"""Tests for the granular indexing status (Phase 100, refined Phase 134) -
index_document() itself sets "parsing" -> "chunking" -> "embedding" ->
"indexing" before write_chunks() (faked here) would set "indexed". Every
heavy dependency (PDF extraction, chunking, embedding, vector write) is
faked - no real network call, matching every other test in this project."""

from src.hrb_chatbot.ai.doc_processing import pipeline


class _RecordingMetadataStore:
    """Records every update_status() call, in order - not just the final
    value, since that's what this phase's actual claim (chunking happens
    before embedding) needs to prove."""

    def __init__(self):
        self.status_history: list[str] = []

    async def update_status(self, document_id, status, error_message=None):
        self.status_history.append(status)


class _RecordingDBGateway:
    def __init__(self, metadata_store):
        self._metadata_store = metadata_store

    def metadata_store(self):
        return self._metadata_store


def _patch_pipeline_dependencies(monkeypatch, metadata_store):
    monkeypatch.setattr(pipeline, "get_db_gateway", lambda: _RecordingDBGateway(metadata_store))
    monkeypatch.setattr(pipeline, "extract_text_from_pdf", lambda file_path: "some extracted policy text")
    monkeypatch.setattr(pipeline, "decide_chunking_strategy", lambda text: "recursive")
    monkeypatch.setattr(pipeline, "decide_chunk_size", lambda text: 800)
    monkeypatch.setattr(pipeline, "chunk_document", lambda text, **kwargs: ["chunk one", "chunk two"])

    async def _fake_generate_embeddings(chunks, embedding_model=None):
        return [[0.1, 0.2], [0.3, 0.4]]

    monkeypatch.setattr(pipeline, "generate_embeddings", _fake_generate_embeddings)

    async def _fake_write_chunks(document_id, chunks, embeddings, **kwargs):
        # The real write_chunks()/record_successful_index() sets status to
        # "indexed" - out of scope here, this test is only about the two
        # new states that happen before this point.
        return {"action": "insert", "chunks_indexed": len(chunks), "chunks_removed": 0, "chunk_ids": ["c1", "c2"]}

    monkeypatch.setattr(pipeline, "write_chunks", _fake_write_chunks)
    monkeypatch.setattr(pipeline, "extract_document_metadata", lambda text: dict(pipeline.EMPTY_RESULT))

    async def _fake_record_document_metadata(document_id, **kwargs):
        return None

    async def _fake_apply_extracted_chunk_metadata(document_id, chunk_ids, vector_db, **kwargs):
        return None

    monkeypatch.setattr(pipeline, "apply_extracted_chunk_metadata", _fake_apply_extracted_chunk_metadata)
    metadata_store.record_document_metadata = _fake_record_document_metadata


async def test_parsing_chunking_embedding_indexing_are_set_in_order(monkeypatch):
    metadata_store = _RecordingMetadataStore()
    _patch_pipeline_dependencies(monkeypatch, metadata_store)

    await pipeline.index_document("doc-123", "data/uploads/doc-123/policy.pdf")

    assert metadata_store.status_history == ["parsing", "chunking", "embedding", "indexing"]
