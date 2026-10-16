"""Phase 184 - fire-and-forget request-metrics logging for the Deployment
Dashboard's Live Metrics tab. Was an empty scaffold file (CLAUDE.md's own
note: "scaffolding for future phases") - this is that phase. Never allowed
to affect the real response it's logging - every caller wraps the actual
work, catches anything, logs a warning, and returns normally either way."""

import time
from collections.abc import Awaitable, Callable

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("observability.response_metrics")


async def log_response_metrics(
    endpoint: str,
    pipeline: str,
    token_count: int | None,
    latency_ms: int,
    status: str,
    error_code: str | None = None,
) -> None:
    """Best-effort - a logging failure here must never surface to the real
    caller. Each of genai-rag/single-agentic-rag/multi-agentic-rag's own
    route handlers calls this once per response, success or failure."""
    try:
        await get_db_gateway().request_metrics_store().log_request(
            endpoint=endpoint,
            pipeline=pipeline,
            token_count=token_count,
            latency_ms=latency_ms,
            status=status,
            error_code=error_code,
        )
    except Exception as error:
        logger.warning("Could not log request metrics for %s/%s: %s", endpoint, pipeline, error)


async def time_and_log(
    endpoint: str,
    pipeline: str,
    call: Callable[[], Awaitable[dict]],
    extract_token_count: Callable[[dict], int | None],
) -> dict:
    """Wraps one real pipeline call: times it, logs success/failure metrics
    around it, re-raises whatever `call` raised so the route's own existing
    error handling is unaffected - this is purely an observer, never a
    decision-maker in the request's own outcome."""
    started_at = time.monotonic()
    try:
        result = await call()
    except Exception as error:
        latency_ms = int((time.monotonic() - started_at) * 1000)
        await log_response_metrics(endpoint, pipeline, None, latency_ms, "error", type(error).__name__)
        raise

    latency_ms = int((time.monotonic() - started_at) * 1000)
    await log_response_metrics(endpoint, pipeline, extract_token_count(result), latency_ms, "success")
    return result
