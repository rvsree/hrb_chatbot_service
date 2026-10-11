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


class Role(StrEnum):
    """Who's calling the API - HR_SUPPORT uploads documents, all three can retrieve."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR_SUPPORT = "hr_support"


class FeedbackVote(StrEnum):
    """A fixed value set (Phase 104), not a plain str - matches the project's
    own convention for this kind of field."""

    HELPFUL = "helpful"
    NOT_QUITE = "not_quite"
