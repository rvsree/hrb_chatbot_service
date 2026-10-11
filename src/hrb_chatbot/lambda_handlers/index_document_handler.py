"""Lambda entry point - SQS (triggered by an S3 ObjectCreated event) -> index
one document. A thin adapter: reads the event, downloads the object, calls
ai/doc_processing/pipeline.py's existing index_document() unchanged - see
RAG-ROADMAP.md Phase 88."""

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import unquote_plus

import boto3

from src.hrb_chatbot.ai.doc_processing import pipeline
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.utils.content_hash import compute_content_hash

TMP_DIRECTORY = Path("/tmp")


class _JsonFormatter(logging.Formatter):
    """One JSON line per log record - CloudWatch Logs Insights can then query
    fields directly, unlike the rest of this project's deliberately
    plain-text logs (see Phase 88's spec for why Lambda alone gets this)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Phase 133: logger.error(..., exc_info=True) was already capturing
        # the real traceback - this formatter was just dropping it before
        # it reached the log line, making every past failure here opaque.
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("lambda_handlers.index_document")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


logger = _get_logger()


def _parse_s3_event(sqs_record: dict) -> tuple[str, str] | None:
    """Return (bucket, key) from one SQS message body, or None for a non-upload
    event (e.g. the s3:TestEvent S3 sends when a notification is first configured).
    Phase 133: S3's own ObjectCreated notification URL-encodes the key (a
    space becomes "+", other characters percent-encoded) - decoded here so
    a real filename with a space in it (any real-world PDF, not just this
    project's own underscore-named KB docs) downloads from the real key."""
    body = json.loads(sqs_record["body"])
    if body.get("Event") == "s3:TestEvent":
        return None

    s3_info = body["Records"][0]["s3"]
    return s3_info["bucket"]["name"], unquote_plus(s3_info["object"]["key"])


def _document_id_and_filename(key: str) -> tuple[str, str]:
    """Key convention: "{document_id}/{filename}" - the same layout
    documents_service.py already uses for local uploads under data/uploads/."""
    document_id, _, filename = key.partition("/")
    return document_id, filename or key


def _pending_overrides_kwargs(existing: dict) -> dict:
    """Phase 89: the presigned-upload route stashes chunk_info/document_metadata
    on the row it already created - unpack them into index_document()'s own
    kwargs. Returns {} if there's nothing pending (the Phase 88 direct-S3-put
    fallback path, or a retry after they were already cleared)."""
    raw = existing.get("pending_overrides")
    if not raw:
        return {}

    overrides = json.loads(raw)
    kwargs = {}
    chunk_info = overrides.get("chunk_info")
    if chunk_info:
        kwargs["chunking_strategy"] = chunk_info.get("chunking_strategy")
        kwargs["chunk_size"] = chunk_info.get("chunk_size")
        kwargs["chunk_overlap"] = chunk_info.get("chunk_overlap")
    document_metadata = overrides.get("document_metadata")
    if document_metadata:
        kwargs["document_metadata_override"] = document_metadata
    return kwargs


async def _index_one(bucket: str, key: str) -> None:
    document_id, filename = _document_id_and_filename(key)
    local_path = TMP_DIRECTORY / document_id / filename
    local_path.parent.mkdir(parents=True, exist_ok=True)

    metadata_store = get_db_gateway().metadata_store()
    # Checked before the download (not after, like before Phase 103) so a
    # real, possibly-slow S3 transfer has a status to show while it runs -
    # only possible when the row already exists (the presigned-upload
    # path); the row-less fallback path below still has nothing to update yet.
    existing = await metadata_store.get_document(document_id)
    if existing is not None:
        await metadata_store.update_status(document_id, "downloading")

    s3 = boto3.client("s3")
    s3.download_file(bucket, key, str(local_path))

    if existing is None:
        # No API step created this row yet - the Phase 88 direct-S3-put
        # fallback path, still useful for manual testing. Phase 89's real
        # presigned-upload endpoint always creates this row first.
        content = local_path.read_bytes()
        content_hash = compute_content_hash(content)
        await metadata_store.create_document(document_id, filename, str(local_path), len(content), content_hash)
        index_kwargs = {}
    else:
        index_kwargs = _pending_overrides_kwargs(existing)

    # Phase 100: index_document() itself now sets status to "parsing" as
    # its very first action (Phase 134 - was "chunking", mislabeled at that
    # point) - a separate status update here would be overwritten within
    # microseconds, so it's not worth a second DB write.

    try:
        await pipeline.index_document(document_id, str(local_path), **index_kwargs)
        if index_kwargs:
            await metadata_store.set_pending_overrides(document_id, None)
    except Exception as error:
        logger.error(
            "Indexing failed for document %s (bucket=%s, key=%s): %s: %s",
            document_id, bucket, key, type(error).__name__, error,
        )
        # Phase 134: the document's current status is the last stage it
        # actually reached - read it before overwriting it to "failed".
        current = await metadata_store.get_document(document_id)
        failed_stage = current["status"] if current else "unknown"
        await metadata_store.update_status(document_id, "failed", f"[{failed_stage}] {error}")
        raise


async def _process_one_record(record: dict) -> str | None:
    """One record's own download/parse/chunk/embed/index - returns its
    messageId if it failed, else None. Exceptions are caught here, not left
    to asyncio.gather() to propagate, so one bad document can't cancel the
    others' concurrent processing."""
    try:
        parsed = _parse_s3_event(record)
        if parsed is None:
            return None
        bucket, key = parsed
        await _index_one(bucket, key)
        return None
    except Exception:
        logger.error("Failed to process SQS message %s", record.get("messageId"), exc_info=True)
        return record["messageId"]


async def _process_batch(records: list[dict]) -> list[dict]:
    """Phase 145: every record in one SQS batch now processes concurrently
    via asyncio.gather() - still exactly one asyncio.run() for the whole
    batch (not per record, unchanged from before), so the Redis-client-
    outlives-the-loop issue Phase 88 found doesn't resurface; that issue
    was about multiple asyncio.run() calls, not concurrency within one.
    Chroma's PersistentClient isn't safe for concurrent writes from
    multiple threads, confirmed live (the user's own local index got
    corrupted, "Error finding id") - vector_indexer.py's own
    collection_lock (chroma_client.py, Phase 145) now serializes the
    actual chromadb calls underneath this concurrency, so the slow parts
    (download, parse, chunk, embed - real network/CPU time) genuinely run
    in parallel while the one truly unsafe resource stays serialized."""
    message_ids = await asyncio.gather(*(_process_one_record(record) for record in records))
    return [{"itemIdentifier": message_id} for message_id in message_ids if message_id is not None]


def lambda_handler(event: dict, context) -> dict:
    """One invocation may carry a batch of SQS messages. Reports per-message
    failures via batchItemFailures (AWS's documented partial-batch-failure
    pattern) so one bad document retries/DLQs without blocking the rest."""
    failures = asyncio.run(_process_batch(event.get("Records", [])))
    return {"batchItemFailures": failures}
