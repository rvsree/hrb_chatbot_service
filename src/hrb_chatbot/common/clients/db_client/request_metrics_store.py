"""Phase 184 - persists one row per real query response (token count,
latency, status) so the Deployment Dashboard's Live Metrics tab has
something to aggregate. cost_usd exists as a column for later - no
verified, maintained per-model price table exists in this project yet, so
it's always logged as NULL this phase rather than a guessed number.
Same psycopg + asyncio.to_thread() pattern as every other store here."""

import asyncio

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("request_metrics_store")

CREATE_REQUEST_METRICS_TABLE = """
CREATE TABLE IF NOT EXISTS request_metrics (
    id SERIAL PRIMARY KEY,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    endpoint TEXT NOT NULL,
    pipeline TEXT NOT NULL,
    token_count INTEGER,
    cost_usd NUMERIC,
    latency_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT
)
"""

# Phase 201 - request_id didn't exist when this table was first created
# (Phase 184), so existing rows get NULL, same migration pattern
# pipeline_runs already used for its own later columns.
ADD_REQUEST_METRICS_REQUEST_ID_COLUMN = "ALTER TABLE request_metrics ADD COLUMN IF NOT EXISTS request_id TEXT"

CREATE_REQUEST_METRICS_LOGGED_AT_INDEX = "CREATE INDEX IF NOT EXISTS idx_request_metrics_logged_at ON request_metrics(logged_at)"


class RequestMetricsStore:
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
            host=self.host, port=self.port, dbname=self.db_name, user=self.user, password=self.password
        )

    def _ensure_table_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_REQUEST_METRICS_TABLE)
            conn.execute(ADD_REQUEST_METRICS_REQUEST_ID_COLUMN)
            conn.execute(CREATE_REQUEST_METRICS_LOGGED_AT_INDEX)
            conn.commit()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        await asyncio.to_thread(self._ensure_table_sync)
        self._table_ready = True

    def _log_request_sync(
        self,
        endpoint: str,
        pipeline: str,
        token_count: int | None,
        latency_ms: int,
        status: str,
        error_code: str | None,
        request_id: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO request_metrics (endpoint, pipeline, token_count, latency_ms, status, error_code, request_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (endpoint, pipeline, token_count, latency_ms, status, error_code, request_id),
            )
            conn.commit()

    async def log_request(
        self,
        endpoint: str,
        pipeline: str,
        token_count: int | None,
        latency_ms: int,
        status: str,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Fire-and-forget by design - callers wrap this in try/except and
        never let a logging failure affect the real response being logged."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "request_metrics.log", endpoint=endpoint, pipeline=pipeline, request_id=request_id):
            await asyncio.to_thread(
                self._log_request_sync, endpoint, pipeline, token_count, latency_ms, status, error_code, request_id
            )

    @staticmethod
    def _dict_row_factory(cursor):
        columns = [desc.name for desc in cursor.description]
        return lambda values: dict(zip(columns, values, strict=True))

    def _aggregate_sync(self, window_hours: int) -> dict:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT pipeline, status, count(*) AS request_count, "
                    "avg(latency_ms) AS avg_latency_ms, "
                    "percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_latency_ms, "
                    "percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms, "
                    "sum(token_count) AS total_tokens "
                    "FROM request_metrics "
                    "WHERE logged_at > now() - (%s || ' hours')::interval "
                    "GROUP BY pipeline, status "
                    "ORDER BY pipeline",
                    (window_hours,),
                )
                rows = cur.fetchall()
        return {"window_hours": window_hours, "rows": rows}

    async def aggregate(self, window_hours: int) -> dict:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "request_metrics.aggregate", window_hours=window_hours):
            return await asyncio.to_thread(self._aggregate_sync, window_hours)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_REQUEST_METRICS_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM request_metrics").fetchone()
            result["status"] = "healthy"
            result["rows_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
