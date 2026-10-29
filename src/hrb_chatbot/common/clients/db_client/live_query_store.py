"""Phase 257 - captures real production queries whose live groundedness
score crosses the configurable LTM threshold (app_settings key
ltm_score_threshold, default 0.6 - see app_settings_store.py). Distinct
from golden_dataset_store.py (hand-curated, human-verified) and
synthetic_dataset_store.py (generated) - this is the third, real-traffic
dataset category. Same psycopg + asyncio.to_thread() pattern as every
other store in this module. Uses psycopg.sql.Identifier/SQL to compose
the schema-qualified table name (not an f-string) - the real, idiomatic-
psycopg way to handle a dynamic identifier."""

import asyncio

import psycopg
from psycopg import sql

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("live_query_store")

_SCHEMA = "hrb_query_capture"
_TABLE = sql.Identifier(_SCHEMA, "live_queries")

CREATE_SCHEMA = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(_SCHEMA))

CREATE_LIVE_QUERIES_TABLE = sql.SQL(
    """
CREATE TABLE IF NOT EXISTS {table} (
    id SERIAL PRIMARY KEY,
    query_text TEXT NOT NULL,
    answer_text TEXT,
    pipeline TEXT,
    request_id TEXT,
    employee_id TEXT,
    eval_score DOUBLE PRECISION,
    is_ltm BOOLEAN NOT NULL DEFAULT false,
    category TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
).format(table=_TABLE)

CREATE_IS_LTM_INDEX = sql.SQL("CREATE INDEX IF NOT EXISTS idx_live_queries_is_ltm ON {table}(is_ltm)").format(table=_TABLE)


class LiveQueryStore:
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
            conn.execute(CREATE_SCHEMA)
            conn.execute(CREATE_LIVE_QUERIES_TABLE)
            conn.execute(CREATE_IS_LTM_INDEX)
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

    def _capture_sync(
        self, query_text: str, answer_text: str | None, pipeline: str | None, request_id: str | None,
        employee_id: str | None, eval_score: float | None, is_ltm: bool,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                sql.SQL(
                    "INSERT INTO {table} (query_text, answer_text, pipeline, request_id, employee_id, eval_score, is_ltm) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
                ).format(table=_TABLE),
                (query_text, answer_text, pipeline, request_id, employee_id, eval_score, is_ltm),
            )
            row_id = cur.fetchone()[0]
            conn.commit()
            return row_id

    async def capture(
        self, query_text: str, answer_text: str | None, pipeline: str | None, request_id: str | None,
        employee_id: str | None, eval_score: float | None, is_ltm: bool,
    ) -> None:
        """Fire-and-forget by design - callers must wrap this in try/except
        and never let a capture failure affect the real response. Mirrors
        response_metrics.py's own established convention for exactly this
        kind of best-effort side-channel logging."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "live_queries.capture", pipeline=pipeline, request_id=request_id):
            await asyncio.to_thread(
                self._capture_sync, query_text, answer_text, pipeline, request_id, employee_id, eval_score, is_ltm
            )

    def _list_sync(self, is_ltm: bool | None) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                if is_ltm is None:
                    cur.execute(sql.SQL("SELECT * FROM {table} ORDER BY created_at DESC").format(table=_TABLE))
                else:
                    cur.execute(
                        sql.SQL("SELECT * FROM {table} WHERE is_ltm = %s ORDER BY created_at DESC").format(table=_TABLE),
                        (is_ltm,),
                    )
                rows = cur.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
        return rows

    async def list_queries(self, is_ltm: bool | None = None) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "live_queries.list"):
            return await asyncio.to_thread(self._list_sync, is_ltm)

    def _delete_live_query_sync(self, live_query_id: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(sql.SQL("DELETE FROM {table} WHERE id = %s").format(table=_TABLE), (live_query_id,))
            conn.commit()
            return cur.rowcount

    async def delete_live_query(self, live_query_id: int) -> int:
        """Phase 267 - admin-only hard delete. Nothing in this store could
        delete anything before this - list_queries()/capture() were the
        only 2 operations that existed."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "live_queries.delete", live_query_id=live_query_id):
            return await asyncio.to_thread(self._delete_live_query_sync, live_query_id)
