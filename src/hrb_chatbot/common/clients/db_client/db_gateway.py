"""One place that hands out every database client the project uses."""

from src.hrb_chatbot.common.clients.cache_client.admin_dashboard_cache import AdminDashboardCache
from src.hrb_chatbot.common.clients.cache_client.answer_cache import AnswerCache
from src.hrb_chatbot.common.clients.cache_client.embedding_cache import EmbeddingCache
from src.hrb_chatbot.common.clients.cache_client.stm_cache import StmCache
from src.hrb_chatbot.common.clients.db_client.admin_credential_store import AdminCredentialStore
from src.hrb_chatbot.common.clients.db_client.agent_thread_store import AgentThreadStore
from src.hrb_chatbot.common.clients.db_client.app_settings_store import AppSettingsStore
from src.hrb_chatbot.common.clients.db_client.base_metadata_client import BaseMetadataClient
from src.hrb_chatbot.common.clients.db_client.base_vector_db_client import BaseVectorDBClient
from src.hrb_chatbot.common.clients.db_client.chat_workflow_store import ChatWorkflowStore
from src.hrb_chatbot.common.clients.db_client.chroma_client import ChromaDBClient
from src.hrb_chatbot.common.clients.db_client.conversation_store import ConversationStore
from src.hrb_chatbot.common.clients.db_client.demo_visitor_store import DemoVisitorStore
from src.hrb_chatbot.common.clients.db_client.doc_metadata_store import DocMetadataStore
from src.hrb_chatbot.common.clients.db_client.eval_run_store import EvalRunStore
from src.hrb_chatbot.common.clients.db_client.faq_submission_store import FaqSubmissionStore
from src.hrb_chatbot.common.clients.db_client.golden_dataset_store import GoldenDatasetStore
from src.hrb_chatbot.common.clients.db_client.interview_qa_store import InterviewQaStore
from src.hrb_chatbot.common.clients.db_client.live_query_store import LiveQueryStore
from src.hrb_chatbot.common.clients.db_client.pipeline_run_store import PipelineRunStore
from src.hrb_chatbot.common.clients.db_client.request_metrics_store import RequestMetricsStore
from src.hrb_chatbot.common.clients.db_client.feedback_store import FeedbackStore
from src.hrb_chatbot.common.clients.db_client.pinecone_client import PineconeClient
from src.hrb_chatbot.common.clients.db_client.postgres_client import PostgresClient
from src.hrb_chatbot.common.clients.db_client.sqlite_client import SQLiteClient
from src.hrb_chatbot.common.clients.db_client.synthetic_dataset_store import SyntheticDatasetStore
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
        self.chat_workflow_store_client = None
        self.feedback_store_client = None
        self.embedding_cache_client = None
        self.answer_cache_client = None
        self.admin_dashboard_cache_client = None
        self.stm_cache_client = None
        self.admin_credential_store_client = None
        self.agent_thread_store_client = None
        self.doc_metadata_store_client = None
        self.golden_dataset_store_client = None
        self.eval_run_store_client = None
        self.request_metrics_store_client = None
        self.pipeline_run_store_client = None
        self.faq_submission_store_client = None
        self.interview_qa_store_client = None
        self.live_query_store_client = None
        self.synthetic_dataset_store_client = None
        self.app_settings_store_client = None
        self.demo_visitor_store_client = None

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

    def chat_workflow_store(self) -> ChatWorkflowStore:
        """Return the shared GenAI Chat Workflow session/turn/email store, building it on first use (Phase 163)."""
        if self.chat_workflow_store_client is None:
            self.chat_workflow_store_client = ChatWorkflowStore()
        return self.chat_workflow_store_client

    def feedback_store(self) -> FeedbackStore:
        """Return the shared feedback store, building it on first use (Phase 104)."""
        if self.feedback_store_client is None:
            self.feedback_store_client = FeedbackStore()
        return self.feedback_store_client

    def admin_credential_store(self) -> AdminCredentialStore:
        """Return the shared admin-credential store, building it on first use (Phase 171)."""
        if self.admin_credential_store_client is None:
            self.admin_credential_store_client = AdminCredentialStore()
        return self.admin_credential_store_client

    def agent_thread_store(self) -> AgentThreadStore:
        """Return the shared agent-thread store, building it on first use (Phase 172)."""
        if self.agent_thread_store_client is None:
            self.agent_thread_store_client = AgentThreadStore()
        return self.agent_thread_store_client

    def doc_metadata_store(self) -> DocMetadataStore:
        """Return the shared doc-metadata store, building it on first use (Phase 170)."""
        if self.doc_metadata_store_client is None:
            self.doc_metadata_store_client = DocMetadataStore()
        return self.doc_metadata_store_client

    def golden_dataset_store(self) -> GoldenDatasetStore:
        """Return the shared golden-dataset store, building it on first use (Phase 181)."""
        if self.golden_dataset_store_client is None:
            self.golden_dataset_store_client = GoldenDatasetStore()
        return self.golden_dataset_store_client

    def live_query_store(self) -> LiveQueryStore:
        """Return the shared live-query capture store, building it on first use (Phase 257)."""
        if self.live_query_store_client is None:
            self.live_query_store_client = LiveQueryStore()
        return self.live_query_store_client

    def demo_visitor_store(self) -> DemoVisitorStore:
        """Return the shared demo-visitor tracking store, building it on first use (Phase 265)."""
        if self.demo_visitor_store_client is None:
            self.demo_visitor_store_client = DemoVisitorStore()
        return self.demo_visitor_store_client

    def synthetic_dataset_store(self) -> SyntheticDatasetStore:
        """Return the shared synthetic-dataset store, building it on first use (Phase 257)."""
        if self.synthetic_dataset_store_client is None:
            self.synthetic_dataset_store_client = SyntheticDatasetStore()
        return self.synthetic_dataset_store_client

    def app_settings_store(self) -> AppSettingsStore:
        """Return the shared generic runtime-settings store, building it on first use (Phase 257)."""
        if self.app_settings_store_client is None:
            self.app_settings_store_client = AppSettingsStore()
        return self.app_settings_store_client

    def eval_run_store(self) -> EvalRunStore:
        """Return the shared eval-run store, building it on first use (Phase 182)."""
        if self.eval_run_store_client is None:
            self.eval_run_store_client = EvalRunStore()
        return self.eval_run_store_client

    def pipeline_run_store(self) -> PipelineRunStore:
        """Return the shared pipeline-run-snapshot store, building it on
        first use (Phase 189)."""
        if self.pipeline_run_store_client is None:
            self.pipeline_run_store_client = PipelineRunStore()
        return self.pipeline_run_store_client

    def request_metrics_store(self) -> RequestMetricsStore:
        """Return the shared request-metrics store, building it on first use (Phase 184)."""
        if self.request_metrics_store_client is None:
            self.request_metrics_store_client = RequestMetricsStore()
        return self.request_metrics_store_client

    def faq_submission_store(self) -> FaqSubmissionStore:
        """Return the shared FAQ-submission store, building it on first use (Phase 186)."""
        if self.faq_submission_store_client is None:
            self.faq_submission_store_client = FaqSubmissionStore()
        return self.faq_submission_store_client

    def interview_qa_store(self) -> InterviewQaStore:
        """Return the shared interview-Q&A store, building it on first use (Phase 187)."""
        if self.interview_qa_store_client is None:
            self.interview_qa_store_client = InterviewQaStore()
        return self.interview_qa_store_client

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

    def admin_dashboard_cache(self) -> AdminDashboardCache:
        """Return the shared Admin Dashboard list-view cache, building it on first use (Phase 276)."""
        if self.admin_dashboard_cache_client is None:
            self.admin_dashboard_cache_client = AdminDashboardCache()
        return self.admin_dashboard_cache_client

    def stm_cache(self) -> StmCache:
        """Return the shared STM cache, building it on first use (Phase 247)."""
        if self.stm_cache_client is None:
            self.stm_cache_client = StmCache()
        return self.stm_cache_client

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
