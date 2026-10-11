"""One place that hands out every database client the project uses."""

from src.hrb_chatbot.common.clients.cache_client.answer_cache import AnswerCache
from src.hrb_chatbot.common.clients.cache_client.embedding_cache import EmbeddingCache
from src.hrb_chatbot.common.clients.db_client.base_metadata_client import BaseMetadataClient
from src.hrb_chatbot.common.clients.db_client.base_vector_db_client import BaseVectorDBClient
from src.hrb_chatbot.common.clients.db_client.chroma_client import ChromaDBClient
from src.hrb_chatbot.common.clients.db_client.conversation_store import ConversationStore
from src.hrb_chatbot.common.clients.db_client.feedback_store import FeedbackStore
from src.hrb_chatbot.common.clients.db_client.pinecone_client import PineconeClient
from src.hrb_chatbot.common.clients.db_client.postgres_client import PostgresClient
from src.hrb_chatbot.common.clients.db_client.sqlite_client import SQLiteClient
from src.hrb_chatbot.common.config.settings import get_active_vector_db, get_app_environment, read_setting
from src.hrb_chatbot.common.enums import MetadataStore, VectorDB

# Phase 137: chromadb/sqlite are local-disk stores - never shared across App
# Runner's multiple instances, never reachable by the separate Lambda
# ingestion worker. A production request/default that resolves to either is
# never a legitimate choice there, only a silent split-brain footgun.
_LOCAL_ONLY_STORES_BLOCKED_IN_PRODUCTION = "{provider!r} is a local-disk store and is disabled when APP_ENVIRONMENT=production (Phase 137) - use {expected!r} instead."


class DBGateway:
   # Creates each database client once, then returns that same client every time.

    def __init__(self):
        self.chroma_client = None
        self.pinecone_client = None
        self.sqlite_client = None
        self.postgres_client = None
        self.conversation_store_client = None
        self.feedback_store_client = None
        self.embedding_cache_client = None
        self.answer_cache_client = None

    def chroma(self) -> ChromaDBClient:
        # Return the shared ChromaDB client, building it on first use.
        if self.chroma_client is None:
            self.chroma_client = ChromaDBClient()
        return self.chroma_client

    def pinecone(self) -> PineconeClient:
        # Return the shared Pinecone client, building it on first use.
        if self.pinecone_client is None:
            self.pinecone_client = PineconeClient()
        return self.pinecone_client

    def vector_store(self, provider: str | None = None) -> BaseVectorDBClient:
        """Return whichever vector store is selected."""
        provider = get_active_vector_db(provider)

        if provider == VectorDB.CHROMADB:
            if get_app_environment() == "production":
                raise ValueError(
                    _LOCAL_ONLY_STORES_BLOCKED_IN_PRODUCTION.format(provider=provider, expected=VectorDB.PINECONE.value)
                )
            return self.chroma()
        if provider == VectorDB.PINECONE:
            return self.pinecone()

        raise ValueError(f"Unknown vector store {provider!r} - use one of {[member.value for member in VectorDB]}")

    def sqlite(self) -> SQLiteClient:
        """Return the shared SQLite client, building it on first use."""
        if self.sqlite_client is None:
            self.sqlite_client = SQLiteClient()
        return self.sqlite_client

    def postgres(self) -> PostgresClient:
        """Return the shared Postgres client, building it on first use."""
        if self.postgres_client is None:
            self.postgres_client = PostgresClient()
        return self.postgres_client

    def conversation_store(self) -> ConversationStore:
        """Return the shared conversation-history store, building it on first use (Phase 76)."""
        if self.conversation_store_client is None:
            self.conversation_store_client = ConversationStore()
        return self.conversation_store_client

    def feedback_store(self) -> FeedbackStore:
        """Return the shared feedback store, building it on first use (Phase 104)."""
        if self.feedback_store_client is None:
            self.feedback_store_client = FeedbackStore()
        return self.feedback_store_client

    def embedding_cache(self) -> EmbeddingCache:
        """Return the shared embedding cache, building it on first use (Phase 77)."""
        if self.embedding_cache_client is None:
            self.embedding_cache_client = EmbeddingCache()
        return self.embedding_cache_client

    def answer_cache(self) -> AnswerCache:
        """Return the shared answer cache, building it on first use (Phase 78)."""
        if self.answer_cache_client is None:
            self.answer_cache_client = AnswerCache()
        return self.answer_cache_client

    def metadata_store(self, provider: str | None = None) -> BaseMetadataClient:
        # Return whichever document-metadata store is selected.
        provider = provider or read_setting(None, "RAG_METADATA_STORE", MetadataStore.SQLITE)

        if provider == MetadataStore.SQLITE:
            if get_app_environment() == "production":
                raise ValueError(
                    _LOCAL_ONLY_STORES_BLOCKED_IN_PRODUCTION.format(provider=provider, expected=MetadataStore.POSTGRES.value)
                )
            return self.sqlite()
        if provider == MetadataStore.POSTGRES:
            return self.postgres()

        raise ValueError(
            f"Unknown metadata store {provider!r} - use one of {[member.value for member in MetadataStore]}"
        )


# The single gateway shared by the whole program - same convention as client_gateway.py's _shared_gateway.
_shared_db_gateway = None


def get_db_gateway() -> DBGateway:
    # Return the one shared DBGateway, creating it on the first call.
    global _shared_db_gateway

    if _shared_db_gateway is None:
        _shared_db_gateway = DBGateway()

    return _shared_db_gateway


def reset_db_gateway():
    global _shared_db_gateway
    _shared_db_gateway = None
