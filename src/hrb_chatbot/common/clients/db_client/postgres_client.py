"""Postgres client - an alternative document-metadata store, same BaseMetadataClient contract as sqlite_client.py."""

import asyncio
import json

import psycopg

from src.hrb_chatbot.common.clients.db_client.base_metadata_client import BaseMetadataClient
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("postgres_client")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
_SCHEMA = "hrb_rag_ingestion"

CREATE_DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
)
"""

# Columns added after the table already existed - Postgres's IF NOT EXISTS means no try/except needed.
ADD_COLUMNS = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_ids TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_version INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_model TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS vector_db TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_size INTEGER",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunk_overlap INTEGER",
    # Phase 114: see sqlite_client.py's own identical column for why.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS chunking_strategy TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS last_indexed_at TIMESTAMPTZ",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_current BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS supersedes TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS superseded_by TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS department TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_category TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS purpose TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_description TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS effective_date TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS audience TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS confidentiality_level TEXT",
    # Phase 231 - Document ACL; a JSON-encoded list, same convention chunk_ids already uses.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS restricted_roles TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS uploaded_by TEXT",
    # Provenance/citation fields, not filter dimensions like doc_category/department/doc_description.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS author TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_date TEXT",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_version TEXT",
    # Phase 89: the presigned-upload route's chunk_info/document_metadata
    # overrides, as one JSON blob, until the Lambda reads and clears it.
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS pending_overrides TEXT",
]

# Rename rather than add-new/leave-old, so stored values survive - checked against information_schema first.
RENAME_COLUMNS = [("doc_type", "doc_category"), ("doc_classification", "doc_description")]

# Speeds up find_by_content_hash() - one lookup per upload, worth an index.
CREATE_CONTENT_HASH_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents(content_hash)"
)

# Normalized chunk tracking - see sqlite_client.py's identical table for why.
CREATE_CHUNKS_TABLE = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT true
)
"""
CREATE_CHUNKS_DOCUMENT_ID_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id)"
)


class PostgresClient(BaseMetadataClient):
    """Stores document metadata in Postgres."""

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

    def get_configuration(self) -> dict:
        """Return the settings this client is using - no password in it."""
        return {"host": self.host, "port": self.port, "db_name": self.db_name}

    def _connect(self) -> psycopg.Connection:
        """Synchronous connect - always run this through asyncio.to_thread()."""
        return psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=self.db_name,
            user=self.user,
            password=self.password,
            options=f"-c search_path={_SCHEMA},public",
        )

    def _ensure_table_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_DOCUMENTS_TABLE)

            existing_columns = {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'documents'"
                ).fetchall()
            }
            for old_name, new_name in RENAME_COLUMNS:
                if old_name in existing_columns and new_name not in existing_columns:
                    conn.execute(f"ALTER TABLE documents RENAME COLUMN {old_name} TO {new_name}")

            for add_column in ADD_COLUMNS:
                conn.execute(add_column)
            conn.execute(CREATE_CONTENT_HASH_INDEX)
            conn.execute(CREATE_CHUNKS_TABLE)
            conn.execute(CREATE_CHUNKS_DOCUMENT_ID_INDEX)
            conn.commit()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return

        await asyncio.to_thread(self._ensure_table_sync)
        self._table_ready = True

    def _create_document_sync(
        self,
        document_id: str,
        filename: str,
        file_path: str,
        file_size_bytes: int,
        content_hash: str,
        supersedes: str | None,
        uploaded_by: str | None,
    ) -> None:
        # document_version starts at 0 ("no successfully indexed version yet") - the first real index lands on 1.
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO documents (id, filename, file_path, status, error_message, "
                "created_at, updated_at, document_version, file_size_bytes, content_hash, "
                "is_current, supersedes, uploaded_by) "
                "VALUES (%s, %s, %s, 'uploaded', NULL, now(), now(), 0, %s, %s, true, %s, %s)",
                (document_id, filename, file_path, file_size_bytes, content_hash, supersedes, uploaded_by),
            )
            conn.commit()

    async def find_by_content_hash(self, content_hash: str) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "metadata.find_by_content_hash"):
            return await asyncio.to_thread(self._find_by_content_hash_sync, content_hash)

    def _find_by_content_hash_sync(self, content_hash: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT * FROM documents WHERE content_hash = %s ORDER BY created_at DESC LIMIT 1",
                    (content_hash,),
                )
                return cur.fetchone()

    async def create_document(
        self,
        document_id: str,
        filename: str,
        file_path: str,
        file_size_bytes: int,
        content_hash: str,
        supersedes: str | None = None,
        uploaded_by: str | None = None,
    ) -> None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "metadata.create_document", document_id=document_id):
            await asyncio.to_thread(
                self._create_document_sync,
                document_id,
                filename,
                file_path,
                file_size_bytes,
                content_hash,
                supersedes,
                uploaded_by,
            )

    def _update_status_sync(self, document_id: str, status: str, error_message: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE documents SET status = %s, error_message = %s, updated_at = now() "
                "WHERE id = %s",
                (status, error_message, document_id),
            )
            conn.commit()

    async def update_status(
        self, document_id: str, status: str, error_message: str | None = None
    ) -> None:
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "metadata.update_status", document_id=document_id, status=status
        ):
            await asyncio.to_thread(self._update_status_sync, document_id, status, error_message)

    def _set_pending_overrides_sync(self, document_id: str, overrides_json: str | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE documents SET pending_overrides = %s WHERE id = %s",
                (overrides_json, document_id),
            )
            conn.commit()

    async def set_pending_overrides(self, document_id: str, overrides_json: str | None) -> None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "metadata.set_pending_overrides", document_id=document_id):
            await asyncio.to_thread(self._set_pending_overrides_sync, document_id, overrides_json)

    def _set_chunk_ids_sync(self, document_id: str, chunk_ids: list[str]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE documents SET chunk_ids = %s, updated_at = now() WHERE id = %s",
                (json.dumps(chunk_ids), document_id),
            )
            conn.commit()

    async def set_chunk_ids(self, document_id: str, chunk_ids: list[str]) -> None:
        await self._ensure_table()
        with log_backend_call(
            logger,
            "postgres",
            "metadata.set_chunk_ids",
            document_id=document_id,
            chunk_count=len(chunk_ids),
        ):
            await asyncio.to_thread(self._set_chunk_ids_sync, document_id, chunk_ids)

    def _record_successful_index_sync(
        self,
        document_id: str,
        chunk_ids: list[str],
        embedding_model: str,
        embedding_dimension: int,
        vector_db: str,
        chunking_strategy: str | None,
        chunk_size: int,
        chunk_overlap: int,
    ) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE documents SET chunk_ids = %s, chunk_count = %s, embedding_model = %s, "
                "embedding_dimension = %s, vector_db = %s, chunking_strategy = %s, chunk_size = %s, chunk_overlap = %s, "
                "status = 'indexed', error_message = NULL, last_indexed_at = now(), updated_at = now(), "
                "document_version = document_version + 1 WHERE id = %s RETURNING document_version",
                (
                    json.dumps(chunk_ids),
                    len(chunk_ids),
                    embedding_model,
                    embedding_dimension,
                    vector_db,
                    chunking_strategy,
                    chunk_size,
                    chunk_overlap,
                    document_id,
                ),
            ).fetchone()

            # Replace this document's rows in `chunks` - same delete-then-insert shape as sqlite_client.py.
            conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            if chunk_ids:
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO chunks (chunk_id, document_id, chunk_index, created_at, is_current) "
                        "VALUES (%s, %s, %s, now(), true)",
                        [(chunk_id, document_id, index) for index, chunk_id in enumerate(chunk_ids)],
                    )
            conn.commit()
        return row[0]

    def _mark_superseded_sync(self, document_id: str, superseded_by: str) -> list[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chunk_ids FROM documents WHERE id = %s", (document_id,)
            ).fetchone()

            conn.execute(
                "UPDATE documents SET is_current = false, superseded_by = %s, updated_at = now() "
                "WHERE id = %s",
                (superseded_by, document_id),
            )
            conn.execute("UPDATE chunks SET is_current = false WHERE document_id = %s", (document_id,))
            conn.commit()

        if row is None or row[0] is None:
            return []
        return json.loads(row[0])

    async def mark_superseded(self, document_id: str, superseded_by: str) -> list[str]:
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "metadata.mark_superseded", document_id=document_id, superseded_by=superseded_by
        ):
            return await asyncio.to_thread(self._mark_superseded_sync, document_id, superseded_by)

    def _update_document_content_sync(
        self, document_id: str, filename: str, file_path: str, file_size_bytes: int, content_hash: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE documents SET filename = %s, file_path = %s, file_size_bytes = %s, content_hash = %s, "
                "updated_at = now() WHERE id = %s",
                (filename, file_path, file_size_bytes, content_hash, document_id),
            )
            conn.commit()

    async def update_document_content(
        self, document_id: str, filename: str, file_path: str, file_size_bytes: int, content_hash: str
    ) -> None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "metadata.update_document_content", document_id=document_id):
            await asyncio.to_thread(
                self._update_document_content_sync, document_id, filename, file_path, file_size_bytes, content_hash
            )

    def _record_document_metadata_sync(
        self,
        document_id: str,
        owner: str | None,
        department: str | None,
        doc_category: str | None,
        purpose: str | None,
        doc_description: str | None,
        restricted_roles: list[str] | None,
        effective_date: str | None,
        audience: str | None,
        confidentiality_level: str | None,
        author: str | None,
        doc_date: str | None,
        doc_version: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE documents SET owner = %s, department = %s, doc_category = %s, purpose = %s, "
                "doc_description = %s, restricted_roles = %s, effective_date = %s, audience = %s, "
                "confidentiality_level = %s, author = %s, doc_date = %s, doc_version = %s, "
                "updated_at = now() WHERE id = %s",
                (
                    owner,
                    department,
                    doc_category,
                    purpose,
                    doc_description,
                    json.dumps(restricted_roles) if restricted_roles else None,
                    effective_date,
                    audience,
                    confidentiality_level,
                    author,
                    doc_date,
                    doc_version,
                    document_id,
                ),
            )
            conn.commit()

    async def record_document_metadata(
        self,
        document_id: str,
        owner: str | None,
        department: str | None,
        doc_category: str | None,
        purpose: str | None,
        doc_description: str | None,
        restricted_roles: list[str] | None = None,
        effective_date: str | None = None,
        audience: str | None = None,
        confidentiality_level: str | None = None,
        author: str | None = None,
        doc_date: str | None = None,
        doc_version: str | None = None,
    ) -> None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "metadata.record_document_metadata", document_id=document_id):
            await asyncio.to_thread(
                self._record_document_metadata_sync,
                document_id,
                owner,
                department,
                doc_category,
                purpose,
                doc_description,
                restricted_roles,
                effective_date,
                audience,
                confidentiality_level,
                author,
                doc_date,
                doc_version,
            )

    async def record_successful_index(
        self,
        document_id: str,
        chunk_ids: list[str],
        embedding_model: str,
        embedding_dimension: int,
        vector_db: str,
        chunking_strategy: str | None,
        chunk_size: int,
        chunk_overlap: int,
    ) -> int:
        await self._ensure_table()
        with log_backend_call(
            logger, "postgres", "metadata.record_successful_index", document_id=document_id
        ):
            return await asyncio.to_thread(
                self._record_successful_index_sync,
                document_id,
                chunk_ids,
                embedding_model,
                embedding_dimension,
                vector_db,
                chunking_strategy,
                chunk_size,
                chunk_overlap,
            )

    def _get_document_sync(self, document_id: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM documents WHERE id = %s", (document_id,))
                return cur.fetchone()

    async def get_document(self, document_id: str) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "metadata.get_document", document_id=document_id):
            return await asyncio.to_thread(self._get_document_sync, document_id)

    def _list_documents_sync(self) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM documents ORDER BY created_at DESC")
                return cur.fetchall()

    async def list_documents(self) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "metadata.list_documents"):
            return await asyncio.to_thread(self._list_documents_sync)

    def _delete_document_sync(self, document_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM documents WHERE id = %s", (document_id,))
            conn.commit()

    async def delete_document(self, document_id: str) -> None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "metadata.delete_document", document_id=document_id):
            await asyncio.to_thread(self._delete_document_sync, document_id)

    @staticmethod
    def _dict_row_factory(cursor):
        """Turn each result row into a dict keyed by column name, matching sqlite_client.py's row shape."""
        columns = [desc.name for desc in cursor.description]

        def make_row(values):
            row = dict(zip(columns, values, strict=True))
            # last_indexed_at was missed here originally, leaking a raw datetime instead of a string.
            for key in ("created_at", "updated_at", "last_indexed_at"):
                if row.get(key) is not None:
                    row[key] = row[key].isoformat()
            return row

        return make_row

    def health_check(self) -> dict:
        """Report whether this client is usable - connects, creates the table if missing, counts rows."""
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not configured"
            return result

        try:
            connection = psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.db_name,
                user=self.user,
                password=self.password,
                connect_timeout=5,
            )
            try:
                connection.execute(CREATE_DOCUMENTS_TABLE)
                for add_column in ADD_COLUMNS:
                    connection.execute(add_column)
                connection.commit()
                document_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            finally:
                connection.close()

            result["status"] = "healthy"
            result["documents_stored"] = document_count
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
