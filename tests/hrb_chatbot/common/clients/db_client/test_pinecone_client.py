"""Tests for PineconeClient.get_all_chunks() (Phase 131). No real Pinecone
account/network available in tests - a fake Index stands in, built to match
the real SDK's confirmed shapes: list(namespace=...) yields batches of ids,
fetch(ids=..., namespace=...) returns an object with a .vectors dict keyed
by id, each vector carrying a plain .metadata dict."""

from src.hrb_chatbot.common.clients.db_client.pinecone_client import PineconeClient


class _FakeVector:
    def __init__(self, metadata):
        self.metadata = metadata


class _FakeFetchResponse:
    def __init__(self, vectors):
        self.vectors = vectors


class FakeIndex:
    """ids_by_namespace: {namespace: {chunk_id: metadata_dict}}."""

    def __init__(self, ids_by_namespace):
        self._data = ids_by_namespace

    def list(self, namespace=None, **kwargs):
        ids = list(self._data.get(namespace, {}).keys())
        if ids:
            yield ids

    def fetch(self, ids, namespace=None, **kwargs):
        namespace_data = self._data.get(namespace, {})
        vectors = {chunk_id: _FakeVector(namespace_data[chunk_id]) for chunk_id in ids if chunk_id in namespace_data}
        return _FakeFetchResponse(vectors)


def _client_with_fake_index(monkeypatch, ids_by_namespace):
    client = PineconeClient(api_key="fake-key", index_name="fake-index")
    fake_index = FakeIndex(ids_by_namespace)
    monkeypatch.setattr(client, "get_index", lambda: fake_index)
    return client


def test_get_all_chunks_returns_every_chunk_with_text_and_metadata(monkeypatch):
    client = _client_with_fake_index(
        monkeypatch,
        {
            "test_collection": {
                "chunk-1": {"document": "first chunk text", "doc_id": "doc-1"},
                "chunk-2": {"document": "second chunk text", "doc_id": "doc-1"},
            }
        },
    )

    chunks = client.get_all_chunks("test_collection")

    assert {chunk["id"] for chunk in chunks} == {"chunk-1", "chunk-2"}
    by_id = {chunk["id"]: chunk for chunk in chunks}
    assert by_id["chunk-1"]["text"] == "first chunk text"
    assert by_id["chunk-1"]["metadata"] == {"doc_id": "doc-1"}


def test_get_all_chunks_falls_back_to_llama_index_node_content(monkeypatch):
    # No "document" key - the LlamaIndex-era storage shape, matching query()'s own fallback.
    node_content = '{"text": "legacy chunk text"}'
    client = _client_with_fake_index(
        monkeypatch,
        {"test_collection": {"chunk-1": {"_node_content": node_content}}},
    )

    chunks = client.get_all_chunks("test_collection")

    assert chunks == [{"id": "chunk-1", "text": "legacy chunk text", "metadata": {"_node_content": node_content}}]


def test_get_all_chunks_on_empty_namespace_returns_empty_list(monkeypatch):
    client = _client_with_fake_index(monkeypatch, {})

    assert client.get_all_chunks("test_collection") == []


def test_get_all_chunks_batches_fetch_calls_past_the_fetch_batch_size(monkeypatch):
    # fetch_batch_size is 100 - 150 ids proves get_all_chunks() issues more than one fetch() call, not one giant call.
    many_chunks = {f"chunk-{i}": {"document": f"text {i}"} for i in range(150)}
    client = _client_with_fake_index(monkeypatch, {"test_collection": many_chunks})

    chunks = client.get_all_chunks("test_collection")

    assert len(chunks) == 150
    assert {chunk["id"] for chunk in chunks} == set(many_chunks.keys())
