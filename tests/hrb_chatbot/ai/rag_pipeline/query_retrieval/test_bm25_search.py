"""Tests for search_keyword()/search_hybrid() (Phase 131,
ai/rag_pipeline/query_retrieval/bm25_search.py).

Same real-ephemeral-chromadb-no-network approach as test_retriever.py.
bm25_search.py reads the whole corpus via get_all_chunks() against a fixed
module-level COLLECTION_NAME (matches production - every provider writes
into one shared collection, see langchain_vector_store.py) - monkeypatched
per-test to a random name here so tests stay isolated from each other,
same reasoning test_vector_indexer.py's own EphemeralChromaVectorStore
comment gives for why a plain fresh EphemeralClient() isn't isolation
enough on its own."""

import uuid

import chromadb

from src.hrb_chatbot.ai.rag_pipeline.query_retrieval import bm25_search, retriever
from tests.conftest import FakeDBGateway, FakeEmbeddings, FakeMetadataStore


class FakeVectorStoreClient:
    """Stands in for ChromaDBClient - real, ephemeral chromadb, same as test_retriever.py's own."""

    PROVIDER_NAME = "chromadb"

    def __init__(self):
        self._client = chromadb.EphemeralClient()

    def get_client(self):
        return self._client

    def get_all_chunks(self, collection_name: str) -> list[dict]:
        result = self._client.get_or_create_collection(collection_name).get(include=["documents", "metadatas"])
        return [
            {"id": chunk_id, "text": document or "", "metadata": metadata or {}}
            for chunk_id, document, metadata in zip(result["ids"], result["documents"], result["metadatas"], strict=True)
        ]


# BM25's idf formula degenerates to exactly 0 for a term that appears in
# precisely half of a 2-document corpus (log(N-freq+0.5) - log(freq+0.5),
# N=2, freq=1 -> log(1.5)-log(1.5)) - confirmed directly against rank_bm25's
# real _calc_idf() before writing these tests, not assumed. These filler
# chunks pad every test corpus past that degenerate case.
_FILLER_CHUNKS = [
    {
        "id": "filler-1:0",
        "text": "Office parking permits renew every January at the front desk.",
        "embedding": [9.0, 9.0],  # far from any registered query embedding - excluded by the vector relevance bar too
        "metadata": {"document_id": "filler-1", "chunk_index": 0, "is_current": True},
    },
    {
        "id": "filler-2:0",
        "text": "The cafeteria menu rotates weekly and posts on the intranet.",
        "embedding": [9.0, 9.0],
        "metadata": {"document_id": "filler-2", "chunk_index": 0, "is_current": True},
    },
    {
        "id": "filler-3:0",
        "text": "Badge access requests go through facilities, not IT support.",
        "embedding": [9.0, 9.0],
        "metadata": {"document_id": "filler-3", "chunk_index": 0, "is_current": True},
    },
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
    """Patches bm25_search's own COLLECTION_NAME (for search_keyword's direct
    get_all_chunks() call) and retriever.get_vector_store (for search_hybrid's
    nested search_similarity() call) to the same isolated, random collection."""
    from langchain_chroma import Chroma

    collection_name = f"test_{uuid.uuid4().hex}"
    vector_store_client = FakeVectorStoreClient()
    metadata_store = FakeMetadataStore()
    gateway = FakeDBGateway(vector_store=vector_store_client, metadata_store=metadata_store)
    monkeypatch.setattr(bm25_search, "get_db_gateway", lambda: gateway)
    monkeypatch.setattr(bm25_search, "COLLECTION_NAME", collection_name)

    embeddings = FakeEmbeddings()
    langchain_store = Chroma(
        client=vector_store_client.get_client(), collection_name=collection_name, embedding_function=embeddings
    )
    monkeypatch.setattr(
        retriever, "get_vector_store", lambda vector_db, embedding_model=None: (langchain_store, "chromadb")
    )

    return collection_name, vector_store_client, metadata_store, embeddings


def test_search_keyword_returns_chunks_matching_query_terms(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-1:0",
                "text": "The 401k vesting schedule is five years for employer contributions.",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-1", "chunk_index": 0, "is_current": True},
            },
            {
                "id": "doc-2:0",
                "text": "Employees accrue fifteen days of paid time off per year.",
                "embedding": [0.0, 1.0],
                "metadata": {"document_id": "doc-2", "chunk_index": 0, "is_current": True},
            },
            *_FILLER_CHUNKS,
        ],
    )

    chunks = bm25_search.search_keyword("vesting schedule 401k", top_k=5)

    assert len(chunks) == 1
    assert chunks[0]["document_id"] == "doc-1"
    assert chunks[0]["score"] > 0


def test_search_keyword_excludes_superseded_chunks(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-old:0",
                "text": "stale vesting schedule text",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-old", "chunk_index": 0, "is_current": False},
            },
            {
                "id": "doc-new:0",
                "text": "current vesting schedule text",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-new", "chunk_index": 0, "is_current": True},
            },
            *_FILLER_CHUNKS,
        ],
    )

    chunks = bm25_search.search_keyword("vesting schedule", top_k=5)

    document_ids = [chunk["document_id"] for chunk in chunks]
    assert "doc-new" in document_ids
    assert "doc-old" not in document_ids


def test_search_keyword_drops_chunks_with_zero_term_overlap(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-1:0",
                "text": "completely unrelated sentence about office supplies",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-1", "chunk_index": 0, "is_current": True},
            }
        ],
    )

    chunks = bm25_search.search_keyword("401k vesting schedule", top_k=5)

    assert chunks == []


def test_search_keyword_on_empty_collection_returns_empty_list(monkeypatch):
    _setup(monkeypatch)

    assert bm25_search.search_keyword("any question", top_k=5) == []


async def test_search_hybrid_merges_keyword_and_vector_results(monkeypatch):
    """A chunk that only a lexical match would find (no vector-embedding
    overlap registered) and a chunk that only the vector search would find
    (no lexical term overlap) must both come back - proof the two result
    sets are actually fused, not one silently winning."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-lexical:0",
                "text": "401k vesting schedule is five years",
                "embedding": [0.0, 1.0],  # deliberately far from the query's registered embedding
                "metadata": {"document_id": "doc-lexical", "chunk_index": 0, "is_current": True},
            },
            {
                "id": "doc-semantic:0",
                "text": "completely different wording with no shared terms",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-semantic", "chunk_index": 0, "is_current": True},
            },
            *_FILLER_CHUNKS,
        ],
    )
    # The query's own embedding is registered to match doc-semantic's vector
    # exactly - the vector half of the hybrid search should find it purely
    # on that, with zero shared lexical terms.
    embeddings.register("401k vesting schedule", [1.0, 0.0])

    chunks = bm25_search.search_hybrid("401k vesting schedule", top_k=5)

    document_ids = {chunk["document_id"] for chunk in chunks}
    assert document_ids == {"doc-lexical", "doc-semantic"}


async def test_search_hybrid_via_retrieve_chunks(monkeypatch):
    """search_hybrid is also reachable through retrieve_chunks()'s own
    SEARCH_STRATEGIES dispatch, same as every other strategy."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    monkeypatch.setattr(retriever, "get_db_gateway", lambda: FakeDBGateway(vector_store=vector_store_client, metadata_store=metadata_store))
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-1:0",
                "text": "401k vesting schedule is five years",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-1", "chunk_index": 0, "is_current": True},
            }
        ],
    )
    embeddings.register("401k vesting schedule", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("401k vesting schedule", top_k=5, search_strategy="hybrid")

    assert len(chunks) == 1
    assert chunks[0]["document_id"] == "doc-1"
    assert chunks[0]["filename"] == "policy.pdf"
