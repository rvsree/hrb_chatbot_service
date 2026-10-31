"""Phase 283 - a real accumulating history of FinOps cost/usage snapshots
(AWS Cost Explorer, LangSmith granular usage), not a cache - the admin
FinOps Monitoring tab's History grid needs rows to survive past any cache
TTL. Same psycopg + asyncio.to_thread() + psycopg.sql.Identifier pattern
as demo_visitor_store.py/live_query_store.py."""

import asyncio
import json

import psycopg
from psycopg import sql

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("finops_snapshot_store")

_SCHEMA = "hrb_finops"
_TABLE = sql.Identifier(_SCHEMA, "cost_snapshots")

CREATE_SCHEMA = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(_SCHEMA))

CREATE_COST_SNAPSHOTS_TABLE = sql.SQL(
    """
CREATE TABLE IF NOT EXISTS {table} (
    id SERIAL PRIMARY KEY,
    provider TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_cost DOUBLE PRECISION,
    cost_breakdown JSONB NOT NULL DEFAULT '{{}}',
    created_by TEXT
)
"""
).format(table=_TABLE)

CREATE_PROVIDER_INDEX = sql.SQL(
    "CREATE INDEX IF NOT EXISTS idx_cost_snapshots_provider ON {table}(provider, captured_at DESC)"
).format(table=_TABLE)


class FinopsSnapshotStore:
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
            conn.execute(CREATE_COST_SNAPSHOTS_TABLE)
            conn.execute(CREATE_PROVIDER_INDEX)
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

    def _insert_snapshot_sync(
        self, provider: str, period_start: str, period_end: str, total_cost: float | None,
        cost_breakdown: dict, created_by: str | None,
    ) -> dict:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {table}
                            (provider, period_start, period_end, total_cost, cost_breakdown, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """
                    ).format(table=_TABLE),
                    (provider, period_start, period_end, total_cost, json.dumps(cost_breakdown), created_by),
                )
                row = cur.fetchone()
                conn.commit()
        row["captured_at"] = row["captured_at"].isoformat()
        row["period_start"] = row["period_start"].isoformat()
        row["period_end"] = row["period_end"].isoformat()
        return row

    async def insert_snapshot(
        self, provider: str, period_start: str, period_end: str, total_cost: float | None,
        cost_breakdown: dict, created_by: str | None,
    ) -> dict:
        """Called on every force_refresh (or first-ever) fetch of a
        provider's cost/usage - a real accumulating row, never an upsert."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "cost_snapshots.insert", provider=provider):
            return await asyncio.to_thread(
                self._insert_snapshot_sync, provider, period_start, period_end, total_cost, cost_breakdown, created_by
            )

    def _get_latest_snapshot_sync(self, provider: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT * FROM {table} WHERE provider = %s ORDER BY captured_at DESC LIMIT 1"
                    ).format(table=_TABLE),
                    (provider,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        row["captured_at"] = row["captured_at"].isoformat()
        row["period_start"] = row["period_start"].isoformat()
        row["period_end"] = row["period_end"].isoformat()
        return row

    async def get_latest_snapshot(self, provider: str) -> dict | None:
        """The most recently captured snapshot for one provider, or None
        if this provider has never been fetched yet."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "cost_snapshots.get_latest", provider=provider):
            return await asyncio.to_thread(self._get_latest_snapshot_sync, provider)

    def _list_history_sync(self, provider: str, limit: int) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT * FROM {table} WHERE provider = %s ORDER BY captured_at DESC LIMIT %s"
                    ).format(table=_TABLE),
                    (provider, limit),
                )
                rows = cur.fetchall()
        for row in rows:
            row["captured_at"] = row["captured_at"].isoformat()
            row["period_start"] = row["period_start"].isoformat()
            row["period_end"] = row["period_end"].isoformat()
        return rows

    async def list_history(self, provider: str, limit: int = 30) -> list[dict]:
        """Newest first, capped at `limit` rows (default 30)."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "cost_snapshots.list_history", provider=provider):
            return await asyncio.to_thread(self._list_history_sync, provider, limit)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_SCHEMA)
                conn.execute(CREATE_COST_SNAPSHOTS_TABLE)
                conn.commit()
                row = conn.execute(sql.SQL("SELECT count(*) FROM {table}").format(table=_TABLE)).fetchone()
            result["status"] = "healthy"
            result["snapshots_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
