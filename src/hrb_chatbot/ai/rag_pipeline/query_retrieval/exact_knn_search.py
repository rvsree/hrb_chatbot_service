"""Exact KNN search strategy (Phase 218) - brute-force cosine similarity
against every current chunk's own stored embedding, no approximation/index
involved. Real, not decorative: both ChromaDB and Pinecone's get_all_chunks()
already walk the whole collection/index (BM25's own corpus source), and each
returned chunk now carries its own embedding too - this just scores them
directly instead of going through either backend's native HNSW-backed query."""

import math

from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.bm25_search import _matches_metadata_filter
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.db_client.langchain_vector_store import COLLECTION_NAME, get_vector_store
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_pipeline.exact_knn_search")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot_product = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def search_knn(query: str, top_k: int = 5, vector_db: str | None = None, extra_filter: dict | None = None) -> list[dict]:
    """Exact (not approximate) nearest-neighbor search - every current
    chunk's cosine similarity to the query is actually computed, not
    estimated by an index. Slower than similarity_search's native HNSW
    path, especially on Pinecone (a full index walk, same cost profile
    search_keyword/search_hybrid already accept there) - no relevance-bar
    filtering, same choice search_mmr already makes, since this is an
    exact ranking, not a bar-filtered one."""
    store, provider = get_vector_store(vector_db)
    query_embedding = store.embeddings.embed_query(query)

    vector_store_client = get_db_gateway().vector_store(provider=vector_db)
    all_chunks = vector_store_client.get_all_chunks(COLLECTION_NAME)
    current_chunks = [
        chunk
        for chunk in all_chunks
        if _matches_metadata_filter(chunk["metadata"], extra_filter) and chunk.get("embedding")
    ]

    scored = [
        (chunk, _cosine_similarity(query_embedding, chunk["embedding"]))
        for chunk in current_chunks
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    results = []
    for chunk, score in scored[:top_k]:
        results.append(
            {
                "document_id": chunk["metadata"].get("document_id"),
                "chunk_index": chunk["metadata"].get("chunk_index"),
                "text": chunk["text"],
                "score": score,
            }
        )
    logger.info("Exact KNN search (%s): %d chunk(s) scored, top %d returned", provider, len(current_chunks), len(results))
    return results
