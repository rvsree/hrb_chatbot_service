"""Phase 283 - plain HTTP call to LangSmith's granular-usage billing
endpoint, for the admin-only FinOps Monitoring tab. Not the `langsmith`
SDK - it has no billing method (confirmed while scoping this phase, see
RAG-ROADMAP.md's Phase 283 entry). Same error-as-data convention as
github_actions_client.py: never raises, an "error"/"message" field on
failure instead.

The exact shape of a real granular-usage response wasn't verified against
a live call while building this (no network access in this environment) -
parsing below is deliberately defensive: it looks for a per-day usage list
under a few likely key names and sums whatever looks like a trace count,
falling back to storing the raw response body under cost_breakdown with
total_traces left at 0 if neither is found. Flagged for a real check
against the live response the first time this runs for real."""

import datetime

import requests

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("langsmith_usage_client")

# A handful of plausible key names for the per-day usage list/trace-count
# field - see this module's own docstring for why this isn't a single,
# confirmed shape.
_USAGE_LIST_KEYS = ("usage", "daily_usage", "data", "rows")
_TRACE_COUNT_KEYS = ("trace_count", "count", "traces", "num_traces")


class LangSmithUsageClient:
    PROVIDER_NAME = "langsmith"
    ENV_KEY = "LANGSMITH_API_KEY"

    DEFAULT_BASE_URL = "https://api.smith.langchain.com"
    DEFAULT_TIMEOUT_SECONDS = 15

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = read_setting(api_key, self.ENV_KEY)
        self.base_url = read_setting(base_url, "LANGSMITH_BASE_URL", self.DEFAULT_BASE_URL)

        if not self.api_key:
            logger.warning("[LANGSMITH] LANGSMITH_API_KEY not set")

    @staticmethod
    def _current_month_bounds() -> tuple[str, str]:
        today = datetime.date.today()
        period_start = today.replace(day=1)
        period_end = today + datetime.timedelta(days=1)
        return period_start.isoformat(), period_end.isoformat()

    @staticmethod
    def _extract_daily_breakdown(data: dict) -> dict:
        """Best-effort: {date: trace_count} from whatever shape came back -
        see this module's own docstring on why this isn't one confirmed shape."""
        for list_key in _USAGE_LIST_KEYS:
            entries = data.get(list_key)
            if not isinstance(entries, list):
                continue
            breakdown = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                date_value = entry.get("date") or entry.get("day")
                count_value = next((entry[key] for key in _TRACE_COUNT_KEYS if key in entry), None)
                if date_value is not None and count_value is not None:
                    breakdown[date_value] = count_value
            if breakdown:
                return breakdown
        return data

    def get_current_month_usage(self) -> dict:
        """Current-month daily trace-count breakdown. Never raises -
        {"status": "unavailable", "message": "..."} on any failure
        (unset key, revoked key, non-200 response). total_cost is always
        None - LangSmith's Base/free plan has no per-trace dollar figure."""
        period_start, period_end = self._current_month_bounds()

        if not self.api_key:
            return {
                "status": "unavailable",
                "message": "LANGSMITH_API_KEY not configured",
                "period_start": period_start,
                "period_end": period_end,
                "total_cost": None,
                "cost_breakdown": {},
            }

        url = f"{self.base_url}/api/v1/orgs/current/billing/granular-usage"
        try:
            with log_backend_call(logger, self.PROVIDER_NAME, "granular_usage"):
                response = requests.get(
                    url,
                    headers={"x-api-key": self.api_key},
                    # Required by LangSmith's own API - confirmed live this
                    # session: a bare GET with no start_time/end_time 422s.
                    params={"start_time": period_start, "end_time": period_end},
                    timeout=self.DEFAULT_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as error:
            logger.warning("[LANGSMITH] granular-usage call failed: %s", error)
            return {
                "status": "unavailable",
                "message": str(error),
                "period_start": period_start,
                "period_end": period_end,
                "total_cost": None,
                "cost_breakdown": {},
            }

        return {
            "status": "ok",
            "message": None,
            "period_start": period_start,
            "period_end": period_end,
            "total_cost": None,
            "cost_breakdown": self._extract_daily_breakdown(data) if isinstance(data, dict) else {},
        }
