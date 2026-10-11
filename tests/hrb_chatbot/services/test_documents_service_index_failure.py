"""Phase 134 - a failed index attempt's error_message is prefixed with the
real stage it failed at (the document's own status right before it gets
overwritten to "failed"), not just the bare exception text. Covers
documents_service._index_now() only - the one place both the synchronous
upload path and reindex/rechunk all funnel through."""

from src.hrb_chatbot.services import documents_service
from tests.conftest import FakeDBGateway, FakeMetadataStore


async def test_failure_message_is_prefixed_with_the_stage_it_failed_at(monkeypatch):
    metadata_store = FakeMetadataStore()
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    await metadata_store.update_status("doc-1", "embedding")  # the stage reached before the failure

    gateway = FakeDBGateway(metadata_store=metadata_store)
    monkeypatch.setattr(documents_service, "get_db_gateway", lambda: gateway)

    async def _failing_index_document(document_id, file_path, **kwargs):
        raise ValueError("could not reach pinecone")

    monkeypatch.setattr(documents_service.pipeline, "index_document", _failing_index_document)

    result = await documents_service._index_now("doc-1", "data/uploads/doc-1/policy.pdf")

    assert result["error_code"] == documents_service.error_codes.INDEXING_FAILED
    assert metadata_store.documents["doc-1"]["status"] == "failed"
    assert metadata_store.documents["doc-1"]["error_message"] == "[embedding] could not reach pinecone"


async def test_failure_message_names_unknown_stage_if_the_document_row_is_gone(monkeypatch):
    # Edge case: the row was deleted out from under an in-flight index
    # attempt - must not crash building the stage-tagged message.
    metadata_store = FakeMetadataStore()
    gateway = FakeDBGateway(metadata_store=metadata_store)
    monkeypatch.setattr(documents_service, "get_db_gateway", lambda: gateway)

    async def _failing_index_document(document_id, file_path, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(documents_service.pipeline, "index_document", _failing_index_document)

    result = await documents_service._index_now("doc-missing", "data/uploads/doc-missing/policy.pdf")

    assert result["error_code"] == documents_service.error_codes.INDEXING_FAILED
