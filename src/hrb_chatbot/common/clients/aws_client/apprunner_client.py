"""Phase 261 - thin boto3 wrapper over AWS App Runner's describe/resume/
pause APIs, for the admin-only "AWS Demo" Settings tab. Service ARNs come
from config (AWS_DEMO_SERVICES, a JSON array), never hardcoded - this repo
is public, and ARNs shouldn't be literal source code even though they're
lower-sensitivity than a credential (same redaction discipline already
applied to docs/agent-reference/AWS-DEVOPS-RUNBOOK.md).

Every method is per-service fault-isolated: one service's AWS error never
raises out and blocks the other 5 from reporting/acting - matches the
"partial success" failure mode in endpoint-request-response-contracts.md's
AWS Demo section."""

import json

import boto3

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("apprunner_client")

# Phase 262/286 real incident, 2026-10-31 - RESOLVED by Phase 287, not
# just documented history: the idle-timeout Lambda and the sign-out
# accelerant both auto-paused ALL running services, including hrb-chatbot
# itself - the one service hosting the login/resume/sign-out endpoints
# that could ever bring things back. That left a real, self-inflicted
# deadlock, recovered only via direct AWS CLI. The stopgap fix at the
# time was a hrb-chatbot exclusion here, applied by both automated pause
# paths before calling .pause(). Phase 287 replaces that stopgap with a
# real fix - a standalone wake-up Lambda, independent of hrb-chatbot's
# own runtime state, behind its own Function URL - so hrb-chatbot can go
# back to being a normal, auto-pausable service. The exclusion constant/
# helper that used to live here is gone; see RAG-ROADMAP.md Phase 287.


class AppRunnerClient:
    DEFAULT_REGION = "us-east-1"

    def __init__(self, region: str | None = None, services_json: str | None = None):
        self.region = read_setting(region, "AWS_REGION", self.DEFAULT_REGION)
        raw_services = read_setting(services_json, "AWS_DEMO_SERVICES", "[]")
        try:
            self.services: list[dict] = json.loads(raw_services)
        except (json.JSONDecodeError, TypeError):
            logger.warning("AWS_DEMO_SERVICES is not valid JSON - AWS Demo tab will report 0 services")
            self.services = []

        self._services_by_name = {service["service_name"]: service for service in self.services}
        self.client = boto3.client("apprunner", region_name=self.region)

    def _describe_one(self, service: dict) -> dict:
        service_name = service["service_name"]
        try:
            with log_backend_call(logger, "apprunner", "describe_service", service_name=service_name):
                response = self.client.describe_service(ServiceArn=service["arn"])
            status = response["Service"]["Status"]
            return {
                "service_name": service_name,
                "display_name": service["display_name"],
                "status": status,
                "url": service.get("public_url") if status == "RUNNING" else None,
                "error": None,
            }
        except Exception as error:
            logger.warning("describe_service failed for %r: %s", service_name, error)
            return {
                "service_name": service_name,
                "display_name": service["display_name"],
                "status": "ERROR",
                "url": None,
                "error": str(error),
            }

    def describe_all(self) -> list[dict]:
        return [self._describe_one(service) for service in self.services]

    def _resolve_targets(self, service_names: list[str] | None) -> list[dict]:
        if not service_names:
            return self.services
        return [self._services_by_name[name] for name in service_names if name in self._services_by_name]

    def _act_one(self, service: dict, action: str) -> dict:
        service_name = service["service_name"]
        boto_method = self.client.resume_service if action == "resume" else self.client.pause_service
        try:
            with log_backend_call(logger, "apprunner", f"{action}_service", service_name=service_name):
                response = boto_method(ServiceArn=service["arn"])
            status = response["Service"]["Status"]
            return {
                "service_name": service_name,
                "display_name": service["display_name"],
                "status": status,
                "url": None,  # async operation - not RUNNING yet, caller should poll describe_all()
                "error": None,
            }
        except Exception as error:
            logger.warning("%s_service failed for %r: %s", action, service_name, error)
            return {
                "service_name": service_name,
                "display_name": service["display_name"],
                "status": "ERROR",
                "url": None,
                "error": str(error),
            }

    def resume(self, service_names: list[str] | None = None) -> list[dict]:
        return [self._act_one(service, "resume") for service in self._resolve_targets(service_names)]

    def pause(self, service_names: list[str] | None = None) -> list[dict]:
        return [self._act_one(service, "pause") for service in self._resolve_targets(service_names)]
