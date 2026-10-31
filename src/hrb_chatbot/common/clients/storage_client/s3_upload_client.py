"""Generates presigned S3 upload URLs (Phase 89) - a plain function, not a
Base*Client/Gateway pair like the vector/metadata stores, since there's
only one storage provider here, nothing to swap at runtime."""

from pathlib import Path

import boto3

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("s3_upload_client")

DEFAULT_REGION = "us-east-1"
DEFAULT_EXPIRY_SECONDS = 300

# Matches documents_service.py's own UPLOAD_DIRECTORY - not imported from
# there to avoid a circular import (documents_service already imports this module).
UPLOAD_DIRECTORY = Path("data/uploads")


def generate_presigned_upload_url(document_id: str, filename: str, content_type: str) -> dict:
    """Returns {"upload_url": str, "expires_in_seconds": int} - the client
    PUTs the file body directly to upload_url, no AWS SDK/credentials needed
    on their end. Key convention ("{document_id}/{filename}") matches
    documents_service.py's local UPLOAD_DIRECTORY layout and the Lambda
    handler's own key-parsing (Phase 88)."""
    bucket = read_setting(None, "S3_UPLOAD_BUCKET")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)
    expiry_seconds = int(read_setting(None, "S3_PRESIGNED_URL_EXPIRY_SECONDS", DEFAULT_EXPIRY_SECONDS))

    s3_client = boto3.client("s3", region_name=region)
    key = f"{document_id}/{filename}"

    with log_backend_call(logger, "s3", "generate_presigned_url", document_id=document_id):
        upload_url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expiry_seconds,
        )

    return {"upload_url": upload_url, "expires_in_seconds": expiry_seconds}


def generate_leave_document_upload_url(leave_request_token: str, filename: str, content_type: str) -> dict:
    """Phase 162 - same presigned-PUT shape as generate_presigned_upload_url(),
    but reads LEAVE_DOCS_S3_BUCKET, never S3_UPLOAD_BUCKET. Separate bucket on
    purpose - S3_UPLOAD_BUCKET has a whole-bucket S3 event notification that
    triggers the KB ingestion Lambda (docs/agent-reference/S3-ASYNC-UPLOAD-DESIGN.md,
    not prefix-scoped), so a leave document dropped there would silently get
    chunked/embedded into the shared RAG vector index - a real privacy bug for
    something like a medical certificate, not a hypothetical one."""
    bucket = read_setting(None, "LEAVE_DOCS_S3_BUCKET")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)
    expiry_seconds = int(read_setting(None, "S3_PRESIGNED_URL_EXPIRY_SECONDS", DEFAULT_EXPIRY_SECONDS))

    s3_client = boto3.client("s3", region_name=region)
    key = f"{leave_request_token}/{filename}"

    with log_backend_call(logger, "s3", "generate_presigned_url", leave_request_token=leave_request_token):
        upload_url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expiry_seconds,
        )

    return {"upload_url": upload_url, "key": key, "expires_in_seconds": expiry_seconds}


def generate_leave_document_download_url(s3_key: str) -> dict:
    """Phase 165 - the symmetric presigned-GET counterpart to
    generate_leave_document_upload_url()'s presigned-PUT. Reads the same
    LEAVE_DOCS_S3_BUCKET; the key is already real (looked up from
    unpaid_leave_documents' own manifest row via the caller, never
    constructed here), so this is a short function - the gap this closes
    was never technical difficulty, just that this half was never built."""
    bucket = read_setting(None, "LEAVE_DOCS_S3_BUCKET")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)
    expiry_seconds = int(read_setting(None, "S3_PRESIGNED_URL_EXPIRY_SECONDS", DEFAULT_EXPIRY_SECONDS))

    s3_client = boto3.client("s3", region_name=region)

    with log_backend_call(logger, "s3", "generate_presigned_url", s3_key=s3_key):
        download_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": s3_key},
            ExpiresIn=expiry_seconds,
        )

    return {"download_url": download_url, "expires_in_seconds": expiry_seconds}


def delete_leave_document_object(s3_key: str) -> None:
    """Phase 168 - admin-only real S3 cleanup, called after
    hrb_lms_mcp's own admin_delete_hitl_request has already removed the
    manifest row. Best-effort by design (same as delete_uploaded_object
    above) - delete_object on an already-missing key is a no-op, not an
    error. Unlike delete_uploaded_object, takes the real key directly
    rather than reconstructing it, since the manifest row (not a
    document_id/filename convention) is this feature's own source of truth
    for what a document's key actually is."""
    bucket = read_setting(None, "LEAVE_DOCS_S3_BUCKET")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)
    s3_client = boto3.client("s3", region_name=region)

    with log_backend_call(logger, "s3", "delete_object", s3_key=s3_key):
        s3_client.delete_object(Bucket=bucket, Key=s3_key)


def delete_uploaded_object(document_id: str, filename: str) -> None:
    """Best-effort S3 cleanup on document delete - same key convention as
    generate_presigned_upload_url, safe to call even if this document was
    never actually uploaded via S3 (delete_object on a missing key is a no-op)."""
    bucket = read_setting(None, "S3_UPLOAD_BUCKET")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)
    s3_client = boto3.client("s3", region_name=region)
    key = f"{document_id}/{filename}"

    with log_backend_call(logger, "s3", "delete_object", document_id=document_id):
        s3_client.delete_object(Bucket=bucket, Key=key)


def upload_admin_doc_file(local_path: str, s3_key: str, content_type: str) -> None:
    """Phase 170 (round 1) - server-side upload for the admin docs sync
    script (sync_admin_docs.py runs with real AWS credentials, on the dev
    machine/CI, not in a browser - a direct put_object is simpler than a
    presigned PUT here). Reuses LEAVE_DOCS_S3_BUCKET under a new
    admin-docs/ prefix - deliberately NOT S3_UPLOAD_BUCKET, which has a
    whole-bucket event notification that triggers KB ingestion (same
    reasoning Phase 162 already used to keep leave documents off that
    bucket too - an admin doc landing there would silently get chunked
    into the RAG vector index)."""
    bucket = read_setting(None, "LEAVE_DOCS_S3_BUCKET")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)
    s3_client = boto3.client("s3", region_name=region)

    with log_backend_call(logger, "s3", "put_object", s3_key=s3_key):
        with open(local_path, "rb") as file_handle:
            s3_client.put_object(Bucket=bucket, Key=s3_key, Body=file_handle.read(), ContentType=content_type)


# Phase 281 - extensions no browser can render as a page. S3 serves these
# as application/xml (or similar) with no Content-Disposition, so without
# forcing a download the browser just shows raw source text - never the
# actual diagram.
NON_RENDERABLE_DOC_EXTENSIONS = {".drawio"}


def generate_admin_doc_download_url(s3_key: str) -> dict:
    """Phase 170 (round 1) - presigned-GET for the admin doc viewer,
    symmetric to generate_leave_document_download_url(). Phase 281 - a
    non-renderable file type (.drawio) forces a real download instead of
    displaying as raw text in the browser."""
    bucket = read_setting(None, "LEAVE_DOCS_S3_BUCKET")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)
    expiry_seconds = int(read_setting(None, "S3_PRESIGNED_URL_EXPIRY_SECONDS", DEFAULT_EXPIRY_SECONDS))

    s3_client = boto3.client("s3", region_name=region)
    params = {"Bucket": bucket, "Key": s3_key}
    if Path(s3_key).suffix.lower() in NON_RENDERABLE_DOC_EXTENSIONS:
        params["ResponseContentDisposition"] = f'attachment; filename="{Path(s3_key).name}"'

    with log_backend_call(logger, "s3", "generate_presigned_url", s3_key=s3_key):
        download_url = s3_client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expiry_seconds,
        )

    return {"download_url": download_url, "expires_in_seconds": expiry_seconds}


def download_for_reprocessing(file_path: str, document_id: str, filename: str) -> str:
    """Phase 135: a local path is returned unchanged (the old synchronous-
    upload case - nothing to download). An `s3://bucket/key` URI (every
    document uploaded through the presigned-upload path, the default since
    Phase 89's frontend wiring) is downloaded to the same local layout a
    synchronous upload already uses, and that local path is returned -
    index_document()'s extract_text_from_pdf() only ever understands a
    real local path, never an S3 URI directly."""
    if not file_path.startswith("s3://"):
        return file_path

    without_scheme = file_path[len("s3://") :]
    bucket, _, key = without_scheme.partition("/")
    region = read_setting(None, "AWS_REGION", DEFAULT_REGION)
    s3_client = boto3.client("s3", region_name=region)

    document_directory = UPLOAD_DIRECTORY / document_id
    document_directory.mkdir(parents=True, exist_ok=True)
    local_path = document_directory / filename

    with log_backend_call(logger, "s3", "download_file", document_id=document_id):
        s3_client.download_file(bucket, key, str(local_path))

    return str(local_path)
