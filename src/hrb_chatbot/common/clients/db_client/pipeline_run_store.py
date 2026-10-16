"""Phase 189 - persists a snapshot of GET /v1/admin/ci-status/pipeline's
own response, upserted by head_sha, on every successful real fetch
(persist-on-read - no new GitHub Actions step, no new auth surface).
Never re-hosts log text - runs_json/eval_gate_json hold stage names,
status, and timing only, the same split this project's Decisions doc
already settled for Phase 188. Same psycopg + asyncio.to_thread()
pattern as eval_run_store.py."""

import asyncio
import json

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("pipeline_run_store")

CREATE_PIPELINE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id SERIAL PRIMARY KEY,
    head_sha TEXT NOT NULL UNIQUE,
    head_commit_message TEXT NOT NULL DEFAULT '',
    head_branch TEXT NOT NULL DEFAULT '',
    event TEXT NOT NULL DEFAULT '',
    actor_login TEXT NOT NULL DEFAULT '',
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    runs_json JSONB NOT NULL DEFAULT '[]',
    eval_gate_json JSONB
)
"""

# Phase 193 added head_branch/event/actor_login - ADD COLUMN IF NOT
# EXISTS, not just the CREATE TABLE above, since local dev already had
# this table from Phase 189's own testing before these columns existed.
ADD_PIPELINE_RUNS_COLUMNS = """
ALTER TABLE pipeline_runs
    ADD COLUMN IF NOT EXISTS head_branch TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS event TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS actor_login TEXT NOT NULL DEFAULT ''
"""


class PipelineRunStore:
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
            conn.execute(CREATE_PIPELINE_RUNS_TABLE)
            conn.execute(ADD_PIPELINE_RUNS_COLUMNS)
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

    def _upsert_snapshot_sync(
        self, head_sha: str, head_commit_message: str, head_branch: str, event: str, actor_login: str, runs: list[dict], eval_gate: dict | None
    ) -> dict:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "INSERT INTO pipeline_runs (head_sha, head_commit_message, head_branch, event, actor_login, runs_json, eval_gate_json) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (head_sha) DO UPDATE SET "
                    "head_commit_message = EXCLUDED.head_commit_message, head_branch = EXCLUDED.head_branch, "
                    "event = EXCLUDED.event, actor_login = EXCLUDED.actor_login, runs_json = EXCLUDED.runs_json, "
                    "eval_gate_json = EXCLUDED.eval_gate_json, captured_at = now() "
                    "RETURNING *",
                    (
                        head_sha,
                        head_commit_message,
                        head_branch,
                        event,
                        actor_login,
                        json.dumps(runs),
                        json.dumps(eval_gate) if eval_gate else None,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        row["captured_at"] = row["captured_at"].isoformat()
        return row

    async def upsert_snapshot(
        self, head_sha: str, head_commit_message: str, head_branch: str, event: str, actor_login: str, runs: list[dict], eval_gate: dict | None
    ) -> dict:
        """Called on every successful real fetch of the live pipeline
        route - never allowed to break that route if persistence fails,
        callers must catch and log, not propagate."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "pipeline_runs.upsert", head_sha=head_sha):
            return await asyncio.to_thread(
                self._upsert_snapshot_sync, head_sha, head_commit_message, head_branch, event, actor_login, runs, eval_gate
            )

    def _list_snapshots_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT id, head_sha, head_commit_message, captured_at FROM pipeline_runs ORDER BY captured_at DESC")
                rows = cur.fetchall()
        for row in rows:
            row["captured_at"] = row["captured_at"].isoformat()
        return rows

    async def list_snapshots(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "pipeline_runs.list"):
            return await asyncio.to_thread(self._list_snapshots_sync)

    def _get_snapshot_sync(self, snapshot_id: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM pipeline_runs WHERE id = %s", (snapshot_id,))
                row = cur.fetchone()
        if row is None:
            return None
        row["captured_at"] = row["captured_at"].isoformat()
        return row

    async def get_snapshot(self, snapshot_id: int) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "pipeline_runs.get", snapshot_id=snapshot_id):
            return await asyncio.to_thread(self._get_snapshot_sync, snapshot_id)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_PIPELINE_RUNS_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM pipeline_runs").fetchone()
            result["status"] = "healthy"
            result["snapshots_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
