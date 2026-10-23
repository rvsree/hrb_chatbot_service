"""Phase 182 - persists scripts/run_release_gate.py's own per-run results
(Phase 80's eval gate) so the Deployment Dashboard can show history instead
of each run's output only ever living in CI stdout. Same psycopg +
asyncio.to_thread() pattern as doc_metadata_store.py/golden_dataset_store.py."""

import asyncio
import json

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("eval_run_store")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
_SCHEMA = "hrb_build_deployment"

CREATE_EVAL_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id SERIAL PRIMARY KEY,
    run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision TEXT NOT NULL,
    flags JSONB NOT NULL DEFAULT '[]',
    aggregated_scores JSONB NOT NULL DEFAULT '{}',
    total_cases INTEGER NOT NULL,
    scored_cases INTEGER NOT NULL,
    failed_case_ids JSONB NOT NULL DEFAULT '[]',
    retrieval_k INTEGER NOT NULL
)
"""

CREATE_EVAL_RUN_CASES_TABLE = """
CREATE TABLE IF NOT EXISTS eval_run_cases (
    id SERIAL PRIMARY KEY,
    eval_run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    category TEXT,
    scores JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL
)
"""

CREATE_EVAL_RUN_CASES_INDEX = "CREATE INDEX IF NOT EXISTS idx_eval_run_cases_eval_run_id ON eval_run_cases(eval_run_id)"


class EvalRunStore:
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
            conn.execute(CREATE_EVAL_RUNS_TABLE)
            conn.execute(CREATE_EVAL_RUN_CASES_TABLE)
            conn.execute(CREATE_EVAL_RUN_CASES_INDEX)
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

    def _record_run_sync(
        self,
        decision: str,
        flags: list[str],
        aggregated_scores: dict[str, float],
        total_cases: int,
        scored_cases: int,
        failed_case_ids: list[str],
        retrieval_k: int,
        case_results: list[dict],
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO eval_runs (decision, flags, aggregated_scores, total_cases, scored_cases, "
                "failed_case_ids, retrieval_k) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    decision,
                    json.dumps(flags),
                    json.dumps(aggregated_scores),
                    total_cases,
                    scored_cases,
                    json.dumps(failed_case_ids),
                    retrieval_k,
                ),
            )
            run_id = cur.fetchone()[0]
            for case_result in case_results:
                conn.execute(
                    "INSERT INTO eval_run_cases (eval_run_id, case_id, category, scores, status) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        run_id,
                        case_result["case_id"],
                        case_result.get("category"),
                        json.dumps(case_result.get("scores", {})),
                        case_result["status"],
                    ),
                )
            conn.commit()
            return run_id

    async def record_run(
        self,
        decision: str,
        flags: list[str],
        aggregated_scores: dict[str, float],
        total_cases: int,
        scored_cases: int,
        failed_case_ids: list[str],
        retrieval_k: int,
        case_results: list[dict],
    ) -> int:
        """Called once at the end of a real run_release_gate.py run. Never
        allowed to fail the gate itself - callers must catch and log, not
        propagate, per the gate's own "release-blocking behavior must
        never depend on persistence succeeding" rule."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "eval_runs.record", decision=decision):
            return await asyncio.to_thread(
                self._record_run_sync,
                decision,
                flags,
                aggregated_scores,
                total_cases,
                scored_cases,
                failed_case_ids,
                retrieval_k,
                case_results,
            )

    def _list_runs_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM eval_runs ORDER BY run_at DESC")
                rows = cur.fetchall()
        for row in rows:
            row["run_at"] = row["run_at"].isoformat()
        return rows

    async def list_runs(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "eval_runs.list"):
            return await asyncio.to_thread(self._list_runs_sync)

    def _get_run_sync(self, run_id: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM eval_runs WHERE id = %s", (run_id,))
                run = cur.fetchone()
                if run is None:
                    return None
                cur.execute("SELECT * FROM eval_run_cases WHERE eval_run_id = %s ORDER BY case_id", (run_id,))
                run["cases"] = cur.fetchall()
        run["run_at"] = run["run_at"].isoformat()
        return run

    async def get_run(self, run_id: int) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "eval_runs.get", run_id=run_id):
            return await asyncio.to_thread(self._get_run_sync, run_id)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_EVAL_RUNS_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM eval_runs").fetchone()
            result["status"] = "healthy"
            result["runs_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
