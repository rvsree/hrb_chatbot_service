"""Phase 163 - Postgres-backed session memory for the GenAI Chat Workflow,
deliberately separate from conversation_store.py (genai-rag/single/multi-
agentic-rag's own memory) - different shape (file attachments, email
events), same database. Postgres-only, same psycopg-via-asyncio.to_thread()
pattern as conversation_store.py/postgres_client.py - this project's own
closest precedent for "should this be swappable with SQLite" already
answered no (conversation_store.py has no SQLite fallback either), so this
mirrors that instead of inventing a new dual-backend client."""

import asyncio
import json
import uuid

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("chat_workflow_store")

CREATE_CHAT_SESSION_RECORDS_TABLE = """
CREATE TABLE IF NOT EXISTS chat_session_records (
    session_id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    full_name TEXT,
    session_title TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_count_total INTEGER NOT NULL DEFAULT 0
)
"""

CREATE_CHAT_TURN_RECORDS_TABLE = """
CREATE TABLE IF NOT EXISTS chat_turn_records (
    turn_id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    turn_sequence_number INTEGER NOT NULL,
    user_query_text TEXT NOT NULL,
    agent_response_text TEXT NOT NULL,
    attached_file_names TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
CREATE_CHAT_TURN_SESSION_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_chat_turn_records_session ON chat_turn_records(session_id, turn_sequence_number)"
)

CREATE_EMAIL_SEND_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS email_send_events (
    event_id SERIAL PRIMARY KEY,
    turn_id INTEGER NOT NULL,
    recipient_email_address TEXT NOT NULL,
    cc_email_addresses TEXT,
    email_subject_line TEXT NOT NULL,
    email_status TEXT NOT NULL,
    send_status_message TEXT NOT NULL,
    attached_file_names TEXT NOT NULL DEFAULT '[]',
    trigger_source TEXT NOT NULL,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
CREATE_EMAIL_EVENT_TURN_INDEX = "CREATE INDEX IF NOT EXISTS idx_email_send_events_turn ON email_send_events(turn_id)"


class ChatWorkflowStore:
    """Stores and retrieves the GenAI Chat Workflow's own session/turn/email history in Postgres."""

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

        self._tables_ready = False

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
        )

    def _ensure_tables_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_CHAT_SESSION_RECORDS_TABLE)
            conn.execute(CREATE_CHAT_TURN_RECORDS_TABLE)
            conn.execute(CREATE_CHAT_TURN_SESSION_INDEX)
            conn.execute(CREATE_EMAIL_SEND_EVENTS_TABLE)
            conn.execute(CREATE_EMAIL_EVENT_TURN_INDEX)
            conn.commit()

    async def _ensure_tables(self) -> None:
        if self._tables_ready:
            return
        await asyncio.to_thread(self._ensure_tables_sync)
        self._tables_ready = True

    @staticmethod
    def _dict_row_factory(cursor):
        columns = [desc.name for desc in cursor.description]
        return lambda values: dict(zip(columns, values, strict=True))

    @staticmethod
    def new_session_id() -> str:
        return uuid.uuid4().hex

    def _start_or_touch_session_sync(self, session_id: str, employee_id: str, full_name: str | None, session_title: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO chat_session_records (session_id, employee_id, full_name, session_title, turn_count_total) "
                "VALUES (%s, %s, %s, %s, 1) "
                "ON CONFLICT (session_id) DO UPDATE SET "
                "last_active = now(), turn_count_total = chat_session_records.turn_count_total + 1",
                (session_id, employee_id, full_name, session_title),
            )
            conn.commit()

    async def start_or_touch_session(self, session_id: str, employee_id: str, full_name: str | None, session_title: str) -> None:
        """Creates the session row on its first turn (session_title/employee_id/
        full_name set once, never overwritten), or just bumps last_active/
        turn_count_total on every later turn - one call handles both, no
        separate "does this session already exist" check needed. Caller must
        call this exactly once per turn, immediately before save_turn() -
        turn_count_total counts calls to this method, not rows in
        chat_turn_records, so the two only stay in lockstep if the caller
        keeps that 1:1 pairing (confirmed by a live round-trip test that
        caught the original off-by-one before this fix: the first INSERT
        used to set turn_count_total=0, undercounting every session by 1)."""
        await self._ensure_tables()
        with log_backend_call(logger, "postgres", "chat_workflow.start_or_touch_session", session_id=session_id):
            await asyncio.to_thread(self._start_or_touch_session_sync, session_id, employee_id, full_name, session_title)

    def _load_turns_sync(self, session_id: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT user_query_text, agent_response_text, created_at FROM chat_turn_records "
                    "WHERE session_id = %s ORDER BY turn_sequence_number ASC",
                    (session_id,),
                )
                rows = cur.fetchall()
        # created_at added for Phase 165's sidebar history view - _build_chat_history()
        # (adhoc_document_chat.py) only ever reads the other 2 keys, so this is additive.
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
        return rows

    async def load_turns(self, session_id: str) -> list[dict]:
        """Returns [] for an unknown/new session_id - never raises on an empty result."""
        await self._ensure_tables()
        with log_backend_call(logger, "postgres", "chat_workflow.load_turns", session_id=session_id):
            return await asyncio.to_thread(self._load_turns_sync, session_id)

    def _save_turn_sync(
        self, session_id: str, employee_id: str, user_query_text: str, agent_response_text: str, attached_file_names: list[str]
    ) -> int:
        # Same Postgres TEXT-column NUL-byte guard conversation_store.py
        # already needed (Phase 97) - a PDF-extracted ligature can embed one.
        user_query_text = user_query_text.replace("\x00", "")
        agent_response_text = agent_response_text.replace("\x00", "")
        with self._connect() as conn:
            row = conn.execute(
                "INSERT INTO chat_turn_records "
                "(session_id, employee_id, turn_sequence_number, user_query_text, agent_response_text, attached_file_names) "
                "VALUES (%s, %s, (SELECT COALESCE(MAX(turn_sequence_number), 0) + 1 FROM chat_turn_records WHERE session_id = %s), %s, %s, %s) "
                "RETURNING turn_id",
                (session_id, employee_id, session_id, user_query_text, agent_response_text, json.dumps(attached_file_names)),
            ).fetchone()
            conn.commit()
            return row[0]

    async def save_turn(
        self, session_id: str, employee_id: str, user_query_text: str, agent_response_text: str, attached_file_names: list[str]
    ) -> int:
        """Returns the new turn's turn_id - the caller needs it to attach any email_send_events row to this turn."""
        await self._ensure_tables()
        with log_backend_call(logger, "postgres", "chat_workflow.save_turn", session_id=session_id):
            return await asyncio.to_thread(
                self._save_turn_sync, session_id, employee_id, user_query_text, agent_response_text, attached_file_names
            )

    def _save_email_event_sync(
        self,
        turn_id: int,
        recipient_email_address: str,
        cc_email_addresses: str | None,
        email_subject_line: str,
        email_status: str,
        send_status_message: str,
        attached_file_names: list[str],
        trigger_source: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO email_send_events "
                "(turn_id, recipient_email_address, cc_email_addresses, email_subject_line, email_status, "
                "send_status_message, attached_file_names, trigger_source) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    turn_id,
                    recipient_email_address,
                    cc_email_addresses,
                    email_subject_line,
                    email_status,
                    send_status_message,
                    json.dumps(attached_file_names),
                    trigger_source,
                ),
            )
            conn.commit()

    async def save_email_event(
        self,
        turn_id: int,
        recipient_email_address: str,
        cc_email_addresses: str | None,
        email_subject_line: str,
        email_status: str,
        send_status_message: str,
        attached_file_names: list[str],
        trigger_source: str,
    ) -> None:
        await self._ensure_tables()
        with log_backend_call(logger, "postgres", "chat_workflow.save_email_event", turn_id=turn_id):
            await asyncio.to_thread(
                self._save_email_event_sync,
                turn_id,
                recipient_email_address,
                cc_email_addresses,
                email_subject_line,
                email_status,
                send_status_message,
                attached_file_names,
                trigger_source,
            )

    def _list_sessions_sync(self, employee_id: str) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT session_id, session_title, started_at, last_active, turn_count_total "
                    "FROM chat_session_records WHERE employee_id = %s ORDER BY last_active DESC",
                    (employee_id,),
                )
                rows = cur.fetchall()
        for row in rows:
            row["started_at"] = row["started_at"].isoformat()
            row["last_active"] = row["last_active"].isoformat()
        return rows

    async def list_sessions(self, employee_id: str) -> list[dict]:
        """Phase 163 - built now so a later left-panel "GENAI RAG WORKFLOW
        HISTORY" UI slice isn't blocked on backend work; not wired into any
        route yet this phase (scoped down deliberately, see RAG-ROADMAP.md)."""
        await self._ensure_tables()
        with log_backend_call(logger, "postgres", "chat_workflow.list_sessions", employee_id=employee_id):
            return await asyncio.to_thread(self._list_sessions_sync, employee_id)

    def health_check(self) -> dict:
        """Report whether this store is usable - connects, creates the tables if missing, counts rows."""
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_CHAT_SESSION_RECORDS_TABLE)
                conn.execute(CREATE_CHAT_TURN_RECORDS_TABLE)
                conn.execute(CREATE_CHAT_TURN_SESSION_INDEX)
                conn.execute(CREATE_EMAIL_SEND_EVENTS_TABLE)
                conn.execute(CREATE_EMAIL_EVENT_TURN_INDEX)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM chat_turn_records").fetchone()
            result["status"] = "healthy"
            result["turns_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
