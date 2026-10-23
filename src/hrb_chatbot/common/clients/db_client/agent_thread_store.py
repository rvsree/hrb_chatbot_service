"""Phase 172 - maps a HITL request's hitl_request_context_id to the
LangGraph thread_id its originating "Request Unpaid Leave" graph run is
checkpointed under, so a later /resolve call (which only knows
hitl_request_context_id, the existing API contract) can find the right
paused thread to resume. Pure orchestration metadata this project owns
itself - hrb_lms_mcp has no reason to know about LangGraph thread ids.
Same psycopg + asyncio.to_thread() pattern as every other store here."""

import asyncio

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("agent_thread_store")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
_SCHEMA = "hrb_chat_hitl"

CREATE_AGENT_THREADS_TABLE = """
CREATE TABLE IF NOT EXISTS agent_threads (
    hitl_request_context_id INTEGER PRIMARY KEY,
    agent_thread_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class AgentThreadStore:
    PROVIDER_NAME = "postgres"
    ENV_KEY = "POSTGRES_DB_HOST"

    DEFAULT_PORT = "5432"

    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        db_name: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        self.host = read_setting(host, "POSTGRES_DB_HOST")
        self.port = read_setting(port, "POSTGRES_DB_PORT", self.DEFAULT_PORT)
        self.db_name = read_setting(db_name, "POSTGRES_DB_NAME")
        self.user = read_setting(user, "POSTGRES_DB_USER")
        self.password = read_setting(password, "POSTGRES_DB_PASSWORD")

        if not self.host:
            logger.warning("[POSTGRES] POSTGRES_DB_HOST not set")

        self._table_ready = False

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.host, port=self.port, dbname=self.db_name, user=self.user, password=self.password,
        )

    def _ensure_table_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_AGENT_THREADS_TABLE)
            conn.commit()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        await asyncio.to_thread(self._ensure_table_sync)
        self._table_ready = True

    def _save_thread_mapping_sync(self, hitl_request_context_id: int, agent_thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO agent_threads (hitl_request_context_id, agent_thread_id) VALUES (%s, %s) "
                "ON CONFLICT (hitl_request_context_id) DO UPDATE SET agent_thread_id = EXCLUDED.agent_thread_id",
                (hitl_request_context_id, agent_thread_id),
            )
            conn.commit()

    async def save_thread_mapping(self, hitl_request_context_id: int, agent_thread_id: str) -> None:
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "agent_threads.save", hitl_request_context_id=hitl_request_context_id
        ):
            await asyncio.to_thread(self._save_thread_mapping_sync, hitl_request_context_id, agent_thread_id)

    def _get_thread_id_sync(self, hitl_request_context_id: int) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT agent_thread_id FROM agent_threads WHERE hitl_request_context_id = %s",
                (hitl_request_context_id,),
            ).fetchone()
            return row[0] if row else None

    async def get_thread_id(self, hitl_request_context_id: int) -> str | None:
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "agent_threads.get", hitl_request_context_id=hitl_request_context_id
        ):
            return await asyncio.to_thread(self._get_thread_id_sync, hitl_request_context_id)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_AGENT_THREADS_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM agent_threads").fetchone()
            result["status"] = "healthy"
            result["agent_threads_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
