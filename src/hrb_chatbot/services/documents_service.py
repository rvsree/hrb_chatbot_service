"""Saves uploaded files to disk and records their metadata - rejections are data, not raised."""

import asyncio
import json
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from src.hrb_chatbot.ai.doc_processing import pipeline
from src.hrb_chatbot.ai.doc_processing.indexing.vector_indexer import storage_chunk_ids
from src.hrb_chatbot.common.clients.db_client.langchain_vector_store import COLLECTION_NAME
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.storage_client.s3_upload_client import (
    delete_uploaded_object,
    download_for_reprocessing,
    generate_presigned_upload_url,
)
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.utils.content_hash import compute_content_hash
from src.hrb_chatbot.models.documents import (
    ALLOWED_CONTENT_TYPE,
    MAX_FILE_SIZE_BYTES,
    ChunkInfoInput,
    ChunkInfoResult,
    DocumentMetadataInput,
    DocumentMetadataResult,
    DocumentUploadResult,
    PresignedUploadResponse,
    VersioningInfo,
)

logger = get_logger("documents_service")

UPLOAD_DIRECTORY = Path("data/uploads")


async def _clear_answer_cache_best_effort() -> None:
    """Phase 78: a document change invalidates every cached answer - best-effort,
    since a down answer cache must never block an otherwise-successful
    upload/delete (unlike the cache's own get/set calls on the live query path,
    which do propagate - see pipeline.py)."""
    try:
        await get_db_gateway().answer_cache().clear_all()
    except Exception as error:
        logger.warning("Answer cache invalidation failed: %s: %s", type(error).__name__, error)


def _delete_s3_object_best_effort(document_id: str, filename: str) -> None:
    """Phase 121: a document delete must also remove its S3 source object,
    or an async-uploaded (Phase 89) file orphans there forever - best-effort,
    same reasoning as the answer-cache clear above."""
    try:
        delete_uploaded_object(document_id, filename)
    except Exception as error:
        logger.warning("S3 object delete failed for %s: %s: %s", document_id, type(error).__name__, error)


def validate_file(upload: UploadFile, size: int) -> tuple[str, str] | None:
    """Return (message, error_code) for why this file is rejected, or None."""
    filename = upload.filename or ""

    if upload.content_type != ALLOWED_CONTENT_TYPE and not filename.lower().endswith(".pdf"):
        return f"Only PDF files are accepted, got content_type={upload.content_type!r}", error_codes.INVALID_FILE_TYPE

    if size == 0:
        return "File is empty", error_codes.EMPTY_FILE

    if size > MAX_FILE_SIZE_BYTES:
        return (
            f"File is {size} bytes, which exceeds the {MAX_FILE_SIZE_BYTES}-byte limit",
            error_codes.FILE_TOO_LARGE,
        )

    return None


async def save_upload(
    upload: UploadFile,
    supersedes_document_id: str | None = None,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    document_metadata_override: DocumentMetadataInput | None = None,
    uploaded_by: str | None = None,
) -> DocumentUploadResult:
    """Validate, store, and record one uploaded file - never raises."""
    try:
        content = await upload.read()
    except Exception as error:
        logger.error("Could not read upload %r: %s", upload.filename, error)
        return DocumentUploadResult(
            filename=upload.filename or "unknown",
            document_id=None,
            status="rejected",
            error=f"Could not read the uploaded file: {error}",
            error_code=error_codes.UPLOAD_READ_FAILED,
        )

    size = len(content)
    validation_failure = validate_file(upload, size)
    if validation_failure:
        message, code = validation_failure
        logger.warning("Rejected upload %r: %s", upload.filename, message)
        return DocumentUploadResult(
            filename=upload.filename or "unknown",
            document_id=None,
            status="rejected",
            error=message,
            error_code=code,
        )

    # Same bytes = same document, regardless of filename - catches any upload of identical content, any time.
    content_hash = compute_content_hash(content)
    existing = await get_db_gateway().metadata_store().find_by_content_hash(content_hash)
    if existing is not None:
        logger.info(
            "Upload %r matches existing document %s (%s) by content - no new document created",
            upload.filename,
            existing["id"],
            existing["filename"],
        )
        return DocumentUploadResult(
            filename=upload.filename,
            document_id=existing["id"],
            status="duplicate",
            error=None,
            message=(
                f"Identical content already uploaded as document {existing['id']} "
                f"({existing['filename']!r}), version {existing['document_version']}. "
                "No new document was created - use that document_id to re-index if needed."
            ),
            file_size_bytes=existing["file_size_bytes"],
            versioning_info=VersioningInfo(
                document_version=existing["document_version"],
                is_current=existing.get("is_current"),
                supersedes=existing.get("supersedes"),
                superseded_by=existing.get("superseded_by"),
            ),
        )

    if supersedes_document_id:
        target = await get_db_gateway().metadata_store().get_document(supersedes_document_id)
        if target is None:
            logger.warning(
                "Upload %r cannot supersede unknown document %r", upload.filename, supersedes_document_id
            )
            return DocumentUploadResult(
                filename=upload.filename or "unknown",
                document_id=None,
                status="rejected",
                error=f"supersedes_document_id {supersedes_document_id!r} does not exist",
                error_code=error_codes.SUPERSEDES_TARGET_NOT_FOUND,
            )

    document_id = uuid.uuid4().hex
    document_directory = UPLOAD_DIRECTORY / document_id

    try:
        document_directory.mkdir(parents=True, exist_ok=True)
        file_path = document_directory / upload.filename
        file_path.write_bytes(content)

        await get_db_gateway().metadata_store().create_document(
            document_id,
            upload.filename,
            str(file_path),
            size,
            content_hash,
            supersedes=supersedes_document_id,
            uploaded_by=uploaded_by,
        )
    except Exception as error:
        # A real, unexpected failure - reported as a per-file rejection so the rest of the batch continues.
        logger.error("Failed to store upload %r (document %s): %s", upload.filename, document_id, error)
        return DocumentUploadResult(
            filename=upload.filename,
            document_id=None,
            status="rejected",
            error=f"Could not store the file: {error}",
            error_code=error_codes.STORAGE_FAILURE,
        )

    logger.info("Stored upload %r as document %s", upload.filename, document_id)

    # Index immediately - chunk, embed, write to the vector store - as part of the same upload call.
    index_outcome = await _index_now(
        document_id, file_path,
        chunking_strategy=chunking_strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        document_metadata_override=document_metadata_override,
    )
    document_metadata = index_outcome.get("document_metadata") or {}

    return DocumentUploadResult(
        filename=upload.filename,
        document_id=document_id,
        status="uploaded",
        error=index_outcome.get("error"),
        error_code=index_outcome.get("error_code"),
        file_size_bytes=size,
        uploaded_by=uploaded_by,
        chunk_info=ChunkInfoResult(
            chunking_strategy=index_outcome.get("chunking_strategy"),
            chunk_size=index_outcome.get("chunk_size"),
            chunk_overlap=index_outcome.get("chunk_overlap"),
            action=index_outcome.get("action"),
            chunks_indexed=index_outcome.get("chunks_indexed"),
            chunks_removed=index_outcome.get("chunks_removed"),
        ),
        document_metadata=DocumentMetadataResult(**document_metadata) if document_metadata else None,
        # 0 if indexing failed - matches what the row holds (only a successful index moves it to 1+).
        versioning_info=VersioningInfo(
            document_version=index_outcome.get("document_version", 0),
            is_current=True,
            supersedes=supersedes_document_id,
        ),
    )


async def _index_now(
    document_id: str,
    file_path,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    document_metadata_override: DocumentMetadataInput | None = None,
) -> dict:
    """Chunk/embed/index a just-uploaded file - never raises, a failure leaves status 'failed'."""
    # supersedes_document_id is handled separately, at create_document() time.
    override_dict = (
        document_metadata_override.model_dump(exclude={"supersedes_document_id"})
        if document_metadata_override
        else None
    )
    try:
        result = await pipeline.index_document(
            document_id,
            str(file_path),
            chunking_strategy=chunking_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            document_metadata_override=override_dict,
        )
        await _clear_answer_cache_best_effort()
        return result
    except Exception as error:
        logger.error("Indexing failed for document %s: %s: %s", document_id, type(error).__name__, error)
        # Phase 134: the document's current status is the last stage it
        # actually reached - read it before overwriting it to "failed" so
        # the stage isn't lost, and prefix it onto the real error text.
        existing = await get_db_gateway().metadata_store().get_document(document_id)
        failed_stage = existing["status"] if existing else "unknown"
        await get_db_gateway().metadata_store().update_status(document_id, "failed", f"[{failed_stage}] {error}")
        return {"error": "Upload succeeded, but indexing failed.", "error_code": error_codes.INDEXING_FAILED}


async def reindex_document(
    document_id: str,
    upload: UploadFile,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> DocumentUploadResult | None:
    """Phase 125: replace an existing document's file content in place, under
    the same document_id, and re-index it. Returns None if document_id doesn't
    exist - the route turns that into a 404, not a per-file 'rejected' result."""
    existing = await get_db_gateway().metadata_store().get_document(document_id)
    if existing is None:
        return None

    try:
        content = await upload.read()
    except Exception as error:
        logger.error("Could not read reindex upload %r for document %s: %s", upload.filename, document_id, error)
        return DocumentUploadResult(
            filename=upload.filename or "unknown",
            document_id=document_id,
            status="rejected",
            error=f"Could not read the uploaded file: {error}",
            error_code=error_codes.UPLOAD_READ_FAILED,
        )

    size = len(content)
    validation_failure = validate_file(upload, size)
    if validation_failure:
        message, code = validation_failure
        logger.warning("Rejected reindex upload %r for document %s: %s", upload.filename, document_id, message)
        return DocumentUploadResult(
            filename=upload.filename or "unknown",
            document_id=document_id,
            status="rejected",
            error=message,
            error_code=code,
        )

    content_hash = compute_content_hash(content)
    if content_hash == existing.get("content_hash"):
        logger.info("Reindex upload for document %s matches existing content - no-op", document_id)
        return DocumentUploadResult(
            filename=existing["filename"],
            document_id=document_id,
            status="unchanged",
            error=None,
            message="Uploaded content is identical to the current version - nothing to re-index.",
            file_size_bytes=existing["file_size_bytes"],
            versioning_info=VersioningInfo(document_version=existing["document_version"], is_current=True),
        )

    document_directory = UPLOAD_DIRECTORY / document_id
    try:
        # Old file(s) under this document_id - avoid orphaning them on disk (Phase 121's same reasoning, local disk this time).
        shutil.rmtree(document_directory, ignore_errors=True)
        document_directory.mkdir(parents=True, exist_ok=True)
        file_path = document_directory / upload.filename
        file_path.write_bytes(content)
    except Exception as error:
        logger.error("Failed to store reindex upload %r for document %s: %s", upload.filename, document_id, error)
        return DocumentUploadResult(
            filename=upload.filename,
            document_id=document_id,
            status="rejected",
            error=f"Could not store the file: {error}",
            error_code=error_codes.STORAGE_FAILURE,
        )

    logger.info("Stored reindex upload %r for document %s - re-indexing", upload.filename, document_id)

    index_outcome = await _index_now(
        document_id, file_path, chunking_strategy=chunking_strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    await get_db_gateway().metadata_store().update_document_content(
        document_id, upload.filename, str(file_path), size, content_hash
    )

    return DocumentUploadResult(
        filename=upload.filename,
        document_id=document_id,
        status="reindexed",
        error=index_outcome.get("error"),
        error_code=index_outcome.get("error_code"),
        file_size_bytes=size,
        chunk_info=ChunkInfoResult(
            chunking_strategy=index_outcome.get("chunking_strategy"),
            chunk_size=index_outcome.get("chunk_size"),
            chunk_overlap=index_outcome.get("chunk_overlap"),
            action=index_outcome.get("action"),
            chunks_indexed=index_outcome.get("chunks_indexed"),
            chunks_removed=index_outcome.get("chunks_removed"),
        ),
        versioning_info=VersioningInfo(
            document_version=index_outcome.get("document_version", existing["document_version"]),
            is_current=True,
            supersedes=existing.get("supersedes"),
            superseded_by=existing.get("superseded_by"),
        ),
    )


async def rechunk_document(
    document_id: str,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> DocumentUploadResult | None:
    """Phase 129: re-chunk/embed/index an existing document's already-stored
    file with new settings - no file upload, no content-hash check (the
    whole point is reprocessing the same bytes). Returns None if document_id
    doesn't exist - the route turns that into a 404."""
    existing = await get_db_gateway().metadata_store().get_document(document_id)
    if existing is None:
        return None

    # Phase 135: existing["file_path"] may be an s3:// URI (every document
    # uploaded through the presigned-upload path) - extract_text_from_pdf()
    # only understands a real local path, so download to one first.
    file_path = download_for_reprocessing(existing["file_path"], document_id, existing["filename"])
    logger.info("Re-chunking document %s with new settings (file unchanged)", document_id)

    index_outcome = await _index_now(
        document_id, file_path, chunking_strategy=chunking_strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )

    return DocumentUploadResult(
        filename=existing["filename"],
        document_id=document_id,
        status="reindexed",
        error=index_outcome.get("error"),
        error_code=index_outcome.get("error_code"),
        file_size_bytes=existing["file_size_bytes"],
        chunk_info=ChunkInfoResult(
            chunking_strategy=index_outcome.get("chunking_strategy"),
            chunk_size=index_outcome.get("chunk_size"),
            chunk_overlap=index_outcome.get("chunk_overlap"),
            action=index_outcome.get("action"),
            chunks_indexed=index_outcome.get("chunks_indexed"),
            chunks_removed=index_outcome.get("chunks_removed"),
        ),
        versioning_info=VersioningInfo(
            document_version=index_outcome.get("document_version", existing["document_version"]),
            is_current=True,
            supersedes=existing.get("supersedes"),
            superseded_by=existing.get("superseded_by"),
        ),
    )


async def request_presigned_upload(
    filename: str,
    content_type: str,
    supersedes_document_id: str | None = None,
    chunk_info: ChunkInfoInput | None = None,
    document_metadata: DocumentMetadataInput | None = None,
    uploaded_by: str | None = None,
) -> PresignedUploadResponse | None:
    """Phase 89: records a pending document row and hands back a presigned
    S3 PUT url - no file bytes exist yet, so there's no content-hash dedup
    check here (that needs real bytes; see RAG-ROADMAP.md Phase 88's
    flagged gap) and no indexing result either. Returns None if
    supersedes_document_id doesn't exist - same "let the route 404/422 it"
    convention as get_document()/delete_document()."""
    if supersedes_document_id:
        target = await get_db_gateway().metadata_store().get_document(supersedes_document_id)
        if target is None:
            return None

    document_id = uuid.uuid4().hex
    bucket = read_setting(None, "S3_UPLOAD_BUCKET")
    placeholder_path = f"s3://{bucket}/{document_id}/{filename}"

    await get_db_gateway().metadata_store().create_document(
        document_id,
        filename,
        placeholder_path,
        0,
        None,
        supersedes=supersedes_document_id,
        uploaded_by=uploaded_by,
    )
    await get_db_gateway().metadata_store().update_status(document_id, "pending_upload")

    overrides = {
        "chunk_info": chunk_info.model_dump() if chunk_info else None,
        "document_metadata": document_metadata.model_dump(exclude={"supersedes_document_id"}) if document_metadata else None,
    }
    if chunk_info or document_metadata:
        await get_db_gateway().metadata_store().set_pending_overrides(document_id, json.dumps(overrides))

    presigned = generate_presigned_upload_url(document_id, filename, content_type)
    logger.info("Issued a presigned upload url for document %s (%r)", document_id, filename)

    return PresignedUploadResponse(
        document_id=document_id,
        upload_url=presigned["upload_url"],
        expires_in_seconds=presigned["expires_in_seconds"],
        status="pending_upload",
    )


async def save_uploads(
    uploads: list[UploadFile],
    supersedes_document_id: str | None = None,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    document_metadata_override: DocumentMetadataInput | None = None,
    uploaded_by: str | None = None,
) -> list[DocumentUploadResult]:
    """Validate, store, and record every uploaded file - one result per file."""
    # One at a time, not in parallel - simpler to follow, and uploads aren't the bottleneck here.
    results = []
    for upload in uploads:
        result = await save_upload(
            upload,
            supersedes_document_id=supersedes_document_id,
            chunking_strategy=chunking_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            document_metadata_override=document_metadata_override,
            uploaded_by=uploaded_by,
        )
        results.append(result)
    return results


def _parse_chunk_ids(document: dict) -> dict:
    """Turn the stored chunk_ids JSON string into a real list - the one place that decodes it."""
    raw = document.get("chunk_ids")
    if raw:
        document["chunk_ids"] = json.loads(raw)
    else:
        document["chunk_ids"] = None
    return document


async def list_documents() -> list[dict]:
    """Return every uploaded document's metadata, newest first."""
    documents = await get_db_gateway().metadata_store().list_documents()
    return [_parse_chunk_ids(document) for document in documents]


async def get_document(document_id: str) -> dict | None:
    """Return one document's metadata, or None if the id is unknown."""
    document = await get_db_gateway().metadata_store().get_document(document_id)
    if document is None:
        return None
    return _parse_chunk_ids(document)


async def delete_document(document_id: str, deleted_by: str | None = None) -> dict | None:
    """Delete one document: vectors, metadata row, uploaded file - None if unknown."""
    gateway = get_db_gateway()
    metadata_store = gateway.metadata_store()
    document = await metadata_store.get_document(document_id)
    if document is None:
        return None

    chunk_ids = []
    if document.get("chunk_ids"):
        chunk_ids = json.loads(document["chunk_ids"])

    if chunk_ids:
        vector_store = gateway.vector_store(provider=document.get("vector_db"))
        # LlamaIndex indexing prefixes Pinecone ids - storage_chunk_ids() is a no-op for Chroma, real for Pinecone.
        # Phase 139: vector_store.delete() is a plain synchronous SDK call
        # (Pinecone/Chroma, not async) - calling it directly here blocked
        # the whole event loop for its network round-trip, serializing a
        # bulk delete's concurrent requests even though the frontend
        # already fires them with Promise.all. Same asyncio.to_thread()
        # pattern conversation_store.py/feedback_store.py already use for
        # this exact reason.
        await asyncio.to_thread(
            vector_store.delete,
            collection_name=COLLECTION_NAME,
            ids=storage_chunk_ids(vector_store.PROVIDER_NAME, document_id, chunk_ids),
        )
        logger.info("Deleted %d vector(s) for document %s", len(chunk_ids), document_id)

    await metadata_store.delete_document(document_id)

    document_directory = UPLOAD_DIRECTORY / document_id
    shutil.rmtree(document_directory, ignore_errors=True)

    # Phase 139: delete_uploaded_object() is a synchronous boto3 S3 call -
    # same event-loop-blocking issue as the vector delete above.
    await asyncio.to_thread(_delete_s3_object_best_effort, document_id, document["filename"])
    await _clear_answer_cache_best_effort()

    logger.info("Deleted document %s (%r) - %d chunk(s) removed", document_id, document["filename"], len(chunk_ids))
    return {
        "document_id": document_id,
        "filename": document["filename"],
        "chunks_removed": len(chunk_ids),
        "deleted_by": deleted_by,
    }


async def delete_all_documents(deleted_by: str | None = None) -> dict:
    """Delete every document - same full delete as delete_document(), just for all of them."""
    documents = await list_documents()
    documents_deleted = 0
    chunks_removed = 0
    for document in documents:
        result = await delete_document(document["id"], deleted_by=deleted_by)
        if result is not None:  # already gone by the time we got here - skip, don't crash the batch
            documents_deleted += 1
            chunks_removed += result["chunks_removed"]

    logger.info("Deleted all %d document(s) - %d chunk(s) removed in total", documents_deleted, chunks_removed)
    return {"documents_deleted": documents_deleted, "chunks_removed": chunks_removed, "deleted_by": deleted_by}


async def _find_test_noise_documents(max_file_size_bytes: int) -> list[dict]:
    documents = await list_documents()
    return [document for document in documents if (document.get("file_size_bytes") or 0) < max_file_size_bytes]


async def list_test_noise_documents(max_file_size_bytes: int) -> list[dict]:
    """Preview only - which documents delete_test_noise_documents() would remove, without removing anything."""
    return await _find_test_noise_documents(max_file_size_bytes)


async def delete_test_noise_documents(max_file_size_bytes: int, deleted_by: str | None = None) -> dict:
    """Delete every document below max_file_size_bytes - same semantics as delete_document(), test-noise scoped."""
    documents = await _find_test_noise_documents(max_file_size_bytes)
    documents_deleted = 0
    chunks_removed = 0
    for document in documents:
        result = await delete_document(document["id"], deleted_by=deleted_by)
        if result is not None:
            documents_deleted += 1
            chunks_removed += result["chunks_removed"]

    logger.info(
        "Deleted %d test-noise document(s) (< %d bytes) - %d chunk(s) removed in total",
        documents_deleted,
        max_file_size_bytes,
        chunks_removed,
    )
    return {"documents_deleted": documents_deleted, "chunks_removed": chunks_removed, "deleted_by": deleted_by}
