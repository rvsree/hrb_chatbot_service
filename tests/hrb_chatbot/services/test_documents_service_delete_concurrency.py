"""Phase 139: delete_document() used to call vector_store.delete() and
delete_uploaded_object() as plain blocking calls inside an async function -
each one serialized a whole batch of otherwise-concurrent delete requests on
the shared asyncio event loop. This proves the asyncio.to_thread() fix
actually unblocks the loop (real elapsed-time assertion), not just that the
code still runs."""

import asyncio
import json
import time

from src.hrb_chatbot.services import documents_service

BLOCKING_DELAY_SECONDS = 0.2


class _FakeMetadataStore:
    def __init__(self, documents: dict[str, dict]):
        self._documents = documents

    async def get_document(self, document_id):
        return self._documents.get(document_id)

    async def delete_document(self, document_id):
        self._documents.pop(document_id, None)


class _FakeVectorStore:
    PROVIDER_NAME = "chromadb"

    def delete(self, collection_name, ids):
        # A real SDK call (Pinecone/Chroma) is a blocking network round-trip -
        # time.sleep (not asyncio.sleep) simulates that honestly, since an
        # un-wrapped blocking call is exactly the bug being fixed here.
        time.sleep(BLOCKING_DELAY_SECONDS)


class _FakeGateway:
    def __init__(self, documents: dict[str, dict]):
        self._metadata_store = _FakeMetadataStore(documents)
        self._vector_store = _FakeVectorStore()

    def metadata_store(self, provider=None):
        return self._metadata_store

    def vector_store(self, provider=None):
        return self._vector_store


def _make_documents(count: int) -> dict[str, dict]:
    return {
        f"doc-{i}": {
            "filename": f"doc-{i}.pdf",
            "chunk_ids": json.dumps(["chunk-1"]),
            "vector_db": "chromadb",
        }
        for i in range(count)
    }


async def test_concurrent_deletes_run_in_parallel_not_serially(monkeypatch):
    documents = _make_documents(5)
    monkeypatch.setattr(documents_service, "get_db_gateway", lambda: _FakeGateway(documents))
    monkeypatch.setattr(documents_service, "_delete_s3_object_best_effort", lambda document_id, filename: time.sleep(BLOCKING_DELAY_SECONDS))

    async def _noop_cache_clear():
        return None

    monkeypatch.setattr(documents_service, "_clear_answer_cache_best_effort", _noop_cache_clear)

    started_at = time.perf_counter()
    await asyncio.gather(*(documents_service.delete_document(doc_id) for doc_id in list(documents.keys())))
    elapsed = time.perf_counter() - started_at

    # Serial would be 5 docs * 2 blocking calls * 0.2s = 2.0s. Running the
    # blocking calls in threads via asyncio.to_thread keeps this well under
    # that - a generous bound (not the tightest possible) to stay reliable
    # under CI load, while still catching a regression back to serial.
    assert elapsed < 1.0, f"deletes took {elapsed:.2f}s - looks serial, not concurrent"
    assert documents == {}
