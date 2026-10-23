"""Phase 186 - employee-submitted questions that get a real-time LLM
first-pass answer, then a human/Claude review pass before publishing.
Same psycopg + asyncio.to_thread() pattern as every other store here."""

import asyncio

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("faq_submission_store")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
_SCHEMA = "hrb_admin_controls"

CREATE_FAQ_SUBMISSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS faq_submissions (
    id SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL,
    query TEXT NOT NULL,
    external_llm_answer TEXT,
    internal_review_status TEXT NOT NULL DEFAULT 'pending',
    answer_restructuring_status TEXT NOT NULL DEFAULT 'not_started',
    final_answer TEXT,
    published BOOLEAN NOT NULL DEFAULT false,
    reviewed_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class FaqSubmissionStore:
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
            options=f"-c search_path={_SCHEMA},public",
        )

    def _ensure_table_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_FAQ_SUBMISSIONS_TABLE)
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

    def _create_submission_sync(self, employee_id: str, query: str, external_llm_answer: str | None) -> dict:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "INSERT INTO faq_submissions (employee_id, query, external_llm_answer) "
                    "VALUES (%s, %s, %s) RETURNING *",
                    (employee_id, query, external_llm_answer),
                )
                row = cur.fetchone()
            conn.commit()
        row["created_at"] = row["created_at"].isoformat()
        row["updated_at"] = row["updated_at"].isoformat()
        return row

    async def create_submission(self, employee_id: str, query: str, external_llm_answer: str | None) -> dict:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "faq_submissions.create", employee_id=employee_id):
            return await asyncio.to_thread(self._create_submission_sync, employee_id, query, external_llm_answer)

    def _list_submissions_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM faq_submissions ORDER BY created_at DESC")
                rows = cur.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
            row["updated_at"] = row["updated_at"].isoformat()
        return rows

    async def list_submissions(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "faq_submissions.list"):
            return await asyncio.to_thread(self._list_submissions_sync)

    def _list_published_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT id, query, final_answer FROM faq_submissions WHERE published = true ORDER BY created_at DESC"
                )
                return cur.fetchall()

    async def list_published(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "faq_submissions.list_published"):
            return await asyncio.to_thread(self._list_published_sync)

    def _get_submission_sync(self, submission_id: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM faq_submissions WHERE id = %s", (submission_id,))
                row = cur.fetchone()
        if row is None:
            return None
        row["created_at"] = row["created_at"].isoformat()
        row["updated_at"] = row["updated_at"].isoformat()
        return row

    async def get_submission(self, submission_id: int) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "faq_submissions.get", submission_id=submission_id):
            return await asyncio.to_thread(self._get_submission_sync, submission_id)

    def _update_restructured_answer_sync(self, submission_id: int, final_answer: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "UPDATE faq_submissions SET final_answer = %s, answer_restructuring_status = 'claude_restructured', "
                    "updated_at = now() WHERE id = %s RETURNING *",
                    (final_answer, submission_id),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            return None
        row["created_at"] = row["created_at"].isoformat()
        row["updated_at"] = row["updated_at"].isoformat()
        return row

    async def update_restructured_answer(self, submission_id: int, final_answer: str) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "faq_submissions.restructure", submission_id=submission_id):
            return await asyncio.to_thread(self._update_restructured_answer_sync, submission_id, final_answer)

    def _review_submission_sync(
        self,
        submission_id: int,
        internal_review_status: str,
        final_answer: str | None,
        published: bool,
        reviewed_by: str,
        restructuring_status: str,
    ) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "UPDATE faq_submissions SET internal_review_status = %s, final_answer = %s, published = %s, "
                    "reviewed_by = %s, answer_restructuring_status = %s, updated_at = now() WHERE id = %s RETURNING *",
                    (internal_review_status, final_answer, published, reviewed_by, restructuring_status, submission_id),
                )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            return None
        row["created_at"] = row["created_at"].isoformat()
        row["updated_at"] = row["updated_at"].isoformat()
        return row

    async def review_submission(
        self,
        submission_id: int,
        internal_review_status: str,
        final_answer: str | None,
        published: bool,
        reviewed_by: str,
        restructuring_status: str,
    ) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "faq_submissions.review", submission_id=submission_id):
            return await asyncio.to_thread(
                self._review_submission_sync,
                submission_id,
                internal_review_status,
                final_answer,
                published,
                reviewed_by,
                restructuring_status,
            )

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_FAQ_SUBMISSIONS_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM faq_submissions").fetchone()
            result["status"] = "healthy"
            result["submissions_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
