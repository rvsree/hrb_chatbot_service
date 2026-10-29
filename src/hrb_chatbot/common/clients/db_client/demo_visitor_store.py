"""Phase 265 - tracks one row per live-demo conversation: who (self-
asserted identity + IP + browser timezone), how many queries they've made,
and any admin-granted waiver on top of the configured limit. Deliberately
NOT an extension of live_query_store.py's live_queries table - that
capture is fire-and-forget and gated on groundedness eval having actually
run (confirmed by reading maybe_capture_live_query() directly), the wrong
reliability tradeoff for a hard limit that must count every attempt.
Same psycopg + asyncio.to_thread() + psycopg.sql.Identifier pattern as
every other store in this module."""

import asyncio

import psycopg
from psycopg import sql

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("demo_visitor_store")

_SCHEMA = "hrb_query_capture"
_TABLE = sql.Identifier(_SCHEMA, "demo_visitors")

CREATE_SCHEMA = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(_SCHEMA))

CREATE_DEMO_VISITORS_TABLE = sql.SQL(
    """
CREATE TABLE IF NOT EXISTS {table} (
    conversation_id TEXT PRIMARY KEY,
    employee_id TEXT,
    full_name TEXT,
    role TEXT,
    ip_address TEXT,
    timezone TEXT,
    query_count INTEGER NOT NULL DEFAULT 0,
    waiver_count INTEGER NOT NULL DEFAULT 0,
    last_query_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
).format(table=_TABLE)


class DemoVisitorStore:
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
            conn.execute(CREATE_DEMO_VISITORS_TABLE)
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

    def _record_query_sync(
        self, conversation_id: str, employee_id: str | None, full_name: str | None, role: str | None,
        ip_address: str | None, timezone: str | None,
    ) -> dict:
        # Single atomic upsert - never read-then-write, so two
        # near-simultaneous requests for the same conversation_id can't
        # both slip through right at the limit boundary.
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {table}
                            (conversation_id, employee_id, full_name, role, ip_address, timezone, query_count, last_query_at)
                        VALUES (%s, %s, %s, %s, %s, %s, 1, now())
                        ON CONFLICT (conversation_id) DO UPDATE SET
                            employee_id = EXCLUDED.employee_id,
                            full_name = EXCLUDED.full_name,
                            role = EXCLUDED.role,
                            ip_address = EXCLUDED.ip_address,
                            timezone = EXCLUDED.timezone,
                            query_count = {table}.query_count + 1,
                            last_query_at = now(),
                            updated_at = now()
                        RETURNING query_count, waiver_count
                        """
                    ).format(table=_TABLE),
                    (conversation_id, employee_id, full_name, role, ip_address, timezone),
                )
                row = cur.fetchone()
                conn.commit()
                return row

    async def record_query(
        self, conversation_id: str, employee_id: str | None, full_name: str | None, role: str | None,
        ip_address: str | None, timezone: str | None,
    ) -> dict:
        """Returns {"query_count": int, "waiver_count": int} - the counts
        AFTER this query was counted."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "demo_visitors.record_query", conversation_id=conversation_id):
            return await asyncio.to_thread(
                self._record_query_sync, conversation_id, employee_id, full_name, role, ip_address, timezone
            )

    def _grant_waiver_sync(self, conversation_id: str, increment: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    sql.SQL(
                        """
                        INSERT INTO {table} (conversation_id, query_count, waiver_count)
                        VALUES (%s, 0, %s)
                        ON CONFLICT (conversation_id) DO UPDATE SET
                            waiver_count = {table}.waiver_count + %s,
                            updated_at = now()
                        RETURNING conversation_id, query_count, waiver_count
                        """
                    ).format(table=_TABLE),
                    (conversation_id, increment, increment),
                )
                row = cur.fetchone()
                conn.commit()
                return row

    async def grant_waiver(self, conversation_id: str, increment: int = 15) -> dict:
        """Admin-only action (enforced at the route layer) - adds `increment`
        extra queries to this conversation's effective limit. Repeatable -
        each call adds on top of any prior waiver, never resets it."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "demo_visitors.grant_waiver", conversation_id=conversation_id):
            return await asyncio.to_thread(self._grant_waiver_sync, conversation_id, increment)

    def _list_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(sql.SQL("SELECT * FROM {table} ORDER BY last_query_at DESC NULLS LAST").format(table=_TABLE))
                rows = cur.fetchall()
        for row in rows:
            if row["last_query_at"] is not None:
                row["last_query_at"] = row["last_query_at"].isoformat()
            row["created_at"] = row["created_at"].isoformat()
            row["updated_at"] = row["updated_at"].isoformat()
        return rows

    async def list_visitors(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "demo_visitors.list"):
            return await asyncio.to_thread(self._list_sync)

    def _delete_visitor_sync(self, conversation_id: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                sql.SQL("DELETE FROM {table} WHERE conversation_id = %s").format(table=_TABLE), (conversation_id,)
            )
            conn.commit()
            return cur.rowcount

    async def delete_visitor(self, conversation_id: str) -> int:
        """Phase 268 - admin-only hard delete. Nothing in this store could
        delete anything before this - record_query()/grant_waiver()/
        list_visitors() were the only 3 operations that existed."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "demo_visitors.delete", conversation_id=conversation_id):
            return await asyncio.to_thread(self._delete_visitor_sync, conversation_id)
