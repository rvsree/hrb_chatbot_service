"""Tests for search_knn() (Phase 218,
ai/rag_pipeline/query_retrieval/exact_knn_search.py) - real cosine math
against a real, ephemeral (in-memory, zero network) chromadb collection and
conftest.py's FakeEmbeddings, same no-real-API-cost approach test_retriever.py
and test_bm25_search.py both already use."""

import uuid

import chromadb
from langchain_chroma import Chroma

from src.hrb_chatbot.ai.rag_pipeline.query_retrieval import exact_knn_search
from tests.conftest import FakeDBGateway, FakeEmbeddings, FakeMetadataStore


class FakeVectorStoreClient:
    """Stands in for ChromaDBClient - real, ephemeral chromadb, same as
    test_retriever.py's own, but with "embeddings" in the include list
    (Phase 218's own addition to the real client's get_all_chunks())."""

    PROVIDER_NAME = "chromadb"

    def __init__(self):
        self._client = chromadb.EphemeralClient()

    def get_client(self):
        return self._client

    def get_all_chunks(self, collection_name: str) -> list[dict]:
        result = self._client.get_or_create_collection(collection_name).get(
            include=["documents", "metadatas", "embeddings"]
        )
        embeddings = result.get("embeddings")
        return [
            {
                "id": chunk_id,
                "text": document or "",
                "metadata": metadata or {},
                "embedding": list(embeddings[index]) if embeddings is not None else None,
            }
            for index, (chunk_id, document, metadata) in enumerate(
                zip(result["ids"], result["documents"], result["metadatas"], strict=True)
            )
        ]


def _seed_collection(vector_store_client, collection_name: str, chunks: list[dict]) -> None:
    collection = vector_store_client.get_client().get_or_create_collection(collection_name)
    collection.add(
        ids=[chunk["id"] for chunk in chunks],
        embeddings=[chunk["embedding"] for chunk in chunks],
        documents=[chunk["text"] for chunk in chunks],
        metadatas=[chunk["metadata"] for chunk in chunks],
    )


def _setup(monkeypatch):
    collection_name = f"test_{uuid.uuid4().hex}"
    vector_store_client = FakeVectorStoreClient()
    metadata_store = FakeMetadataStore()
    gateway = FakeDBGateway(vector_store=vector_store_client, metadata_store=metadata_store)
    monkeypatch.setattr(exact_knn_search, "get_db_gateway", lambda: gateway)
    monkeypatch.setattr(exact_knn_search, "COLLECTION_NAME", collection_name)

    embeddings = FakeEmbeddings()
    langchain_store = Chroma(
        client=vector_store_client.get_client(), collection_name=collection_name, embedding_function=embeddings
    )
    monkeypatch.setattr(
        exact_knn_search, "get_vector_store", lambda vector_db, embedding_model=None: (langchain_store, "chromadb")
    )

    return collection_name, vector_store_client, embeddings


def test_exact_match_ranks_first_even_against_a_closer_approximate_neighbor(monkeypatch):
    # The whole point of exact KNN: real cosine math, computed directly -
    # not an index's approximation of it.
    collection_name, vector_store_client, embeddings = _setup(monkeypatch)
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-1:0",
                "text": "Parental leave is 16 weeks.",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-1", "chunk_index": 0, "is_current": True},
            },
            {
                "id": "doc-2:0",
                "text": "Unrelated cafeteria menu text.",
                "embedding": [0.0, 1.0],
                "metadata": {"document_id": "doc-2", "chunk_index": 0, "is_current": True},
            },
        ],
    )
    embeddings.register("How much parental leave?", [1.0, 0.0])

    results = exact_knn_search.search_knn("How much parental leave?", top_k=5)

    assert len(results) == 2
    assert results[0]["document_id"] == "doc-1"
    assert results[0]["score"] > results[1]["score"]
    # Perfect cosine match (identical vectors) - score is exactly 1.0, not
    # an HNSW-approximated distance.
    assert results[0]["score"] == 1.0


def test_excludes_superseded_chunks(monkeypatch):
    collection_name, vector_store_client, embeddings = _setup(monkeypatch)
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-old:0",
                "text": "stale text",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-old", "chunk_index": 0, "is_current": False},
            },
            {
                "id": "doc-new:0",
                "text": "current text",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-new", "chunk_index": 0, "is_current": True},
            },
        ],
    )
    embeddings.register("query", [1.0, 0.0])

    results = exact_knn_search.search_knn("query", top_k=5)

    assert len(results) == 1
    assert results[0]["document_id"] == "doc-new"


def test_respects_top_k(monkeypatch):
    collection_name, vector_store_client, embeddings = _setup(monkeypatch)
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": f"doc-{i}:0",
                "text": f"chunk {i}",
                "embedding": [1.0, float(i)],
                "metadata": {"document_id": f"doc-{i}", "chunk_index": 0, "is_current": True},
            }
            for i in range(5)
        ],
    )
    embeddings.register("query", [1.0, 0.0])

    results = exact_knn_search.search_knn("query", top_k=2)

    assert len(results) == 2
