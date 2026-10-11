from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import ValidationError

from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.common import IdentityPayload, UserProfile
from src.hrb_chatbot.models.documents import (
    ALLOWED_CONTENT_TYPE,
    PAYLOAD_MAX_LENGTH,
    TEST_NOISE_MAX_FILE_SIZE_BYTES,
    DocumentDeleteAllResponse,
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentRecord,
    DocumentUploadResponse,
    DocumentUploadResult,
    PresignedUploadRequest,
    PresignedUploadResponse,
    ReindexDocumentPayload,
    TestNoiseDocument,
    TestNoisePreviewResponse,
    UploadDocumentsPayload,
)
from src.hrb_chatbot.services import documents_service

logger = get_logger("ingest_document")

router_ingest_document = APIRouter(tags=["documents"])


def _parse_payload(raw_payload: str | None) -> UploadDocumentsPayload | None:
    """Missing payload -> {}; returns None on malformed JSON so the route can return 422, not a 500."""
    if not raw_payload:
        return UploadDocumentsPayload()
    try:
        return UploadDocumentsPayload.model_validate_json(raw_payload)
    except ValidationError:
        return None


@router_ingest_document.post("/documents", response_model=DocumentUploadResponse)
async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    payload: str | None = Form(None, max_length=PAYLOAD_MAX_LENGTH),
):
    # Upload, chunk, embed, and index one or more PDFs in one call - a single file is just a list of one.
    parsed_payload = _parse_payload(payload)
    if parsed_payload is None:
        return json_error(422, "payload is not valid JSON, or doesn't match the expected shape.", code=error_codes.VALIDATION_ERROR)

    userProfile = require_role(parsed_payload.user_profile, Role.HR_SUPPORT)
    await enforce_rate_limit(request)

    chunk_info = parsed_payload.chunk_info
    document_metadata = parsed_payload.document_metadata
    supersedes_document_id = document_metadata.supersedes_document_id if document_metadata else None

    if supersedes_document_id and len(files) != 1:
        return json_error(
            422,
            "supersedes_document_id is only valid with exactly one file - ambiguous for a batch upload.",
            code=error_codes.VALIDATION_ERROR,
        )

    results = await documents_service.save_uploads(
        files,
        supersedes_document_id=supersedes_document_id,
        chunking_strategy=chunk_info.chunking_strategy if chunk_info else None,
        chunk_size=chunk_info.chunk_size if chunk_info else None,
        chunk_overlap=chunk_info.chunk_overlap if chunk_info else None,
        document_metadata_override=document_metadata,
        uploaded_by=userProfile.employee_id,
    )

    uploaded_count = 0
    duplicate_count = 0
    for result in results:
        if result.status == "uploaded":
            uploaded_count += 1
        elif result.status == "duplicate":
            duplicate_count += 1
    rejected_count = len(results) - uploaded_count - duplicate_count

    response = DocumentUploadResponse(
        uploaded_count=uploaded_count,
        duplicate_count=duplicate_count,
        rejected_count=rejected_count,
        results=results,
    )

    return response


def _parse_reindex_payload(raw_payload: str | None) -> ReindexDocumentPayload | None:
    if not raw_payload:
        return ReindexDocumentPayload()
    try:
        return ReindexDocumentPayload.model_validate_json(raw_payload)
    except ValidationError:
        return None


@router_ingest_document.post("/documents/{document_id}/reindex", response_model=DocumentUploadResult)
async def reindex_document(
    document_id: str,
    request: Request,
    file: UploadFile = File(...),
    payload: str | None = Form(None, max_length=PAYLOAD_MAX_LENGTH),
):
    # Phase 125: replace this document's file content in place, under the same document_id, and re-index it.
    parsed_payload = _parse_reindex_payload(payload)
    if parsed_payload is None:
        return json_error(422, "payload is not valid JSON, or doesn't match the expected shape.", code=error_codes.VALIDATION_ERROR)

    require_role(parsed_payload.user_profile, Role.HR_SUPPORT)
    await enforce_rate_limit(request)

    chunk_info = parsed_payload.chunk_info
    result = await documents_service.reindex_document(
        document_id,
        file,
        chunking_strategy=chunk_info.chunking_strategy if chunk_info else None,
        chunk_size=chunk_info.chunk_size if chunk_info else None,
        chunk_overlap=chunk_info.chunk_overlap if chunk_info else None,
    )

    if result is None:
        return json_error(404, f"No document found with id {document_id!r}", code=error_codes.DOCUMENT_NOT_FOUND)

    return result


@router_ingest_document.post("/documents/{document_id}/rechunk", response_model=DocumentUploadResult)
async def rechunk_document(document_id: str, payload: ReindexDocumentPayload, request: Request):
    # Phase 129: re-chunk the already-stored file with new settings - no file upload needed.
    require_role(payload.user_profile, Role.HR_SUPPORT)
    await enforce_rate_limit(request)

    chunk_info = payload.chunk_info
    result = await documents_service.rechunk_document(
        document_id,
        chunking_strategy=chunk_info.chunking_strategy if chunk_info else None,
        chunk_size=chunk_info.chunk_size if chunk_info else None,
        chunk_overlap=chunk_info.chunk_overlap if chunk_info else None,
    )

    if result is None:
        return json_error(404, f"No document found with id {document_id!r}", code=error_codes.DOCUMENT_NOT_FOUND)

    return result


@router_ingest_document.post("/documents/presigned-upload", response_model=PresignedUploadResponse)
async def request_presigned_upload(body: PresignedUploadRequest, request: Request):
    # Phase 89: additive, alongside upload_documents() above - that endpoint is unchanged.
    # No file bytes here, just a document_id + a presigned S3 PUT url the client uploads to directly.
    userProfile = require_role(body.user_profile, Role.HR_SUPPORT)
    await enforce_rate_limit(request)

    if body.content_type != ALLOWED_CONTENT_TYPE and not body.filename.lower().endswith(".pdf"):
        return json_error(
            422,
            f"Only PDF files are accepted, got content_type={body.content_type!r}",
            code=error_codes.INVALID_FILE_TYPE,
        )

    supersedes_document_id = body.document_metadata.supersedes_document_id if body.document_metadata else None

    result = await documents_service.request_presigned_upload(
        body.filename,
        body.content_type,
        supersedes_document_id=supersedes_document_id,
        chunk_info=body.chunk_info,
        document_metadata=body.document_metadata,
        uploaded_by=userProfile.employee_id,
    )

    if result is None:
        return json_error(
            422,
            f"supersedes_document_id {supersedes_document_id!r} does not exist",
            code=error_codes.SUPERSEDES_TARGET_NOT_FOUND,
        )

    return result


@router_ingest_document.get("/documents", response_model=DocumentListResponse)
async def list_documents(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """List every uploaded document and its current status."""
    require_role(user_profile, Role.HR_SUPPORT)
    documents = await documents_service.list_documents()
    return DocumentListResponse(count=len(documents), documents=[DocumentRecord.from_row(doc) for doc in documents])


@router_ingest_document.get("/documents/cleanup/preview", response_model=TestNoisePreviewResponse)
async def preview_test_noise_documents(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Preview only - what DELETE .../documents/cleanup would remove, without removing anything."""
    require_role(user_profile, Role.HR_SUPPORT)
    documents = await documents_service.list_test_noise_documents(TEST_NOISE_MAX_FILE_SIZE_BYTES)
    return TestNoisePreviewResponse(
        count=len(documents),
        threshold_bytes=TEST_NOISE_MAX_FILE_SIZE_BYTES,
        documents=[TestNoiseDocument(**document) for document in documents],
    )


@router_ingest_document.delete("/documents/cleanup", response_model=DocumentDeleteAllResponse)
async def delete_test_noise_documents(identity: IdentityPayload, request: Request):
    """Delete every document below TEST_NOISE_MAX_FILE_SIZE_BYTES - same full-delete semantics as DELETE /documents."""
    userProfile = require_role(identity.user_profile, Role.HR_SUPPORT)
    await enforce_rate_limit(request)
    result = await documents_service.delete_test_noise_documents(
        TEST_NOISE_MAX_FILE_SIZE_BYTES, deleted_by=userProfile.employee_id
    )
    return DocumentDeleteAllResponse(**result)


@router_ingest_document.get("/documents/{document_id}", response_model=DocumentRecord)
async def get_document(document_id: str, user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Get one document's metadata by id."""
    require_role(user_profile, Role.HR_SUPPORT)
    document = await documents_service.get_document(document_id)

    if document is None:
        return json_error(404, f"Unknown document '{document_id}'", code=error_codes.DOCUMENT_NOT_FOUND)

    return DocumentRecord.from_row(document)


@router_ingest_document.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(document_id: str, identity: IdentityPayload, request: Request):
    """Delete one document completely: vectors, metadata rows, uploaded file."""
    userProfile = require_role(identity.user_profile, Role.HR_SUPPORT)
    await enforce_rate_limit(request)
    result = await documents_service.delete_document(document_id, deleted_by=userProfile.employee_id)

    if result is None:
        return json_error(404, f"Unknown document '{document_id}'", code=error_codes.DOCUMENT_NOT_FOUND)

    return DocumentDeleteResponse(**result)


@router_ingest_document.delete("/documents", response_model=DocumentDeleteAllResponse)
async def delete_all_documents(identity: IdentityPayload, request: Request):
    """Delete every document completely - same full delete as DELETE /documents/{id}, just for all of them."""
    userProfile = require_role(identity.user_profile, Role.HR_SUPPORT)
    await enforce_rate_limit(request)
    result = await documents_service.delete_all_documents(deleted_by=userProfile.employee_id)
    return DocumentDeleteAllResponse(**result)
