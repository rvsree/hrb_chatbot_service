"""Keyword (BM25) and Hybrid (BM25 + vector, Reciprocal Rank Fusion) search
strategies - Module 4's own techniques, layered on top of search_similarity()'s
existing vector path. BM25 needs the full corpus text, which only
get_all_chunks() (Phase 131) provides - rank_bm25 is the workshop's own
course library, not a hand-rolled scorer."""

from rank_bm25 import BM25Okapi

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.db_client.langchain_vector_store import COLLECTION_NAME
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_pipeline.bm25_search")

# Standard RRF constant - dampens the influence of any single very-high rank, same value used almost everywhere RRF is described.
RRF_K = 60


def _matches_filter_clause(metadata: dict, clause: dict | None) -> bool:
    """Phase 231 - recurses into "$and" (a list of sub-clauses, each ANDed)
    and understands "$nin" (list membership) in addition to the existing
    flat-equality/"$ne" support - needed because retriever.py can now
    combine Self-Query's own filter with the ACL deny-list filter as
    {"$and": [<self-query clause>, {"document_id": {"$nin": [...]}}]}.

    Note: a "$eq"-wrapped equality clause (the shape Self-Query's own
    translators actually produce, e.g. {"doc_category": {"$eq": "x"}}) is
    NOT handled here either - a pre-existing gap found while adding this,
    not introduced by it (falls through to the "elif actual != condition"
    branch below, comparing a plain value to a dict, which can never
    match) - flagged in BACKLOG.md, not fixed here: out of this phase's
    scope, and doesn't affect ACL's own correctness, since the "$nin"
    clause this phase adds is always a sibling of any self-query clause
    under "$and", never nested inside one."""
    if not clause:
        return True
    if "$and" in clause:
        return all(_matches_filter_clause(metadata, sub_clause) for sub_clause in clause["$and"])
    for key, condition in clause.items():
        actual = metadata.get(key)
        if isinstance(condition, dict):
            if "$ne" in condition and actual == condition["$ne"]:
                return False
            if "$nin" in condition and actual in condition["$nin"]:
                return False
        elif actual != condition:
            return False
    return True


def _matches_metadata_filter(metadata: dict, extra_filter: dict | None) -> bool:
    """is_current is always enforced here, independent of extra_filter - same
    rule search_similarity()/search_mmr() apply via CURRENT_CHUNKS_ONLY, just
    checked directly against raw metadata instead of a vector-store `where`
    clause."""
    if metadata.get("is_current") is False:
        return False
    return _matches_filter_clause(metadata, extra_filter)


def search_keyword(query: str, top_k: int = 5, vector_db: str | None = None, extra_filter: dict | None = None) -> list[dict]:
    """Plain BM25 lexical ranking over every current chunk - good for exact
    terms/acronyms vector similarity can miss. No relevance-bar concept like
    the vector strategies have; a BM25 score of 0 means no term overlap at
    all, so those are dropped instead of padding out top_k with noise."""
    vector_store_client = get_db_gateway().vector_store(provider=vector_db)
    all_chunks = vector_store_client.get_all_chunks(COLLECTION_NAME)
    current_chunks = [chunk for chunk in all_chunks if _matches_metadata_filter(chunk["metadata"], extra_filter)]

    if not current_chunks:
        return []

    tokenized_corpus = [chunk["text"].lower().split() for chunk in current_chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(query.lower().split())

    ranked = sorted(zip(current_chunks, scores), key=lambda pair: pair[1], reverse=True)
    results = []
    for chunk, score in ranked:
        if score <= 0 or len(results) >= top_k:
            continue
        results.append(
            {
                "document_id": chunk["metadata"].get("document_id"),
                "chunk_index": chunk["metadata"].get("chunk_index"),
                "text": chunk["text"],
                "score": float(score),
            }
        )
    return results


def _chunk_key(chunk: dict) -> tuple:
    return (chunk["document_id"], chunk["chunk_index"])


def _reciprocal_rank_fusion(labeled_ranked_lists: dict[str, list[dict]], top_k: int) -> list[dict]:
    """score = sum(1 / (RRF_K + rank)) across every list a chunk appears in,
    rank 1-indexed - lets two differently-scaled rankings (BM25's unbounded
    score, cosine similarity's 0-1 range) combine without normalizing either.
    No weighting term - every list's rank contributes identically regardless
    of label, by design (RRF's own point is being scale-free, not a tunable
    blend - Phase 221, see the "matched_by" field this adds for why a
    dense/sparse WEIGHT isn't a real, configurable thing in this
    implementation; which list(s) a chunk actually came from is)."""
    rrf_scores: dict[tuple, float] = {}
    chunks_by_key: dict[tuple, dict] = {}
    matched_by: dict[tuple, list[str]] = {}

    for label, ranked_list in labeled_ranked_lists.items():
        for position, chunk in enumerate(ranked_list):
            key = _chunk_key(chunk)
            rank = position + 1
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            chunks_by_key.setdefault(key, chunk)
            matched_by.setdefault(key, []).append(label)

    ranked_keys = sorted(rrf_scores, key=lambda key: rrf_scores[key], reverse=True)[:top_k]
    results = []
    for key in ranked_keys:
        fused_chunk = dict(chunks_by_key[key])
        fused_chunk["score"] = rrf_scores[key]
        fused_chunk["matched_by"] = matched_by[key]
        results.append(fused_chunk)
    return results


def search_hybrid(query: str, top_k: int = 5, vector_db: str | None = None, extra_filter: dict | None = None) -> list[dict]:
    """BM25 (lexical) + similarity (semantic) results, merged with Reciprocal
    Rank Fusion - each side fetches 3x top_k so fusion has real overlap to work with."""
    # Imported here, not at module top - retriever.py imports this module to
    # register "keyword"/"hybrid" into SEARCH_STRATEGIES, so a top-level
    # import back the other way would be circular.
    from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.retriever import search_similarity

    fetch_k = top_k * 3
    keyword_results = search_keyword(query, top_k=fetch_k, vector_db=vector_db, extra_filter=extra_filter)
    vector_results = search_similarity(query, top_k=fetch_k, vector_db=vector_db, extra_filter=extra_filter)
    return _reciprocal_rank_fusion({"sparse": keyword_results, "dense": vector_results}, top_k)
