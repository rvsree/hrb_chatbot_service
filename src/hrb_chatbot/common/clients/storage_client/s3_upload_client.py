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
