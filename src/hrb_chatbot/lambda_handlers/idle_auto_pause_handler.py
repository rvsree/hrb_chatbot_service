"""Lambda entry point - EventBridge scheduled rule (every 10-15 min) -> check
the activity_tracker.py signal (Phase 262) -> pause any still-RUNNING App
Runner service past the idle threshold. See RAG-ROADMAP.md Phase 262.

Fails closed toward "leave it running": a missing/unreadable activity
signal, a Postgres outage, or an AppRunnerClient error never raises out of
this handler - each is logged and this run simply does nothing. An
unexpected pause mid-demo is worse than one extra idle billing cycle.

IDLE_AUTOPAUSE_FAILURE is a deliberate, stable log substring - a CloudWatch
Logs Metric Filter on this Lambda's log group matches it, feeding an alarm
that only notifies on repeated real failures, not on routine successful
auto-pauses (user-confirmed preference, 2026-10-31).

Postgres credentials come from Secrets Manager at runtime (`_SECRET_ENV_MAP`
below), fetched into os.environ once per warm execution environment -
deliberately NOT plaintext Lambda environment variables, unlike
index_document_handler.py's own (earlier, Phase 88) Lambda. This Lambda's
own IAM execution role only grants secretsmanager:GetSecretValue on these
5 specific secret ARNs plus the 2 apprunner: actions it needs - it has no
access to any of the LLM/Pinecone/Redis/GitHub secrets that Lambda's own
role has, since this one has no reason to touch any of them.

Phase 287 - this Lambda no longer excludes hrb-chatbot from pausing.
Phase 262/286 originally added that exclusion as a stopgap after
hrb-chatbot auto-pausing itself left no application-level way to resume
anything; Phase 287's new, standalone wake-up Lambda (its own Function
URL, independent of hrb-chatbot's own runtime state) is the real fix, so
hrb-chatbot goes back to being a normal, auto-pausable service here."""

import asyncio
import json
import logging
from datetime import UTC, datetime

from src.hrb_chatbot.common.clients.aws_client.apprunner_client import AppRunnerClient
from src.hrb_chatbot.common.clients.aws_client.lambda_secrets_bootstrap import load_secrets_into_env
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import read_setting

ACTIVITY_SETTING_KEY = "active_user_last_seen_at"
DEFAULT_IDLE_THRESHOLD_MINUTES = 60

_SECRET_ENV_MAP = {
    "POSTGRES_DB_HOST": "hrb-chatbot/POSTGRES_DB_HOST",
    "POSTGRES_DB_PORT": "hrb-chatbot/POSTGRES_DB_PORT",
    "POSTGRES_DB_NAME": "hrb-chatbot/POSTGRES_DB_NAME",
    "POSTGRES_DB_USER": "hrb-chatbot/POSTGRES_DB_USER",
    "POSTGRES_DB_PASSWORD": "hrb-chatbot/POSTGRES_DB_PASSWORD",
}


class _JsonFormatter(logging.Formatter):
    """Same one-JSON-line-per-record shape as index_document_handler.py's
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
    logger = logging.getLogger("lambda_handlers.idle_auto_pause")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


logger = _get_logger()


def _read_idle_threshold_minutes() -> int:
    return int(read_setting(None, "IDLE_AUTO_PAUSE_THRESHOLD_MINUTES", str(DEFAULT_IDLE_THRESHOLD_MINUTES)))


async def _get_last_activity_timestamp() -> datetime | None:
    """None on any read failure or a never-set key - app_settings_store's
    own get_setting() already never raises, falling back to the default
    passed here. A naive (no-tzinfo) string is treated the same as
    missing - every real write is UTC-aware (activity_tracker.py), so a
    naive value is unexpected rather than a case worth guessing about."""
    raw = await get_db_gateway().app_settings_store().get_setting(ACTIVITY_SETTING_KEY, None)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        logger.warning("Activity timestamp %r is not valid ISO 8601 - treating as missing.", raw)
        return None
    if parsed.tzinfo is None:
        logger.warning("Activity timestamp %r has no timezone - treating as missing.", raw)
        return None
    return parsed


async def _check_and_pause_if_idle() -> dict:
    threshold_minutes = _read_idle_threshold_minutes()
    last_seen = await _get_last_activity_timestamp()
    now = datetime.now(UTC)

    if last_seen is None:
        logger.info("No usable activity signal - skipping this run (fail-safe: no signal, no action).")
        return {"action": "skipped", "reason": "no_activity_signal"}

    idle_minutes = (now - last_seen).total_seconds() / 60
    if idle_minutes < threshold_minutes:
        logger.info("Still active - idle %.1f min, threshold %d min.", idle_minutes, threshold_minutes)
        return {"action": "skipped", "reason": "not_idle", "idle_minutes": round(idle_minutes, 1)}

    statuses = AppRunnerClient().describe_all()
    running_names = [service["service_name"] for service in statuses if service["status"] == "RUNNING"]
    if not running_names:
        logger.info("Idle %.1f min, but nothing is RUNNING - nothing to pause.", idle_minutes)
        return {"action": "skipped", "reason": "already_paused", "idle_minutes": round(idle_minutes, 1)}

    logger.info("Idle %.1f min (threshold %d) - pausing %s", idle_minutes, threshold_minutes, running_names)
    results = AppRunnerClient().pause(service_names=running_names)
    errored = [result for result in results if result.get("error")]
    if errored:
        logger.error("IDLE_AUTOPAUSE_FAILURE: %d of %d pause calls failed: %s", len(errored), len(results), errored)
    return {"action": "paused", "idle_minutes": round(idle_minutes, 1), "results": results}


def lambda_handler(event, context):
    try:
        load_secrets_into_env(_SECRET_ENV_MAP)
        result = asyncio.run(_check_and_pause_if_idle())
    except Exception as error:
        # Fail closed - never let an unexpected error surface as a raised
        # Lambda error (which could trigger aggressive EventBridge
        # retries); log under the stable failure marker and return cleanly.
        logger.error("IDLE_AUTOPAUSE_FAILURE: unexpected error in idle-check: %s", error, exc_info=True)
        return {"action": "error", "message": str(error)}
    logger.info(json.dumps(result))
    return result
