"""Phase 181 - mirrors resources/golden_dataset/*.json into Postgres for the
Deployment Dashboard's golden-dataset viewer. Same psycopg +
asyncio.to_thread() pattern as doc_metadata_store.py. The JSON files stay
the source of truth a developer edits - this table is a read mirror the UI
queries, kept in sync by scripts/sync_golden_dataset.py, never written to
directly by the API."""

import asyncio
import json

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("golden_dataset_store")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
_SCHEMA = "hrb_build_deployment"

CREATE_GOLDEN_DATASET_TABLE = """
CREATE TABLE IF NOT EXISTS golden_dataset_cases (
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

CREATE_CASE_KEY_DATASET_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_golden_dataset_case_key_dataset ON golden_dataset_cases(case_key, dataset)"
)


class GoldenDatasetStore:
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
            conn.execute(CREATE_GOLDEN_DATASET_TABLE)
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
                cur.execute("SELECT * FROM golden_dataset_cases ORDER BY dataset, case_key")
                rows = cur.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
            row["updated_at"] = row["updated_at"].isoformat()
        return rows

    async def list_cases(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "golden_dataset_cases.list"):
            return await asyncio.to_thread(self._list_cases_sync)

    def _upsert_case_sync(self, case_key: str, dataset: str, category: str | None, query: str | None, raw_case: dict) -> dict:
        raw_case_json = json.dumps(raw_case, sort_keys=True)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, raw_case FROM golden_dataset_cases WHERE case_key = %s AND dataset = %s",
                (case_key, dataset),
            ).fetchone()

            if existing is None:
                cur = conn.execute(
                    "INSERT INTO golden_dataset_cases (case_key, dataset, category, query, raw_case) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (case_key, dataset, category, query, raw_case_json),
                )
                case_id = cur.fetchone()[0]
                conn.commit()
                return {"id": case_id, "case_key": case_key, "changed": True}

            case_id, old_raw_case = existing
            # psycopg returns jsonb already parsed into a dict - compare the
            # same sort_keys-normalized form on both sides so key-order
            # alone never counts as a real change.
            if json.dumps(old_raw_case, sort_keys=True) == raw_case_json:
                return {"id": case_id, "case_key": case_key, "changed": False}

            conn.execute(
                "UPDATE golden_dataset_cases SET category = %s, query = %s, raw_case = %s, updated_at = now() "
                "WHERE id = %s",
                (category, query, raw_case_json, case_id),
            )
            conn.commit()
            return {"id": case_id, "case_key": case_key, "changed": True}

    async def upsert_case(self, case_key: str, dataset: str, category: str | None, query: str | None, raw_case: dict) -> dict:
        """Idempotent by (case_key, dataset) - a re-sync of an unchanged case
        is a no-op. Used by scripts/sync_golden_dataset.py."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "golden_dataset_cases.upsert", case_key=case_key, dataset=dataset):
            return await asyncio.to_thread(self._upsert_case_sync, case_key, dataset, category, query, raw_case)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_GOLDEN_DATASET_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM golden_dataset_cases").fetchone()
            result["status"] = "healthy"
            result["cases_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
