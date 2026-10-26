"""Fixed value sets for "which backend" fields, as StrEnum - FastAPI rejects an unknown value with a 422."""

from enum import StrEnum


class VectorDB(StrEnum):
    """Which vector store holds document chunks - see db_gateway.DBGateway.vector_store()."""

    CHROMADB = "chromadb"
    PINECONE = "pinecone"


class MetadataStore(StrEnum):
    """Which store holds one row per uploaded document - see db_gateway.DBGateway.metadata_store()."""

    SQLITE = "sqlite"
    POSTGRES = "postgres"


class Application(StrEnum):
    """Phase 255 - which real deployable the CI/CD Pipeline Visibility
    dashboard is showing. Rebuilt for the real 7-repo split - Phase 233's
    original 4-member set (backend/ingestion_lambda/lms_mcp/frontend)
    predates it. Each member below is its own GitHub repo now except
    BACKEND (hrb_chatbot_service, unchanged) and LMS_MCP (rvsree/hrb_lms_mcp,
    unchanged - a genuinely separate project). INGESTION_LAMBDA was dropped
    as its own member: hrb_chatbot_service's own deploy-lambda.yml/Lambda
    is confirmed superseded (its SQS trigger is disabled) by RAG_INGESTION's
    own Lambda - see RAG-ROADMAP.md's Phase 255 entry for the live
    verification."""

    FRONTEND = "frontend"
    GATEWAY = "gateway"
    BACKEND = "backend"
    RAG_INGESTION = "rag_ingestion"
    RAG_RETRIEVAL = "rag_retrieval"
    PLATFORM_COMPONENTS = "platform_components"
    COMMON_LIBS = "common_libs"
    LMS_MCP = "lms_mcp"


class LlmProvider(StrEnum):
    """Which chat LLM provider to use - see client_gateway.ClientGateway."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"
    BEDROCK = "bedrock"


class ChunkingStrategy(StrEnum):
    """How to split text into chunks - must keep matching text_chunker.CHUNKING_STRATEGIES."""

    FIXED = "fixed"
    RECURSIVE = "recursive"
    SEMANTIC = "semantic"
    MARKDOWN = "markdown"
    HTML = "html"
    NONE = "none"
    DOCUMENT_STRUCTURE = "document_structure"


class SearchStrategy(StrEnum):
    """Which retrieval technique to run a query with - must keep matching retriever.SEARCH_STRATEGIES."""

    SIMILARITY = "similarity"
    MMR = "mmr"
    KEYWORD = "keyword"
    HYBRID = "hybrid"
    KNN = "knn"
    # Phase 252 - auto-picks a real strategy per query via
    # dynamic_strategy_selector.py; never reaches SEARCH_STRATEGIES itself,
    # resolved to a concrete value before retrieval runs.
    DYNAMIC = "dynamic"


class Role(StrEnum):
    """Who's calling the API - HR_SUPPORT uploads documents, all three can retrieve.
    Phase 168 - ADMIN: a separate "manage the application" super-user role,
    not an elevated HR_SUPPORT - reviews leave requests vs. deletes any
    record across the app are genuinely different concerns.
    2026-10-15 - EMPLOYEE_ADMIN: a second, narrower admin tier ("Employee
    Admin") - KB documents/conversations/feedback/leave-requests oversight,
    same as ADMIN, but never Architecture Docs or any future
    build/deployment/evals view. ADMIN itself is unchanged in meaning
    ("Engineering Admin" - everything), not renamed."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR_SUPPORT = "hr_support"
    ADMIN = "admin"
    EMPLOYEE_ADMIN = "employee_admin"


class FeedbackVote(StrEnum):
    """A fixed value set (Phase 104), not a plain str - matches the project's
    own convention for this kind of field."""

    HELPFUL = "helpful"
    NOT_QUITE = "not_quite"


class LeaveTypeCode(StrEnum):
    """Phase 165 - the 4 specialist-reviewed leave types "Request Unpaid
    Leave" now covers (expanded past UNPAID-only); must keep matching
    hrb_lms_mcp's own leave_types seed rows (a separate repo/database, not
    enforceable at the type-checker level - kept in sync by hand)."""

    UNPAID = "UNPAID"
    CRITICAL_CAREGIVER = "CRITICAL_CAREGIVER"
    STD = "STD"
    LTD = "LTD"
