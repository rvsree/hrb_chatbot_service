"""Postgres-backed feedback storage (Phase 104) - same psycopg-via-
asyncio.to_thread() pattern as conversation_store.py, not a new pattern."""

import asyncio
import json

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("feedback_store")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
# chat_feedback is new, not in the original planning doc's own schema map -
# a real gap found during that phase's audit (feedback_store.py wasn't
# categorized anywhere in it at all).
_SCHEMA = "hrb_chat_feedback"

CREATE_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS feedback (
    id SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL,
    conversation_id TEXT,
    message_id TEXT NOT NULL,
    vote TEXT NOT NULL,
    reason_tags TEXT NOT NULL,
    notes TEXT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
CREATE_EMPLOYEE_ID_INDEX = "CREATE INDEX IF NOT EXISTS idx_feedback_employee_id ON feedback(employee_id)"


class FeedbackStore:
    """Stores and retrieves feedback entries in Postgres."""

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
            conn.execute(CREATE_FEEDBACK_TABLE)
            conn.execute(CREATE_EMPLOYEE_ID_INDEX)
            conn.commit()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        await asyncio.to_thread(self._ensure_table_sync)
        self._table_ready = True

    @staticmethod
    def _dict_row_factory(cursor):
        columns = [desc.name for desc in cursor.description]
        return lambda values: dict(zip(columns, values, strict=True))

    def _save_feedback_sync(
        self,
        employee_id: str,
        conversation_id: str | None,
        message_id: str,
        vote: str,
        reason_tags: list[str],
        notes: str | None,
        question: str,
        answer: str,
    ) -> int:
        # Same NUL-byte defense as conversation_store.py (Phase 97) - a
        # PDF-ligature artifact can ride into an echoed question/answer.
        question = question.replace("\x00", "")
        answer = answer.replace("\x00", "")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO feedback (employee_id, conversation_id, message_id, vote, reason_tags, "
                "notes, question, answer) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (employee_id, conversation_id, message_id, vote, json.dumps(reason_tags), notes, question, answer),
            )
            feedback_id = cur.fetchone()[0]
            conn.commit()
            return feedback_id

    async def save_feedback(
        self,
        employee_id: str,
        conversation_id: str | None,
        message_id: str,
        vote: str,
        reason_tags: list[str],
        notes: str | None,
        question: str,
        answer: str,
    ) -> int:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "feedback.save", employee_id=employee_id, vote=vote):
            return await asyncio.to_thread(
                self._save_feedback_sync,
                employee_id,
                conversation_id,
                message_id,
                vote,
                reason_tags,
                notes,
                question,
                answer,
            )

    def _list_feedback_sync(self, employee_id: str | None) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                if employee_id is None:
                    cur.execute("SELECT * FROM feedback ORDER BY id DESC")
                else:
                    cur.execute("SELECT * FROM feedback WHERE employee_id = %s ORDER BY id DESC", (employee_id,))
                rows = cur.fetchall()
        for row in rows:
            row["reason_tags"] = json.loads(row["reason_tags"])
            # psycopg returns a real datetime for TIMESTAMPTZ, not a string -
            # converted here so FeedbackRecord's plain `created_at: str`
            # field (matching DocumentRecord's own convention) doesn't choke.
            row["created_at"] = row["created_at"].isoformat()
        return rows

    async def list_feedback(self, employee_id: str | None) -> list[dict]:
        """employee_id=None lists every caller's feedback - only ever passed
        for an hr_support caller, enforced one layer up in the route."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "feedback.list", employee_id=employee_id or "all"):
            return await asyncio.to_thread(self._list_feedback_sync, employee_id)

    def _get_latest_feedback_for_conversation_sync(self, conversation_id: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT * FROM feedback WHERE conversation_id = %s ORDER BY created_at DESC LIMIT 1",
                    (conversation_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        row["reason_tags"] = json.loads(row["reason_tags"])
        row["created_at"] = row["created_at"].isoformat()
        return row

    async def get_latest_feedback_for_conversation(self, conversation_id: str | None) -> dict | None:
        """Phase 248 - the Search Pre-Processing Layer's own feedback-signal
        read. None when conversation_id is falsy or no feedback exists yet -
        never raises, same convention as every other store method here."""
        if not conversation_id:
            return None
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "feedback.get_latest_for_conversation", conversation_id=conversation_id):
            return await asyncio.to_thread(self._get_latest_feedback_for_conversation_sync, conversation_id)

    def _delete_feedback_sync(self, feedback_id: int) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM feedback WHERE id = %s", (feedback_id,))
            conn.commit()
            return cur.rowcount

    async def delete_feedback(self, feedback_id: int) -> int:
        """Phase 168 - admin-only hard delete. Nothing in this store could
        delete anything before this - list_feedback()/save_feedback() were
        the only 2 operations that existed."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "feedback.delete", feedback_id=feedback_id):
            return await asyncio.to_thread(self._delete_feedback_sync, feedback_id)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_FEEDBACK_TABLE)
                conn.execute(CREATE_EMPLOYEE_ID_INDEX)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM feedback").fetchone()
            result["status"] = "healthy"
            result["feedback_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
