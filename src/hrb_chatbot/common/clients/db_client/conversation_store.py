"""Postgres-backed conversation history (Phase 76) - STM and LTM are the
same store: every turn is durable (survives restarts, unlike the old
in-memory dict) and the same rows are what gets read back into the next
turn's context. No separate fast/durable tiers yet - Redis is a planned
future migration, not built here. Same psycopg-via-asyncio.to_thread()
pattern as postgres_client.py, not a new pattern invented for this."""

import asyncio

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("conversation_store")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
_SCHEMA = "hrb_rag_retrieval"

CREATE_CONVERSATION_TURNS_TABLE = """
CREATE TABLE IF NOT EXISTS conversation_turns (
    id SERIAL PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    employee_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
CREATE_CONVERSATION_ID_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_conversation_turns_conversation_id ON conversation_turns(conversation_id)"
)


class ConversationStore:
    """Stores and retrieves one conversation's turns in Postgres."""

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

    def get_configuration(self) -> dict:
        return {"host": self.host, "port": self.port, "db_name": self.db_name}

    def _connect(self) -> psycopg.Connection:
        """Synchronous connect - always run this through asyncio.to_thread()."""
        return psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=self.db_name,
            user=self.user,
            password=self.password,
            options=f"-c search_path={_SCHEMA},public",
        )

    def _ensure_table_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_CONVERSATION_TURNS_TABLE)
            conn.execute(CREATE_CONVERSATION_ID_INDEX)
            conn.commit()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        await asyncio.to_thread(self._ensure_table_sync)
        self._table_ready = True

    @staticmethod
    def _dict_row_factory(cursor):
        """Turn each result row into a dict keyed by column name, matching postgres_client.py's row shape."""
        columns = [desc.name for desc in cursor.description]
        return lambda values: dict(zip(columns, values, strict=True))

    def _load_turns_sync(self, conversation_id: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT role, content FROM conversation_turns WHERE conversation_id = %s ORDER BY id ASC",
                    (conversation_id,),
                )
                return cur.fetchall()

    async def load_turns(self, conversation_id: str) -> list[dict]:
        """Returns [] for an unknown/new conversation_id - never raises on an empty result."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "conversation.load_turns", conversation_id=conversation_id):
            return await asyncio.to_thread(self._load_turns_sync, conversation_id)

    def _get_conversation_turns_sync(self, conversation_id: str, employee_id: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT role, content, created_at FROM conversation_turns "
                    "WHERE conversation_id = %s AND employee_id = %s ORDER BY id ASC",
                    (conversation_id, employee_id),
                )
                rows = cur.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
        return rows

    async def get_conversation_turns(self, conversation_id: str, employee_id: str) -> list[dict]:
        """Phase 116 - same employee_id scoping as delete_conversation(): a
        mismatched employee_id (or an unknown id) returns [] rather than
        leaking whether the conversation exists for someone else."""
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "conversation.get_conversation_turns", conversation_id=conversation_id
        ):
            return await asyncio.to_thread(self._get_conversation_turns_sync, conversation_id, employee_id)

    def _get_conversation_turns_any_sync(self, conversation_id: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT role, content, created_at FROM conversation_turns "
                    "WHERE conversation_id = %s ORDER BY id ASC",
                    (conversation_id,),
                )
                rows = cur.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
        return rows

    async def get_conversation_turns_any(self, conversation_id: str) -> list[dict]:
        """Phase 168 (round 3) - admin-only: the full transcript for any
        conversation regardless of owner, for the admin dashboard's own
        review-before-delete popup. Deliberately a separate method from
        get_conversation_turns() above, not an optional-employee_id
        variant of it - same reasoning as delete_conversation_any()."""
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "conversation.get_conversation_turns_any", conversation_id=conversation_id
        ):
            return await asyncio.to_thread(self._get_conversation_turns_any_sync, conversation_id)

    def _list_conversations_sync(self, employee_id: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT conversation_id, role, content, created_at FROM conversation_turns "
                    "WHERE employee_id = %s ORDER BY id ASC",
                    (employee_id,),
                )
                rows = cur.fetchall()

        conversations: dict[str, dict] = {}
        for row in rows:
            conversation_id = row["conversation_id"]
            if conversation_id not in conversations:
                # First turn seen for this conversation_id - always the human
                # question, since every turn is saved in (human, ai) pairs.
                conversations[conversation_id] = {
                    "conversation_id": conversation_id,
                    "title": row["content"],
                    "started_at": row["created_at"],
                    "last_updated_at": row["created_at"],
                }
            else:
                conversations[conversation_id]["last_updated_at"] = row["created_at"]

        ordered = sorted(conversations.values(), key=lambda c: c["last_updated_at"], reverse=True)
        for conversation in ordered:
            conversation["started_at"] = conversation["started_at"].isoformat()
            conversation["last_updated_at"] = conversation["last_updated_at"].isoformat()
        return ordered

    async def list_conversations(self, employee_id: str) -> list[dict]:
        """Phase 116 - one row per distinct conversation_id this employee
        has turns in, newest-activity-first."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "conversation.list_conversations", employee_id=employee_id):
            return await asyncio.to_thread(self._list_conversations_sync, employee_id)

    def _save_turn_sync(self, conversation_id: str, employee_id: str | None, role: str, content: str) -> None:
        # Postgres TEXT columns hard-reject any embedded NUL byte - some
        # PDFs extract ligatures (e.g. "offers" -> "o\x00ers") with one in
        # place of the real character, which rides into an LLM answer that
        # echoes that span verbatim (Phase 97, psycopg.DataError found live).
        content = content.replace("\x00", "")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversation_turns (conversation_id, employee_id, role, content) "
                "VALUES (%s, %s, %s, %s)",
                (conversation_id, employee_id, role, content),
            )
            conn.commit()

    async def save_turn(self, conversation_id: str, employee_id: str | None, role: str, content: str) -> None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "conversation.save_turn", conversation_id=conversation_id):
            await asyncio.to_thread(self._save_turn_sync, conversation_id, employee_id, role, content)

    def _delete_conversation_sync(self, conversation_id: str, employee_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM conversation_turns WHERE conversation_id = %s AND employee_id = %s",
                (conversation_id, employee_id),
            )
            conn.commit()
            return cur.rowcount

    async def delete_conversation(self, conversation_id: str, employee_id: str) -> int:
        """Deletes every turn for one conversation_id, scoped to the caller's own
        employee_id - a mismatched employee_id deletes zero rows rather than
        leaking whether the conversation exists for someone else."""
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "conversation.delete_conversation", conversation_id=conversation_id
        ):
            return await asyncio.to_thread(self._delete_conversation_sync, conversation_id, employee_id)

    def _list_all_conversations_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT conversation_id, employee_id, role, content, created_at FROM conversation_turns "
                    "ORDER BY id ASC"
                )
                rows = cur.fetchall()

        conversations: dict[str, dict] = {}
        for row in rows:
            conversation_id = row["conversation_id"]
            if conversation_id not in conversations:
                conversations[conversation_id] = {
                    "conversation_id": conversation_id,
                    "employee_id": row["employee_id"],
                    "title": row["content"],
                    "started_at": row["created_at"],
                    "last_updated_at": row["created_at"],
                }
            else:
                conversations[conversation_id]["last_updated_at"] = row["created_at"]

        ordered = sorted(conversations.values(), key=lambda c: c["last_updated_at"], reverse=True)
        for conversation in ordered:
            conversation["started_at"] = conversation["started_at"].isoformat()
            conversation["last_updated_at"] = conversation["last_updated_at"].isoformat()
        return ordered

    async def list_all_conversations(self) -> list[dict]:
        """Phase 168 - admin-only: every conversation across every
        employee, newest-activity-first. Unlike list_conversations()
        above, deliberately not scoped to one employee_id - this is the
        one legitimate "see everyone's" case in this store."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "conversation.list_all_conversations"):
            return await asyncio.to_thread(self._list_all_conversations_sync)

    def _delete_conversation_any_sync(self, conversation_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM conversation_turns WHERE conversation_id = %s",
                (conversation_id,),
            )
            conn.commit()
            return cur.rowcount

    async def delete_conversation_any(self, conversation_id: str) -> int:
        """Phase 168 - admin-only: deletes every turn for one
        conversation_id regardless of which employee it belongs to.
        Deliberately a separate method from delete_conversation() above,
        not an optional-employee_id variant of it - keeping the normal,
        self-scoped delete path textually untouched and impossible to
        accidentally widen."""
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "conversation.delete_conversation_any", conversation_id=conversation_id
        ):
            return await asyncio.to_thread(self._delete_conversation_any_sync, conversation_id)

    def health_check(self) -> dict:
        """Report whether this store is usable - connects, creates the table if missing, counts rows."""
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_CONVERSATION_TURNS_TABLE)
                conn.execute(CREATE_CONVERSATION_ID_INDEX)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM conversation_turns").fetchone()
            result["status"] = "healthy"
            result["turns_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
