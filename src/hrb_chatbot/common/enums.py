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
