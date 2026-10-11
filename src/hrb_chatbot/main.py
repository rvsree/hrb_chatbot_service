from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from src.hrb_chatbot.api.adhoc_chat import adhoc_document_chat
from src.hrb_chatbot.api.admin import routes_health
from src.hrb_chatbot.api.agentic_rag import query_agent
from src.hrb_chatbot.api.auth import login
from src.hrb_chatbot.api.conversations import manage_conversations
from src.hrb_chatbot.api.feedback import manage_feedback
from src.hrb_chatbot.api.multi_agentic_rag import query_agent as multi_query_agent
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.rag import ingest_document, retrieve_document
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.observability.langsmith_tracing import enable_tracing_if_configured
from src.hrb_chatbot.common.observability.mcp_registry_startup import register_configured_mcp_servers

logger = get_logger("main")

enable_tracing_if_configured()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Phase 50: best-effort - a down MCP server or unreachable registry
    database must never stop the app from starting."""
    try:
        await register_configured_mcp_servers()
    except Exception as error:
        logger.warning("MCP registry startup failed, app starting anyway: %s", error)
    yield


app = FastAPI(
    title="HRB Chatbot",
    version="0.1.0",
    description="An HR benefits chatbot backed by a RAG pipeline over the JPMC benefits knowledge base.",
    lifespan=lifespan,
)

# Phase 95: hrb_chatbot_ui (a separate React/Vite repo) calls this API
# straight from the browser - without CORS headers, the browser blocks
# the call before it reaches any route below, regardless of this API's
# own logic. No cookie-based session exists to protect against CSRF, so
# allow_credentials is safe here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "https://hrb-chatbot-ui.rvsree.dev"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Phase 94: the /hrb-chatbot context path (Phase 92) is gone - the
# project now gets its own subdomain (hrb-chatbot.rvsree.dev) instead of
# sharing one path-routed domain, so the path-level project name was
# redundant. The temporary dual root+prefix health registration used
# during rollout is gone too - App Runner's own HealthCheckConfiguration
# has been switched back to /health and confirmed healthy there.
app.include_router(routes_health.router)

app.include_router(login.router_login, prefix="/v1/auth")
app.include_router(ingest_document.router_ingest_document, prefix="/v1/genai-rag/ingest-document")
# Phase 99: retrieval paths renamed to a consistent -retrieval suffix -
# ingestion above is untouched, not part of that rename.
app.include_router(retrieve_document.router_retrieve_document, prefix="/v1/genai-rag-retrieval")
app.include_router(query_agent.router_query_agent, prefix="/v1/single-agentic-rag-retrieval")
app.include_router(multi_query_agent.router_query_agent, prefix="/v1/multi-agentic-rag-retrieval")
app.include_router(manage_conversations.router_manage_conversations, prefix="/v1/conversations")
app.include_router(manage_feedback.router_manage_feedback, prefix="/v1/feedback")
app.include_router(adhoc_document_chat.router_adhoc_document_chat, prefix="/v1/adhoc-document-chat")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = jsonable_encoder(exc.errors(), custom_encoder={bytes: lambda value: value.decode("utf-8", errors="replace")})
    return json_error(422, "Request validation failed.", code=error_codes.VALIDATION_ERROR, details=details)


_ERROR_CODES_BY_STATUS = {
    401: error_codes.UNAUTHENTICATED,
    403: error_codes.FORBIDDEN,
    422: error_codes.VALIDATION_ERROR,
    429: error_codes.RATE_LIMITED,
}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = _ERROR_CODES_BY_STATUS.get(exc.status_code, error_codes.INTERNAL_ERROR)
    return json_error(exc.status_code, str(exc.detail), code=code, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception on %s %s: %s: %s",
        request.method,
        request.url.path,
        type(exc).__name__,
        exc,
        exc_info=exc,
    )
    return json_error(500, "An internal error occurred. Please try again or contact support.", code=error_codes.INTERNAL_ERROR)
