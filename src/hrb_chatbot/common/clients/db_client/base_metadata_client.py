"""Shared interface every document-metadata store implements - one row per document."""

from abc import ABC, abstractmethod


class BaseMetadataClient(ABC):
    """Every document-metadata store (SQLite, Postgres, ...) inherits from this."""

    PROVIDER_NAME = "base"
    ENV_KEY = ""

    @abstractmethod
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
        """Insert one row for a newly-uploaded document; `supersedes` only records intent, not the flip."""
        raise NotImplementedError

    @abstractmethod
    async def find_by_content_hash(self, content_hash: str) -> dict | None:
        """Return the most recent document with this exact content hash, or None."""
        raise NotImplementedError

    @abstractmethod
    async def update_status(
        self, document_id: str, status: str, error_message: str | None = None
    ) -> None:
        """Move a document to 'indexed' or 'failed', recording why if it failed."""
        raise NotImplementedError

    @abstractmethod
    async def set_pending_overrides(self, document_id: str, overrides_json: str | None) -> None:
        """Phase 89: stash the presigned-upload caller's chunk_info/document_metadata
        overrides (as one JSON blob) until the Lambda picks them up - None clears it
        after a successful index, same as any other document column."""
        raise NotImplementedError

    @abstractmethod
    async def set_chunk_ids(self, document_id: str, chunk_ids: list[str]) -> None:
        """Record which vector-store ids this document's chunks were written under."""
        raise NotImplementedError

    @abstractmethod
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
        """One update for everything a successful index changes; returns the new version."""
        raise NotImplementedError

    @abstractmethod
    async def mark_superseded(self, document_id: str, superseded_by: str) -> list[str]:
        """Flip an existing document to is_current=false; returns chunk_ids so the caller can flip the vector store too."""
        raise NotImplementedError

    @abstractmethod
    async def update_document_content(
        self, document_id: str, filename: str, file_path: str, file_size_bytes: int, content_hash: str
    ) -> None:
        """Phase 125: record a new filename/size/hash after an in-place reindex - a
        separate write from record_successful_index() (file-identity vs. indexing facts)."""
        raise NotImplementedError

    @abstractmethod
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
        """Record LLM-extracted document metadata (best-effort) - never raises."""
        raise NotImplementedError

    @abstractmethod
    async def get_document(self, document_id: str) -> dict | None:
        """Return one document's row, or None if the id doesn't exist."""
        raise NotImplementedError

    @abstractmethod
    async def delete_document(self, document_id: str) -> None:
        """Remove one document's row - a no-op if the id doesn't exist."""
        raise NotImplementedError

    @abstractmethod
    async def list_documents(self) -> list[dict]:
        """Return every document row, newest first."""
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> dict:
        """Report whether this store is usable - never raises."""
        raise NotImplementedError
