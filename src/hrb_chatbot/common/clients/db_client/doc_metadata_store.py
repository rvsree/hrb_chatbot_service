"""Phase 170 (round 1) - tracks which architecture/design docs are synced
to S3, for the admin-only in-app doc viewer. Same psycopg +
asyncio.to_thread() pattern as every other store here."""

import asyncio

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("doc_metadata_store")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
# admin_controls, not rag_ingestion - this table tracks admin-facing docs
# synced to S3 for the admin doc viewer, unrelated to RAG ingestion content
# despite the similar name (a real correction found during implementation).
_SCHEMA = "hrb_admin_controls"

CREATE_DOC_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS doc_metadata (
    id SERIAL PRIMARY KEY,
    feature_name TEXT NOT NULL,
    doc_title TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    doc_version INTEGER NOT NULL DEFAULT 1,
    s3_bucket TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    source_local_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

# Phase 179 - a feature can now have more than one doc (Spec/Architecture/
# Design/Decisions), so uniqueness moves from feature_name alone to the
# (feature_name, doc_type) pair. Idempotent, matching postgres_client.py's
# own ALTER TABLE ... IF NOT EXISTS / CREATE INDEX IF NOT EXISTS migration
# convention - DROP CONSTRAINT IF EXISTS targets the auto-generated name
# Postgres gave the original inline UNIQUE; a unique index (not a named
# constraint) replaces it since Postgres has no ADD CONSTRAINT IF NOT EXISTS.
DROP_OLD_FEATURE_NAME_UNIQUE = "ALTER TABLE doc_metadata DROP CONSTRAINT IF EXISTS doc_metadata_feature_name_key"
CREATE_FEATURE_DOC_TYPE_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_metadata_feature_doc_type ON doc_metadata(feature_name, doc_type)"
)


class DocMetadataStore:
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
            conn.execute(CREATE_DOC_METADATA_TABLE)
            conn.execute(DROP_OLD_FEATURE_NAME_UNIQUE)
            conn.execute(CREATE_FEATURE_DOC_TYPE_INDEX)
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

    def _list_docs_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM doc_metadata ORDER BY feature_name")
                rows = cur.fetchall()
        for row in rows:
            row["created_at"] = row["created_at"].isoformat()
            row["updated_at"] = row["updated_at"].isoformat()
            row["last_synced_at"] = row["last_synced_at"].isoformat()
        return rows

    async def list_docs(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "doc_metadata.list"):
            return await asyncio.to_thread(self._list_docs_sync)

    def _get_doc_sync(self, doc_id: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM doc_metadata WHERE id = %s", (doc_id,))
                row = cur.fetchone()
        if row is None:
            return None
        row["created_at"] = row["created_at"].isoformat()
        row["updated_at"] = row["updated_at"].isoformat()
        row["last_synced_at"] = row["last_synced_at"].isoformat()
        return row

    async def get_doc(self, doc_id: int) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "doc_metadata.get", doc_id=doc_id):
            return await asyncio.to_thread(self._get_doc_sync, doc_id)

    def _upsert_doc_sync(
        self,
        feature_name: str,
        doc_title: str,
        doc_type: str,
        s3_bucket: str,
        s3_key: str,
        source_local_path: str,
        content_hash: str,
    ) -> dict:
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, content_hash, doc_version FROM doc_metadata WHERE feature_name = %s AND doc_type = %s",
                (feature_name, doc_type),
            ).fetchone()

            if existing is None:
                cur = conn.execute(
                    "INSERT INTO doc_metadata (feature_name, doc_title, doc_type, doc_version, s3_bucket, "
                    "s3_key, source_local_path, content_hash) VALUES (%s, %s, %s, 1, %s, %s, %s, %s) RETURNING id",
                    (feature_name, doc_title, doc_type, s3_bucket, s3_key, source_local_path, content_hash),
                )
                doc_id = cur.fetchone()[0]
                conn.commit()
                return {"id": doc_id, "feature_name": feature_name, "doc_version": 1, "changed": True}

            doc_id, old_hash, old_version = existing
            if old_hash == content_hash:
                # Phase 179 - also refreshes s3_bucket/s3_key here, not just
                # last_synced_at: a sync script change to the S3 key naming
                # scheme (e.g. adding a doc_type suffix) must not leave an
                # unchanged-content doc's stored key silently pointing at a
                # stale/orphaned S3 object.
                conn.execute(
                    "UPDATE doc_metadata SET s3_bucket = %s, s3_key = %s, last_synced_at = now() WHERE id = %s",
                    (s3_bucket, s3_key, doc_id),
                )
                conn.commit()
                return {"id": doc_id, "feature_name": feature_name, "doc_version": old_version, "changed": False}

            new_version = old_version + 1
            conn.execute(
                "UPDATE doc_metadata SET doc_title = %s, doc_type = %s, doc_version = %s, s3_bucket = %s, "
                "s3_key = %s, source_local_path = %s, content_hash = %s, updated_at = now(), last_synced_at = now() "
                "WHERE id = %s",
                (doc_title, doc_type, new_version, s3_bucket, s3_key, source_local_path, content_hash, doc_id),
            )
            conn.commit()
            return {"id": doc_id, "feature_name": feature_name, "doc_version": new_version, "changed": True}

    async def upsert_doc(
        self,
        feature_name: str,
        doc_title: str,
        doc_type: str,
        s3_bucket: str,
        s3_key: str,
        source_local_path: str,
        content_hash: str,
    ) -> dict:
        """Idempotent by content_hash - a re-sync of an unchanged file only
        touches last_synced_at, not doc_version. Used by sync_admin_docs.py."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "doc_metadata.upsert", feature_name=feature_name):
            return await asyncio.to_thread(
                self._upsert_doc_sync, feature_name, doc_title, doc_type, s3_bucket, s3_key, source_local_path, content_hash
            )

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_DOC_METADATA_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM doc_metadata").fetchone()
            result["status"] = "healthy"
            result["docs_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
