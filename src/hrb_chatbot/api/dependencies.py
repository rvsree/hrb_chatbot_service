"""Shared request parameters and response helpers for the routers in this folder."""

from fastapi import Query
from fastapi.responses import JSONResponse

from src.hrb_chatbot.common.config.settings import get_active_vector_db, read_setting
from src.hrb_chatbot.common.enums import LlmProvider, MetadataStore, VectorDB

# Query()'s enum default makes /docs render a dropdown and rejects a typo with a 422 before any check runs.
PROVIDER_QUERY = Query(
    default=LlmProvider.OPENAI,
    description="Which LLM provider to check.",
)

# Phase 137: these two now follow the actually-active backend
# (ACTIVE_VECTOR_DB/RAG_METADATA_STORE) instead of a hardcoded chromadb/
# sqlite literal - a bare GET /health (what a real uptime monitor calls)
# was checking the wrong store in production, since it never read env vars.
METADATA_PROVIDER_QUERY = Query(
    default=read_setting(None, "RAG_METADATA_STORE", MetadataStore.SQLITE),
    description="Which document-metadata store to check - defaults to whichever is actually active (RAG_METADATA_STORE).",
)

VECTOR_PROVIDER_QUERY = Query(
    default=get_active_vector_db(),
    description=(
        "Which vector store to check - defaults to whichever is actually "
        "active (ACTIVE_VECTOR_DB). Checking a non-default provider will "
        "create its configured index/collection on first call if it "
        "doesn't exist yet."
    ),
)


def json_error(
    status_code: int, message: str, code: str, headers: dict | None = None, **extra
) -> JSONResponse:
    """Build a consistent error shape: {"error": ..., "code": ..., ...extra}."""
    body = {"error": message, "code": code}
    body.update(extra)
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def health_response(report: dict) -> JSONResponse:
    """Turn a health report into a response - 200 when healthy, 503 otherwise."""
    if report["status"] == "healthy":
        status_code = 200
    else:
        status_code = 503
    return JSONResponse(content=report, status_code=status_code)
