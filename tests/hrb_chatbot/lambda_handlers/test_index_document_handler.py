"""Tests for the Lambda handler (RAG-ROADMAP.md Phase 88) - a thin adapter
over pipeline.index_document(), so these cover the adapter logic only
(parsing the SQS/S3 event, creating a missing metadata row, status
transitions, batchItemFailures reporting) - no real AWS call, matching
this project's existing fake-based test convention."""

import asyncio
import json
import logging
import sys

from src.hrb_chatbot.lambda_handlers import index_document_handler
from tests.conftest import FakeDBGateway, FakeMetadataStore


class _FakeS3Client:
    """Stands in for boto3's S3 client - download_file() writes fixed bytes
    to the given local path instead of making a real network call."""

    def __init__(self, content: bytes = b"%PDF-1.4 fake content"):
        self.content = content
        self.downloaded = []

    def download_file(self, bucket, key, local_path):
        self.downloaded.append((bucket, key, local_path))
        with open(local_path, "wb") as f:
            f.write(self.content)


def _s3_event_sqs_record(bucket: str, key: str, message_id: str = "msg-1") -> dict:
    """One SQS message carrying an S3 ObjectCreated event notification body -
    the real shape S3 -> SQS delivers, per Phase 88's spec."""
    body = {"Records": [{"s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]}
    return {"messageId": message_id, "body": json.dumps(body)}


def _wire_fakes(monkeypatch, metadata_store=None, s3_client=None, index_document=None):
    gateway = FakeDBGateway(metadata_store=metadata_store or FakeMetadataStore())
    monkeypatch.setattr(index_document_handler, "get_db_gateway", lambda: gateway)
    monkeypatch.setattr(index_document_handler.boto3, "client", lambda service: s3_client or _FakeS3Client())

    async def _default_index_document(document_id, file_path, **kwargs):
        return {"action": "insert", "chunks_indexed": 1, "chunks_removed": 0}

    monkeypatch.setattr(index_document_handler.pipeline, "index_document", index_document or _default_index_document)
    return gateway


def test_indexes_a_new_document_and_creates_its_metadata_row(monkeypatch):
    gateway = _wire_fakes(monkeypatch)
    event = {"Records": [_s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-123/policy.pdf")]}

    result = index_document_handler.lambda_handler(event, context=None)

    assert result == {"batchItemFailures": []}
    document = gateway.metadata_store().documents["doc-123"]
    assert document["filename"] == "policy.pdf"


def test_pending_overrides_from_the_presigned_upload_route_are_passed_through_and_cleared(monkeypatch):
    # Phase 89: the presigned-upload route already created this row with
    # chunk_info/document_metadata stashed - the handler must pass them to
    # index_document() and clear the column afterward, not just ignore them.
    metadata_store = FakeMetadataStore()
    metadata_store.documents["doc-123"] = {
        "id": "doc-123",
        "filename": "policy.pdf",
        "status": "pending_upload",
        "pending_overrides": json.dumps({
            "chunk_info": {"chunking_strategy": "recursive", "chunk_size": 800, "chunk_overlap": 100},
            "document_metadata": {"doc_category": "benefits"},
        }),
    }
    captured_kwargs = {}

    async def _capturing_index_document(document_id, file_path, **kwargs):
        captured_kwargs.update(kwargs)
        return {"action": "insert", "chunks_indexed": 1, "chunks_removed": 0}

    gateway = _wire_fakes(monkeypatch, metadata_store=metadata_store, index_document=_capturing_index_document)
    event = {"Records": [_s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-123/policy.pdf")]}

    result = index_document_handler.lambda_handler(event, context=None)

    assert result == {"batchItemFailures": []}
    assert captured_kwargs["chunking_strategy"] == "recursive"
    assert captured_kwargs["chunk_size"] == 800
    assert captured_kwargs["chunk_overlap"] == 100
    assert captured_kwargs["document_metadata_override"] == {"doc_category": "benefits"}
    assert gateway.metadata_store().documents["doc-123"]["pending_overrides"] is None


def test_existing_document_is_not_recreated_idempotency(monkeypatch):
    metadata_store = FakeMetadataStore()
    metadata_store.documents["doc-123"] = {"id": "doc-123", "filename": "policy.pdf", "status": "uploaded"}
    gateway = _wire_fakes(monkeypatch, metadata_store=metadata_store)
    event = {"Records": [_s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-123/policy.pdf")]}

    result = index_document_handler.lambda_handler(event, context=None)

    assert result == {"batchItemFailures": []}
    # Phase 103: the handler itself now sets "downloading" for an existing
    # row, before the S3 download - the rest of the progression
    # (chunking/embedding/indexed) lives inside the real index_document(),
    # faked out here, so it never fires past this point.
    assert gateway.metadata_store().documents["doc-123"]["status"] == "downloading"


def test_indexing_failure_marks_the_document_failed_and_reports_batch_item_failure(monkeypatch):
    async def _failing_index_document(document_id, file_path, **kwargs):
        raise ValueError("could not reach pinecone")

    gateway = _wire_fakes(monkeypatch, index_document=_failing_index_document)
    event = {"Records": [_s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-456/benefits.pdf", message_id="msg-2")]}

    result = index_document_handler.lambda_handler(event, context=None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-2"}]}
    document = gateway.metadata_store().documents["doc-456"]
    assert document["status"] == "failed"
    assert "could not reach pinecone" in document["error_message"]


def test_indexing_failure_prefixes_the_stage_it_actually_failed_at(monkeypatch):
    # Phase 134 - the stage comes from the document's own real, live status
    # right before the overwrite, not a guess or a stale pre-set value:
    # _index_one() itself sets "downloading" for an existing row before
    # calling index_document() - faking index_document() to fail
    # immediately means "downloading" is the real last-reached stage here.
    metadata_store = FakeMetadataStore()
    metadata_store.documents["doc-789"] = {"id": "doc-789", "filename": "policy.pdf", "status": "uploaded"}

    async def _failing_index_document(document_id, file_path, **kwargs):
        raise ValueError("could not reach pinecone")

    gateway = _wire_fakes(monkeypatch, metadata_store=metadata_store, index_document=_failing_index_document)
    event = {"Records": [_s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-789/policy.pdf", message_id="msg-3")]}

    index_document_handler.lambda_handler(event, context=None)

    document = gateway.metadata_store().documents["doc-789"]
    assert document["error_message"] == "[downloading] could not reach pinecone"


def test_s3_test_event_is_skipped_not_treated_as_a_failure(monkeypatch):
    _wire_fakes(monkeypatch)
    test_event_body = {"Event": "s3:TestEvent"}
    record = {"messageId": "msg-3", "body": json.dumps(test_event_body)}

    result = index_document_handler.lambda_handler({"Records": [record]}, context=None)

    assert result == {"batchItemFailures": []}


def test_a_batch_of_several_records_runs_on_one_shared_event_loop(monkeypatch):
    # Regression for a real bug found during Phase 88's live concurrency
    # test: calling asyncio.run() once PER record closes the loop a
    # long-lived async resource (the Redis embedding cache's cached
    # client) was created on, raising "Event loop is closed" starting on
    # the second record. This fake raises that same way if it's ever
    # called from a different running loop than the one it first saw.
    seen_loop = {}

    async def _index_document(document_id, file_path, **kwargs):
        current_loop = asyncio.get_running_loop()
        if "loop" not in seen_loop:
            seen_loop["loop"] = current_loop
        elif seen_loop["loop"] is not current_loop:
            raise RuntimeError("Event loop is closed")
        return {"action": "insert", "chunks_indexed": 1, "chunks_removed": 0}

    _wire_fakes(monkeypatch, index_document=_index_document)
    event = {
        "Records": [
            _s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-1/a.pdf", message_id="msg-1"),
            _s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-2/b.pdf", message_id="msg-2"),
            _s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-3/c.pdf", message_id="msg-3"),
        ]
    }

    result = index_document_handler.lambda_handler(event, context=None)

    assert result == {"batchItemFailures": []}


def test_a_batch_of_several_records_actually_processes_concurrently(monkeypatch):
    """Phase 145 - the real, user-reported symptom: documents in one batch
    used to process strictly one at a time (a plain for loop, each record
    awaited before the next started). Proves real concurrency, not just
    that the old sequential test still passes: each fake _index_one sleeps
    briefly and records when it started: if they're concurrent, all 3
    start within a narrow window; if still sequential, each one's start
    time would trail the previous one's full sleep duration."""
    start_times = []

    async def _index_document(document_id, file_path, **kwargs):
        start_times.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.2)
        return {"action": "insert", "chunks_indexed": 1, "chunks_removed": 0}

    _wire_fakes(monkeypatch, index_document=_index_document)
    event = {
        "Records": [
            _s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-1/a.pdf", message_id="msg-1"),
            _s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-2/b.pdf", message_id="msg-2"),
            _s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-3/c.pdf", message_id="msg-3"),
        ]
    }

    index_document_handler.lambda_handler(event, context=None)

    assert len(start_times) == 3
    # Sequential would spread these ~0.2s apart each (~0.4s total spread);
    # concurrent keeps them within a tight window since all 3 start before
    # any of them finishes sleeping.
    assert max(start_times) - min(start_times) < 0.1


# --- Phase 133: the JSON log formatter was silently dropping real tracebacks ---


def test_json_formatter_includes_the_traceback_when_exc_info_is_set():
    formatter = index_document_handler._JsonFormatter()
    try:
        raise ValueError("could not reach pinecone")
    except ValueError:
        record = logging.LogRecord(
            name="lambda_handlers.index_document", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="Failed to process SQS message msg-1", args=(), exc_info=sys.exc_info(),
        )

    payload = json.loads(formatter.format(record))

    assert "could not reach pinecone" in payload["exception"]
    assert "Traceback" in payload["exception"]


def test_json_formatter_omits_exception_key_when_there_is_no_error():
    formatter = index_document_handler._JsonFormatter()
    record = logging.LogRecord(
        name="lambda_handlers.index_document", level=logging.INFO, pathname=__file__, lineno=1,
        msg="Polling for messages", args=(), exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert "exception" not in payload


# --- Phase 133: a real filename with a space, URL-encoded by S3's own event notification ---


def test_a_url_encoded_key_with_spaces_decodes_to_the_real_filename(monkeypatch):
    # S3's ObjectCreated notification encodes a space as "+" - confirmed
    # live against a real bucket before this fix (download with the raw
    # encoded key 404'd, the decoded key succeeded). "Fake content" is
    # written here under the DECODED local path - a test proving the
    # handler actually calls download_file() with the decoded key, not
    # the still-encoded one.
    s3_client = _FakeS3Client()
    gateway = _wire_fakes(monkeypatch, s3_client=s3_client)
    encoded_key = "doc-789/Global+Data+Privacy+Statement_FY27.pdf"
    event = {"Records": [_s3_event_sqs_record("hrb-chatbot-kb-uploads", encoded_key)]}

    result = index_document_handler.lambda_handler(event, context=None)

    assert result == {"batchItemFailures": []}
    downloaded_bucket, downloaded_key, _ = s3_client.downloaded[0]
    assert downloaded_key == "doc-789/Global Data Privacy Statement_FY27.pdf"
    document = gateway.metadata_store().documents["doc-789"]
    assert document["filename"] == "Global Data Privacy Statement_FY27.pdf"


def test_percent_encoded_characters_in_the_key_are_also_decoded(monkeypatch):
    s3_client = _FakeS3Client()
    _wire_fakes(monkeypatch, s3_client=s3_client)
    # "(1)" URL-encoded - parentheses are percent-encoded by S3's own notification.
    encoded_key = "doc-999/FDE+Pulse+%281%29.pdf"
    event = {"Records": [_s3_event_sqs_record("hrb-chatbot-kb-uploads", encoded_key)]}

    index_document_handler.lambda_handler(event, context=None)

    _, downloaded_key, _ = s3_client.downloaded[0]
    assert downloaded_key == "doc-999/FDE Pulse (1).pdf"


def test_one_bad_message_in_a_batch_does_not_block_the_others(monkeypatch):
    async def _index_document(document_id, file_path, **kwargs):
        if document_id == "doc-bad":
            raise ValueError("boom")
        return {"action": "insert", "chunks_indexed": 1, "chunks_removed": 0}

    gateway = _wire_fakes(monkeypatch, index_document=_index_document)
    event = {
        "Records": [
            _s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-good/a.pdf", message_id="msg-good"),
            _s3_event_sqs_record("hrb-chatbot-kb-uploads", "doc-bad/b.pdf", message_id="msg-bad"),
        ]
    }

    result = index_document_handler.lambda_handler(event, context=None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "msg-bad"}]}
    assert gateway.metadata_store().documents["doc-good"]["filename"] == "a.pdf"
    assert gateway.metadata_store().documents["doc-bad"]["status"] == "failed"
