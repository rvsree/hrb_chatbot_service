"""Phase 283 - thin boto3 wrapper over AWS Cost Explorer's
get_cost_and_usage, for the admin-only FinOps Monitoring tab. Same
error-as-data convention as apprunner_client.py: a ClientError/
AccessDeniedException (the real, current state - the App Runner
instance role has no Cost Explorer permission yet, see RAG-ROADMAP.md's
Phase 283 entry) never raises, it comes back as {"status": "unavailable",
"message": ...} instead."""

import datetime

import boto3

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("aws_cost_client")


class AwsCostClient:
    PROVIDER_NAME = "aws_cost_explorer"
    DEFAULT_REGION = "us-east-1"

    def __init__(self, region: str | None = None):
        self.region = read_setting(region, "AWS_REGION", self.DEFAULT_REGION)
        # Cost Explorer is a global/billing API - "ce" still needs a
        # region to construct the client, same as every other boto3 client.
        self.client = boto3.client("ce", region_name=self.region)

    @staticmethod
    def _current_month_bounds() -> tuple[str, str]:
        today = datetime.date.today()
        period_start = today.replace(day=1)
        # Cost Explorer's own End is exclusive - tomorrow, not today, so
        # today's own usage is included in the range.
        period_end = today + datetime.timedelta(days=1)
        return period_start.isoformat(), period_end.isoformat()

    def get_current_month_cost(self) -> dict:
        """Current-month total cost + per-service breakdown. Never raises -
        {"status": "unavailable", "message": "..."} on any AWS-side
        failure (AccessDeniedException is the real, current state)."""
        period_start, period_end = self._current_month_bounds()
        try:
            with log_backend_call(logger, self.PROVIDER_NAME, "get_cost_and_usage"):
                response = self.client.get_cost_and_usage(
                    TimePeriod={"Start": period_start, "End": period_end},
                    Granularity="MONTHLY",
                    Metrics=["UnblendedCost"],
                    GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
                )
        except Exception as error:
            logger.warning("[AWS_COST_EXPLORER] get_cost_and_usage failed: %s", error)
            return {
                "status": "unavailable",
                "message": str(error),
                "period_start": period_start,
                "period_end": period_end,
                "total_cost": None,
                "cost_breakdown": {},
            }

        cost_breakdown = {}
        total_cost = 0.0
        for result in response.get("ResultsByTime", []):
            for group in result.get("Groups", []):
                service_name = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                cost_breakdown[service_name] = cost_breakdown.get(service_name, 0.0) + amount
                total_cost += amount

        return {
            "status": "ok",
            "message": None,
            "period_start": period_start,
            "period_end": period_end,
            "total_cost": round(total_cost, 2),
            "cost_breakdown": {service: round(amount, 2) for service, amount in cost_breakdown.items()},
        }
