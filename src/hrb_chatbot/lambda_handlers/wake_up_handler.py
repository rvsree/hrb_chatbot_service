"""Lambda entry point - public Function URL, called by the frontend the
instant "Sign In" is clicked, before login validation runs. Resumes ONLY
hrb-chatbot - the real fix for Phase 262/286's "hrb-chatbot paused itself
into a dead end" incident (see apprunner_client.py and RAG-ROADMAP.md
Phase 287). Everything else wakes up afterward through the existing
backend-activation flow (Phase 284, routes living on hrb-chatbot itself),
once a login succeeds.

Rate-limited per caller IP (wake_up_limiter.py, configurable via
app_settings, default 10/day) - only when hrb-chatbot is actually PAUSED;
a call that finds it already RUNNING or resuming never touches the
limiter, so a visitor refreshing a few times never burns their quota.

Fails closed throughout: any unexpected error returns "resumed": false
rather than raising. The frontend's own /ping poll against hrb-chatbot
(not this response) is always the real source of truth for whether it's
actually reachable yet.

Postgres/Redis credentials come from Secrets Manager via the shared
lambda_secrets_bootstrap.py (same pattern as idle_auto_pause_handler.py).
This Lambda's own IAM execution role only grants apprunner:DescribeService/
ResumeService on hrb-chatbot's ARN specifically - narrower than the
idle-pause Lambda's role, which needs all 6 services."""

import asyncio
import json
import logging

from src.hrb_chatbot.common.clients.aws_client.apprunner_client import AppRunnerClient
from src.hrb_chatbot.common.clients.aws_client.lambda_secrets_bootstrap import load_secrets_into_env
from src.hrb_chatbot.common.rate_limiting import wake_up_limiter

TARGET_SERVICE_NAME = "hrb-chatbot"

_SECRET_ENV_MAP = {
    "POSTGRES_DB_HOST": "hrb-chatbot/POSTGRES_DB_HOST",
    "POSTGRES_DB_PORT": "hrb-chatbot/POSTGRES_DB_PORT",
    "POSTGRES_DB_NAME": "hrb-chatbot/POSTGRES_DB_NAME",
    "POSTGRES_DB_USER": "hrb-chatbot/POSTGRES_DB_USER",
    "POSTGRES_DB_PASSWORD": "hrb-chatbot/POSTGRES_DB_PASSWORD",
    "REDIS_URL": "hrb-chatbot/REDIS_URL",
}


class _JsonFormatter(logging.Formatter):
    """Same one-JSON-line-per-record shape as idle_auto_pause_handler.py's
    own formatter - CloudWatch Logs Insights queries fields directly."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("lambda_handlers.wake_up")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


logger = _get_logger()


def _extract_source_ip(event: dict) -> str | None:
    """None on any missing/malformed shape - treated the same as "no IP
    known" by wake_up_limiter (always allowed through), never an error
    here."""
    try:
        return event["requestContext"]["http"]["sourceIp"]
    except (KeyError, TypeError):
        return None


def _response(status_code: int, body: dict) -> dict:
    """Lambda Function URL's required response shape - unlike an
    EventBridge-triggered Lambda (idle_auto_pause_handler.py), which can
    return any plain dict."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


async def _resume_if_needed(source_ip: str | None) -> dict:
    statuses = AppRunnerClient().describe_all()
    target = next((service for service in statuses if service["service_name"] == TARGET_SERVICE_NAME), None)

    if target is None:
        logger.error("WAKEUP_FAILURE: %r not found in configured services.", TARGET_SERVICE_NAME)
        return _response(500, {"resumed": False, "error": "hrb-chatbot is not a configured service"})

    if target["status"] == "ERROR":
        logger.warning("WAKEUP_FAILURE: describe_service errored for hrb-chatbot: %s", target.get("error"))
        return _response(502, {"resumed": False, "status": "ERROR", "error": target.get("error")})

    if target["status"] in ("RUNNING", "OPERATION_IN_PROGRESS"):
        logger.info("hrb-chatbot already %s - nothing to resume.", target["status"])
        return _response(200, {"resumed": False, "status": target["status"]})

    under_cap = await wake_up_limiter.check_and_record(source_ip)
    if not under_cap:
        logger.warning("WAKEUP_RATE_LIMITED: IP %r exceeded its daily wake-up cap.", source_ip)
        return _response(429, {"resumed": False, "status": target["status"], "error": "rate_limited"})

    results = AppRunnerClient().resume(service_names=[TARGET_SERVICE_NAME])
    result = results[0] if results else {"status": "ERROR", "error": "no result returned"}
    if result.get("error"):
        logger.error("WAKEUP_FAILURE: resume_service failed for hrb-chatbot: %s", result["error"])
        return _response(502, {"resumed": False, "status": "ERROR", "error": result["error"]})

    logger.info("hrb-chatbot resume triggered - new status %s.", result["status"])
    return _response(200, {"resumed": True, "status": result["status"]})


def lambda_handler(event, context):
    try:
        load_secrets_into_env(_SECRET_ENV_MAP)
        source_ip = _extract_source_ip(event or {})
        return asyncio.run(_resume_if_needed(source_ip))
    except Exception as error:
        # Fail closed - never raise out of a public Function URL handler.
        # The caller always falls back to polling hrb-chatbot's own /ping.
        logger.error("WAKEUP_FAILURE: unexpected error in wake-up handler: %s", error, exc_info=True)
        return _response(200, {"resumed": False, "error": "unexpected_error"})
