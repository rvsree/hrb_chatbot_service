"""Request/response contracts for the document upload API - see docs/agent-reference/endpoint-request-response-contracts.md."""

import json

from pydantic import BaseModel, Field, model_validator

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.enums import ChunkingStrategy
from src.hrb_chatbot.models.common import UserProfile

# A benefits PDF is a handful of pages - 20MB is generous headroom, not arbitrary. Server-side, not payload-overridable.
MAX_FILE_SIZE_BYTES = int(read_setting(None, "MAX_UPLOAD_FILE_SIZE_BYTES", 20 * 1024 * 1024))
ALLOWED_CONTENT_TYPE = "application/pdf"

# The raw `payload` form field's own length bound - see the contracts doc.
PAYLOAD_MAX_LENGTH = 20000

# A structural test-noise signal - real documents are far larger, test-generated files are short fake strings.
TEST_NOISE_MAX_FILE_SIZE_BYTES = int(read_setting(None, "TEST_NOISE_MAX_FILE_SIZE_BYTES", 1024))

# Phase 156 - user-agreed bounds for the now-editable chunk_size/chunk_overlap
# (Indexed Documents page): below 200 chars a chunk is too fragmented to
# carry real context; above 4000 risks the same diluted-embedding problem
# Phase 149 found at 15,000+ chars for "semantic" (same mechanism, just a
# much lower ceiling here since nothing legitimate needs to go that high).
MIN_CHUNK_SIZE = 200
MAX_CHUNK_SIZE = 4000


class ChunkInfoInput(BaseModel):
    chunking_strategy: ChunkingStrategy | None = Field(
        None, description="Override auto-selected chunking - applies to every file in this batch."
    )
    chunk_size: int | None = Field(
        None, ge=MIN_CHUNK_SIZE, le=MAX_CHUNK_SIZE, description="Override CHUNK_DEFAULT_SIZE for this batch."
    )
    chunk_overlap: int | None = Field(None, ge=0, description="Override CHUNK_DEFAULT_OVERLAP for this batch.")

    @model_validator(mode="after")
    def _overlap_must_fit_within_half_the_chunk_size(self) -> "ChunkInfoInput":
        # Only checked when both are given - a caller overriding just one of
        # the two is comparing against the other's server-side default,
        # which this model has no way to know.
        if self.chunk_size is not None and self.chunk_overlap is not None and self.chunk_overlap > self.chunk_size // 2:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) can be at most half of chunk_size ({self.chunk_size})."
            )
        return self


class DocumentMetadataInput(BaseModel):
    """Caller-supplied document metadata - overrides extraction's guess, null fields still get filled in."""

    supersedes_document_id: str | None = Field(
        None,
        max_length=100,
        description="Marks this as a new version of an existing document (single-file uploads only).",
    )
    doc_category: str | None = Field(None, max_length=100)
    department: str | None = Field(None, max_length=100)
    doc_description: str | None = Field(None, max_length=100)
    restricted_roles: list[str] | None = Field(
        None,
        description="Phase 231 - caller-supplied only, never LLM-extracted. "
        "Null/empty means visible to every retrieval-eligible role, unchanged from today.",
    )
    owner: str | None = Field(None, max_length=200)
    purpose: str | None = Field(None, max_length=500)
    effective_date: str | None = Field(None, max_length=100)
    audience: str | None = Field(None, max_length=200)
    confidentiality_level: str | None = Field(None, max_length=100)
    author: str | None = Field(None, max_length=200)
    doc_date: str | None = Field(None, max_length=100)
    doc_version: str | None = Field(None, max_length=100)


class UploadDocumentsPayload(BaseModel):
    """Parsed from the `payload` multipart form field - a JSON string, since a file upload can't be pure JSON."""

    user_profile: UserProfile | None = None
    chunk_info: ChunkInfoInput | None = None
    document_metadata: DocumentMetadataInput | None = None


class ReindexDocumentPayload(BaseModel):
    """Phase 125 - same multipart-form-field-as-JSON-string pattern as
    UploadDocumentsPayload, deliberately smaller: no document_metadata/
    supersedes_document_id, neither applies to an in-place content replace."""

    user_profile: UserProfile | None = None
    chunk_info: ChunkInfoInput | None = None


class ChunkInfoResult(BaseModel):
    chunking_strategy: str | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    action: str | None = Field(
        None, description="'insert' or 'update' - which indexing outcome this was. Null for 'duplicate'/'rejected'."
    )
    chunks_indexed: int | None = Field(None, description="How many chunks were written. Null if not indexed.")
    chunks_removed: int | None = Field(None, description="Stale chunks removed by this index. Null if not indexed.")


class DocumentMetadataResult(BaseModel):
    doc_category: str | None = Field(
        None, description="e.g. 'policy', 'regulatory', 'investment' - caller-supplied, or the "
        "extraction step's best guess, not a controlled vocabulary."
    )
    department: str | None = None
    doc_description: str | None = Field(
        None,
        description="The specific topic this document covers, in the document's own terms (e.g. "
        "'401k') - caller-supplied, or the extraction step's best guess.",
    )
    restricted_roles: list[str] | None = Field(
        None, description="Phase 231 - which roles may retrieve this document; null means everyone can."
    )
    owner: str | None = None
    purpose: str | None = None
    effective_date: str | None = None
    audience: str | None = None
    confidentiality_level: str | None = None
    author: str | None = Field(None, description="Caller-supplied, or the extraction step's best guess.")
    doc_date: str | None = Field(
        None, description="The document's own stated date (created/published), distinct from effective_date."
    )
    doc_version: str | None = Field(None, description="The document's own stated version, e.g. '1.0'.")


class VersioningInfo(BaseModel):
    document_version: int | None = Field(
        None, description="0 until the first successful index, then 1 - increments on each re-index."
    )
    is_current: bool | None = Field(
        None,
        description="False once a newer upload has explicitly superseded this document - its chunks "
        "are excluded from retrieval by default, though not deleted.",
    )
    supersedes: str | None = Field(None, description="The document_id this one explicitly replaced, if any.")
    superseded_by: str | None = Field(None, description="The document_id that replaced this one, if any.")


class DocumentUploadResult(BaseModel):
    """What happened to one uploaded file."""

    filename: str = Field(..., description="The original filename as uploaded.")
    document_id: str | None = Field(
        None,
        description=(
            "The id this document is stored under, or null if it was rejected. On a 'duplicate' "
            "result, this is the EXISTING document's id, not a new one."
        ),
    )
    status: str = Field(
        ...,
        description=(
            "'uploaded' if a new document was stored, 'duplicate' if identical content was already "
            "uploaded before (no new document created - see message), 'rejected' if invalid. "
            "Phase 125's reindex endpoint also returns this shape: 'reindexed' (content changed, "
            "full re-index ran) or 'unchanged' (uploaded content's hash matched what was already indexed)."
        ),
    )
    chunk_info: ChunkInfoResult | None = None
    document_metadata: DocumentMetadataResult | None = None
    versioning_info: VersioningInfo | None = None
    uploaded_by: str | None = Field(None, description="The caller's employee_id, from user_profile - audit only.")
    error: str | None = Field(None, description="Why this file was rejected, if it was.")
    error_code: str | None = Field(
        None,
        description=(
            "Stable, machine-readable reason for a 'rejected' result (see common/error_codes.py) - "
            "e.g. INVALID_FILE_TYPE, EMPTY_FILE, FILE_TOO_LARGE - for a caller deciding which files "
            "in a batch are worth retrying, without string-matching `error`'s prose."
        ),
    )
    message: str | None = Field(
        None, description="Informational note, e.g. which existing document a 'duplicate' matched."
    )
    file_size_bytes: int | None = Field(
        None, description="The file's size in bytes - present for 'uploaded' and 'duplicate', null "
        "for 'rejected'."
    )


class DocumentUploadResponse(BaseModel):
    """What POST /rag/documents returns - one result per file, in upload order."""

    uploaded_count: int = Field(..., description="How many files were stored as new documents.")
    duplicate_count: int = Field(
        ..., description="How many files matched a document already uploaded - see each result's "
        "message for which existing document_id."
    )
    rejected_count: int = Field(..., description="How many files were rejected.")
    results: list[DocumentUploadResult] = Field(..., description="One entry per file uploaded.")


class DocumentRecord(BaseModel):
    """One document's metadata, as returned by the list and get-by-id endpoints."""

    id: str
    filename: str
    file_path: str
    status: str = Field(..., description="'uploaded', 'indexed', or 'failed'.")
    error_message: str | None = None
    created_at: str
    updated_at: str
    last_indexed_at: str | None = Field(
        None,
        description="When the most recent *successful* index finished - unlike updated_at, this "
        "doesn't move on a failed index attempt.",
    )
    chunk_ids: list[str] | None = Field(
        None, description="Vector-store ids this document's chunks were written under, or null if never indexed."
    )
    chunk_count: int = Field(0, description="How many chunks this document currently has.")
    file_size_bytes: int = Field(0, description="The uploaded file's size in bytes.")
    embedding_model: str | None = Field(None, description="Which embedding model produced the current chunks.")
    embedding_dimension: int | None = Field(
        None, description="The vector length that model produced - the actual length of a real "
        "embedding this document's chunks were written with."
    )
    vector_db: str | None = Field(None, description="Which vector store this document's chunks currently live in.")
    uploaded_by: str | None = Field(None, description="The caller's employee_id from upload time - audit only.")
    chunk_info: ChunkInfoResult | None = None
    document_metadata: DocumentMetadataResult | None = None
    versioning_info: VersioningInfo | None = None

    @classmethod
    def from_row(cls, document: dict) -> "DocumentRecord":
        """Map a flat metadata-store row into this nested shape - the one place this translation happens."""
        restricted_roles_raw = document.get("restricted_roles")
        restricted_roles = json.loads(restricted_roles_raw) if restricted_roles_raw else None
        return cls(
            id=document["id"],
            filename=document["filename"],
            file_path=document["file_path"],
            status=document["status"],
            error_message=document.get("error_message"),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
            last_indexed_at=document.get("last_indexed_at"),
            chunk_ids=document.get("chunk_ids"),
            chunk_count=document.get("chunk_count", 0),
            file_size_bytes=document.get("file_size_bytes", 0),
            embedding_model=document.get("embedding_model"),
            embedding_dimension=document.get("embedding_dimension"),
            vector_db=document.get("vector_db"),
            uploaded_by=document.get("uploaded_by"),
            chunk_info=ChunkInfoResult(
                chunking_strategy=document.get("chunking_strategy"),
                chunk_size=document.get("chunk_size"),
                chunk_overlap=document.get("chunk_overlap"),
            ),
            document_metadata=DocumentMetadataResult(
                doc_category=document.get("doc_category"),
                department=document.get("department"),
                doc_description=document.get("doc_description"),
                restricted_roles=restricted_roles,
                owner=document.get("owner"),
                purpose=document.get("purpose"),
                effective_date=document.get("effective_date"),
                audience=document.get("audience"),
                confidentiality_level=document.get("confidentiality_level"),
                author=document.get("author"),
                doc_date=document.get("doc_date"),
                doc_version=document.get("doc_version"),
            ),
            versioning_info=VersioningInfo(
                document_version=document.get("document_version"),
                is_current=document.get("is_current"),
                supersedes=document.get("supersedes"),
                superseded_by=document.get("superseded_by"),
            ),
        )


class DocumentListResponse(BaseModel):
    """What GET /rag/documents returns."""

    count: int
    documents: list[DocumentRecord]


class DocumentDeleteResponse(BaseModel):
    """What DELETE /rag/documents/{id} returns - a full delete, not partial/selective."""

    document_id: str
    filename: str = Field(..., description="The deleted document's filename, for confirmation.")
    chunks_removed: int = Field(
        ..., description="How many vectors were deleted from the vector store. 0 if the document "
        "had never been indexed."
    )
    deleted_by: str | None = Field(None, description="The caller's employee_id for this delete - audit only.")


class DocumentDeleteAllResponse(BaseModel):
    """What DELETE /rag/documents (no id) returns - same full-delete semantics as DocumentDeleteResponse."""

    documents_deleted: int = Field(..., description="How many documents were deleted.")
    chunks_removed: int = Field(..., description="Total vectors deleted across all documents.")
    deleted_by: str | None = Field(None, description="The caller's employee_id for this delete - audit only.")


class TestNoiseDocument(BaseModel):
    """One document that matches the test-noise size threshold (Phase 46)."""

    id: str
    filename: str
    file_size_bytes: int
    created_at: str


class TestNoisePreviewResponse(BaseModel):
    """What GET .../documents/cleanup/preview returns - deletes nothing, just previews it."""

    count: int = Field(..., description="How many documents are below the size threshold.")
    threshold_bytes: int = Field(..., description="file_size_bytes below this counts as test noise.")
    documents: list[TestNoiseDocument]


class PresignedUploadRequest(BaseModel):
    """Phase 89: JSON body for POST .../documents/presigned-upload - no file bytes yet,
    so this is plain JSON, not multipart like the upload endpoint above."""

    user_profile: UserProfile | None = None
    filename: str = Field(..., max_length=255)
    content_type: str = Field(..., max_length=100)
    chunk_info: ChunkInfoInput | None = None
    document_metadata: DocumentMetadataInput | None = None


class PresignedUploadResponse(BaseModel):
    """What POST .../documents/presigned-upload returns - nothing has been indexed yet,
    so this is deliberately not DocumentUploadResponse. Poll GET /documents/{id} afterward."""

    document_id: str
    upload_url: str = Field(..., description="PUT the file body directly here - no AWS SDK or credentials needed.")
    expires_in_seconds: int
    status: str = Field("pending_upload", description="Always 'pending_upload' - poll GET /documents/{id} for the real result.")
