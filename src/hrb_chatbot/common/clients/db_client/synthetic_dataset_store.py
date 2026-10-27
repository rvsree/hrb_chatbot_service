"""Phase 257 - synthetic (programmatically generated) test cases, same
shape as golden_dataset_store.py's own golden_dataset_cases table
deliberately, so any future tooling that reads golden-dataset-shaped rows
can read these too without a second code path. Distinct source though:
generated, not hand-curated - kept in its own table, not folded into
golden_dataset_cases, so the two categories never get mixed. Same
psycopg + asyncio.to_thread() pattern as every other store in this
module. Uses psycopg.sql.Identifier/SQL to compose the schema-qualified
table name (not an f-string) - the real, idiomatic-psycopg way to handle
a dynamic identifier, not just a bandit-appeasement workaround."""

import asyncio
import json

import psycopg
from psycopg import sql

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("synthetic_dataset_store")

_SCHEMA = "hrb_query_capture"
_TABLE = sql.Identifier(_SCHEMA, "synthetic_dataset_cases")

CREATE_SCHEMA = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(_SCHEMA))

CREATE_SYNTHETIC_DATASET_TABLE = sql.SQL(
    """
CREATE TABLE IF NOT EXISTS {table} (
    id SERIAL PRIMARY KEY,
    case_key TEXT NOT NULL,
    dataset TEXT NOT NULL,
    category TEXT,
    query TEXT,
    raw_case JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
).format(table=_TABLE)

CREATE_CASE_KEY_DATASET_INDEX = sql.SQL(
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_synthetic_dataset_case_key_dataset ON {table}(case_key, dataset)"
).format(table=_TABLE)


class SyntheticDatasetStore:
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
            conn.execute(CREATE_SYNTHETIC_DATASET_TABLE)
            conn.execute(CREATE_CASE_KEY_DATASET_INDEX)
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

    def _list_cases_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(sql.SQL("SELECT * FROM {table} ORDER BY dataset, case_key").format(table=_TABLE))
                rows = cur.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
            row["updated_at"] = row["updated_at"].isoformat()
        return rows

    async def list_cases(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "synthetic_dataset_cases.list"):
            return await asyncio.to_thread(self._list_cases_sync)

    def _upsert_case_sync(self, case_key: str, dataset: str, category: str | None, query: str | None, raw_case: dict) -> dict:
        raw_case_json = json.dumps(raw_case, sort_keys=True)
        with self._connect() as conn:
            existing = conn.execute(
                sql.SQL("SELECT id, raw_case FROM {table} WHERE case_key = %s AND dataset = %s").format(table=_TABLE),
                (case_key, dataset),
            ).fetchone()

            if existing is None:
                cur = conn.execute(
                    sql.SQL(
                        "INSERT INTO {table} (case_key, dataset, category, query, raw_case) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING id"
                    ).format(table=_TABLE),
                    (case_key, dataset, category, query, raw_case_json),
                )
                case_id = cur.fetchone()[0]
                conn.commit()
                return {"id": case_id, "case_key": case_key, "changed": True}

            case_id, old_raw_case = existing
            if json.dumps(old_raw_case, sort_keys=True) == raw_case_json:
                return {"id": case_id, "case_key": case_key, "changed": False}

            conn.execute(
                sql.SQL(
                    "UPDATE {table} SET category = %s, query = %s, raw_case = %s, updated_at = now() WHERE id = %s"
                ).format(table=_TABLE),
                (category, query, raw_case_json, case_id),
            )
            conn.commit()
            return {"id": case_id, "case_key": case_key, "changed": True}

    async def upsert_case(self, case_key: str, dataset: str, category: str | None, query: str | None, raw_case: dict) -> dict:
        """Idempotent by (case_key, dataset) - a re-sync of an unchanged case is a no-op."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "synthetic_dataset_cases.upsert", case_key=case_key, dataset=dataset):
            return await asyncio.to_thread(self._upsert_case_sync, case_key, dataset, category, query, raw_case)
