"""Searches the vector store for chunks matching a query - similarity/MMR, plus LangChain's own retrievers layered on top."""

import difflib
import re

from langchain.chains.query_constructor.schema import AttributeInfo
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain.retrievers.self_query.base import SelfQueryRetriever
from langchain_community.query_constructors.chroma import ChromaTranslator
from langchain_community.query_constructors.pinecone import PineconeTranslator
from langchain_core.documents import Document

from src.hrb_chatbot.ai.rag_pipeline.helper.access_control import build_acl_filter
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.db_client.langchain_vector_store import get_vector_store
from src.hrb_chatbot.common.clients.llm_client.langchain_chat_model import GatewayChatModel
from src.hrb_chatbot.common.config.settings import get_active_llm_provider, read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_pipeline.retriever")

# Only chunks still in play - $ne (not equal), not is_current=True equality:
# older chunks have no is_current key at all and would be wrongly excluded by equality.
CURRENT_CHUNKS_ONLY = {"is_current": {"$ne": False}}

# Self-Query's LLM may only parse a filter on these three fields - is_current is deliberately absent (bookkeeping only).
METADATA_FIELD_INFO = [
    AttributeInfo(
        name="doc_category",
        description="The kind of document: one of policy, regulatory, investment, benefits, other.",
        type="string",
    ),
    AttributeInfo(name="department", description="Which company department this document belongs to.", type="string"),
    AttributeInfo(
        name="doc_description",
        description=(
            "The specific topic this document covers, in the document's own terms, e.g. '401k', "
            "'health benefits', 'leave policy'."
        ),
        type="string",
    ),
]
DOCUMENT_CONTENTS_DESCRIPTION = (
    "Sections of AmazingBank HR benefits policy documents - 401k, healthcare, paid/unpaid time off, "
    "tuition assistance, and similar."
)

# One translator per vector-store backend - turns Self-Query's parsed filter
# into that backend's own native `where`/`filter` dict shape.
_STRUCTURED_QUERY_TRANSLATORS = {"chromadb": ChromaTranslator, "pinecone": PineconeTranslator}

# top_k always returns that many results even if irrelevant - vector search
# has no "good enough" concept. Calibrated in Phase 4.5 (see docs/agent-reference/RAG-ROADMAP.md).
MAX_CHROMA_DISTANCE = float(read_setting(None, "RAG_MAX_CHROMA_DISTANCE", 1.1))
MIN_PINECONE_SCORE = float(read_setting(None, "RAG_MIN_PINECONE_SCORE", 0.5))


def _meets_relevance_bar(score: float, provider_name: str) -> bool:
    # Direction depends on the backend: Chroma's distance is lower=better,
    # Pinecone's score is higher=better.
    if provider_name == "pinecone":
        return score >= MIN_PINECONE_SCORE
    return score <= MAX_CHROMA_DISTANCE


def _document_to_chunk(document: Document, score: float | None) -> dict:
    metadata = document.metadata
    return {
        "document_id": metadata.get("document_id"),
        "chunk_index": metadata.get("chunk_index"),
        "text": document.page_content,
        "score": score,
    }


def _combine_with_current_only(extra_filter: dict | None) -> dict:
    # is_current must always apply - never something a parsed filter can
    # override. A plain merge could let a same-shaped key replace it, so AND instead.
    if not extra_filter:
        return CURRENT_CHUNKS_ONLY
    return {"$and": [CURRENT_CHUNKS_ONLY, extra_filter]}


def search_similarity(
    query: str, top_k: int = 5, vector_db: str | None = None, extra_filter: dict | None = None
) -> list[dict]:
    # Plain relevance-ranked search - the default. Chunks below the
    # relevance bar (MAX_CHROMA_DISTANCE/MIN_PINECONE_SCORE) are dropped.
    store, provider = get_vector_store(vector_db)
    results = store.similarity_search_with_score(query, k=top_k, filter=_combine_with_current_only(extra_filter))

    chunks = []
    for document, score in results:
        if _meets_relevance_bar(score, provider):
            chunks.append(_document_to_chunk(document, score))
    return chunks


def search_mmr(
    query: str,
    top_k: int = 5,
    vector_db: str | None = None,
    fetch_k: int | None = None,
    extra_filter: dict | None = None,
    lambda_mult: float | None = None,
) -> list[dict]:
    # Max Marginal Relevance - trades relevance for diversity (non-redundant
    # context). fetch_k defaults to 3x top_k, module 4's own recommended ratio.
    # lambda_mult: 1.0 = pure relevance, 0.0 = pure diversity - LangChain's own default (0.5) when not given.
    store, provider = get_vector_store(vector_db)
    documents = store.max_marginal_relevance_search(
        query,
        k=top_k,
        fetch_k=fetch_k or top_k * 3,
        filter=_combine_with_current_only(extra_filter),
        lambda_mult=lambda_mult if lambda_mult is not None else 0.5,
    )
    # No score at all (unlike similarity_search_with_score) - None here, not
    # a made-up number; no relevance-bar filtering for the same reason.
    return [_document_to_chunk(document, None) for document in documents]


SEARCH_STRATEGIES = {
    "similarity": search_similarity,
    "mmr": search_mmr,
}

# bm25_search.py imports search_similarity from this module - importing it
# down here, after SEARCH_STRATEGIES exists, avoids a circular import at module load time.
from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.bm25_search import search_hybrid, search_keyword  # noqa: E402
from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.exact_knn_search import search_knn  # noqa: E402

SEARCH_STRATEGIES["keyword"] = search_keyword
SEARCH_STRATEGIES["hybrid"] = search_hybrid
SEARCH_STRATEGIES["knn"] = search_knn


def search_multi_query(
    query: str,
    top_k: int = 5,
    vector_db: str | None = None,
    search_strategy: str | None = None,
    llm_provider: str = "openai",
    extra_filter: dict | None = None,
) -> list[dict]:
    # Rewrites `query` into several phrasings, searches each via the base
    # retriever, merges/dedupes - LangChain's own MultiQueryRetriever. No score, same as MMR.
    store, _ = get_vector_store(vector_db)
    resolved_strategy = search_strategy or "similarity"
    search_kwargs = {"k": top_k, "filter": _combine_with_current_only(extra_filter)}
    if resolved_strategy == "mmr":
        search_kwargs["fetch_k"] = top_k * 3
    base_retriever = store.as_retriever(search_type=resolved_strategy, search_kwargs=search_kwargs)

    multi_query_retriever = MultiQueryRetriever.from_llm(
        retriever=base_retriever, llm=GatewayChatModel(provider=llm_provider)
    )
    documents = multi_query_retriever.invoke(query)
    return [_document_to_chunk(document, None) for document in documents]


# Phase 230 - below this cutoff, difflib's own match confidence is low
# enough that substituting it would likely pick the WRONG document rather
# than fix the right one - falls back to the LLM's original (unresolved)
# value instead, same "finds nothing" outcome as before this phase, not a
# new, worse failure mode (a wrong document would be worse than none).
# This is the FALLBACK tier only (near-miss typos) - see
# _resolve_doc_description_value()'s own docstring for why the PRIMARY
# match tier isn't difflib at all.
DOC_DESCRIPTION_MATCH_CUTOFF = 0.6


def _normalize_for_matching(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _resolve_doc_description_value(value: str, real_descriptions: list[str]) -> str:
    """Self-Query's parsing LLM is prompted for a short topic phrase
    (AttributeInfo's own description, e.g. '401k'), but the real indexed
    value is the document's own full extracted description (e.g. '401(k)
    Savings Plan') - confirmed, reproduced BACKLOG.md gap: an exact-match
    filter on the LLM's short guess reliably finds nothing.

    Two-tier resolution, both standard-library only (no new dependency):
    1. Normalized substring containment - strips case/punctuation/spacing
       from both sides and checks if the LLM's short guess appears inside
       a real description. This is the real, common case, and it's NOT
       what difflib.get_close_matches() alone was built for: a generic
       character-level similarity ratio penalizes the length difference
       between a short keyword and a long title so heavily that the real
       documented pair here ('401k' vs '401(k) Savings Plan') scores only
       0.35 - below any cutoff that wouldn't also risk false-matching
       unrelated short queries elsewhere. Substring containment on
       normalized text catches this reliably instead.
    2. difflib.get_close_matches() as a fallback, for near-miss typos that
       aren't a clean substring (e.g. 'healthcare benfits' vs the real
       'Healthcare Benefits')."""
    normalized_value = _normalize_for_matching(value)
    if normalized_value:
        for real_value in real_descriptions:
            if normalized_value in _normalize_for_matching(real_value):
                return real_value

    matches = difflib.get_close_matches(value, real_descriptions, n=1, cutoff=DOC_DESCRIPTION_MATCH_CUTOFF)
    return matches[0] if matches else value


def _rewrite_doc_description_filter(filter_value, real_descriptions: list[str]):
    """Walks a backend-native filter dict (LangChain's own translator
    output, e.g. {"doc_description": {"$eq": "401k"}}, possibly nested
    under "$and" alongside doc_category/department) and resolves any
    doc_description equality value in place - everything else passes
    through unchanged."""
    if isinstance(filter_value, dict):
        if "doc_description" in filter_value and isinstance(filter_value["doc_description"], dict):
            eq_clause = filter_value["doc_description"]
            if "$eq" in eq_clause:
                return {
                    **filter_value,
                    "doc_description": {**eq_clause, "$eq": _resolve_doc_description_value(eq_clause["$eq"], real_descriptions)},
                }
        return {key: _rewrite_doc_description_filter(value, real_descriptions) for key, value in filter_value.items()}
    if isinstance(filter_value, list):
        return [_rewrite_doc_description_filter(item, real_descriptions) for item in filter_value]
    return filter_value


async def _parse_self_query_filter(
    store, provider: str, query: str, llm_provider: str, db_gateway
) -> dict | None:
    """Parse `query` into a filter over METADATA_FIELD_INFO, or None - not yet combined with is_current."""
    translator = _STRUCTURED_QUERY_TRANSLATORS[provider]()
    self_query_retriever = SelfQueryRetriever.from_llm(
        GatewayChatModel(provider=llm_provider),
        store,
        DOCUMENT_CONTENTS_DESCRIPTION,
        METADATA_FIELD_INFO,
        structured_query_translator=translator,
    )
    # Calls query_constructor + _prepare_query directly (not .invoke(),
    # which does the same internally) - one LLM call, and returns the filter itself.
    structured_query = self_query_retriever.query_constructor.invoke({"query": query})
    _, search_kwargs = self_query_retriever._prepare_query(query, structured_query)
    parsed_filter = search_kwargs.get("filter")
    if parsed_filter is None:
        return None

    # Phase 230 - only pay for the real-values lookup when the parsed
    # filter actually references doc_description at all.
    if "doc_description" in str(parsed_filter):
        documents = await db_gateway.metadata_store().list_documents()
        real_descriptions = [doc["doc_description"] for doc in documents if doc.get("doc_description")]
        if real_descriptions:
            parsed_filter = _rewrite_doc_description_filter(parsed_filter, real_descriptions)
    return parsed_filter


def _combine_extra_filters(self_query_filter: dict | None, acl_filter: dict | None) -> dict | None:
    """Phase 231 - ANDs Self-Query's own filter with the ACL deny-list
    filter, both optional. Kept separate from _combine_with_current_only()
    (which always applies, self-query or not) since ACL must too - it's
    computed unconditionally in retrieve_chunks(), not gated behind
    use_self_query the way applied_filter is."""
    filters = [f for f in (self_query_filter, acl_filter) if f]
    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return {"$and": filters}


async def retrieve_chunks(
    query: str,
    top_k: int = 5,
    vector_db: str | None = None,
    search_strategy: str | None = None,
    use_multi_query: bool = False,
    use_self_query: bool = False,
    llm_provider: str | None = None,
    lambda_mult: float | None = None,
    role: str | None = None,
    department: str | None = None,
) -> tuple[list[dict], dict | None]:
    """Returns (chunks, applied_filter) - score is null for MMR/MultiQuery
    results. applied_filter is Self-Query's own filter only (for the
    Explainability "Applied Filter" display) - the Phase 231 ACL filter is
    always combined in separately before chunks are actually searched, but
    deliberately not reported back as part of "the query's own filter"."""
    resolved_strategy = search_strategy or "similarity"
    resolved_llm_provider = get_active_llm_provider(llm_provider)
    logger.info(
        "search: strategy=%s (%s), multi_query=%s, self_query=%s, llm_provider=%s",
        resolved_strategy,
        "explicit" if search_strategy else "default",
        use_multi_query,
        use_self_query,
        resolved_llm_provider,
    )
    if resolved_strategy not in SEARCH_STRATEGIES:
        raise ValueError(f"Unknown search_strategy {resolved_strategy!r} - choose one of {list(SEARCH_STRATEGIES)}")

    db_gateway = get_db_gateway()
    store, provider = get_vector_store(vector_db)

    applied_filter: dict | None = None
    if use_self_query:
        # Best-effort - same "never block the answer" approach as extraction.
        try:
            applied_filter = await _parse_self_query_filter(store, provider, query, resolved_llm_provider, db_gateway)
        except Exception as error:
            logger.warning(
                "Self-Query filter parsing failed for %r - falling back to an unfiltered search: %s: %s",
                query,
                type(error).__name__,
                error,
            )
            applied_filter = None

    # Phase 231 - unconditional, unlike applied_filter above: ACL must gate
    # every retrieval, not just self-query ones. Best-effort (same "never
    # block the answer" choice every other best-effort step here already
    # makes) - matches this project's existing philosophy consistently
    # rather than introducing one path that fails closed and every other
    # path that doesn't; RBAC here is already documented as a formality,
    # not a real security boundary (endpoint-request-response-contracts.md).
    try:
        acl_filter = await build_acl_filter(db_gateway, role, department)
    except Exception as error:
        logger.warning(
            "ACL filter resolution failed - falling back to an unfiltered search: %s: %s",
            type(error).__name__,
            error,
        )
        acl_filter = None
    combined_filter = _combine_extra_filters(applied_filter, acl_filter)

    if use_multi_query:
        chunks = search_multi_query(
            query,
            top_k=top_k,
            vector_db=vector_db,
            search_strategy=resolved_strategy,
            llm_provider=resolved_llm_provider,
            extra_filter=combined_filter,
        )
    else:
        search_function = SEARCH_STRATEGIES[resolved_strategy]
        search_call_kwargs = {"top_k": top_k, "vector_db": vector_db, "extra_filter": combined_filter}
        if resolved_strategy == "mmr" and lambda_mult is not None:
            search_call_kwargs["lambda_mult"] = lambda_mult
        chunks = search_function(query, **search_call_kwargs)

    await _attach_filenames(chunks, db_gateway)

    logger.info(
        "Retrieved %d chunk(s) via %s, applied_filter=%s, acl_filter=%s",
        len(chunks), resolved_strategy, applied_filter, acl_filter,
    )
    return chunks, applied_filter


async def _attach_filenames(chunks: list[dict], db_gateway) -> None:
    """Look up each chunk's source filename, one metadata-store call per
    distinct document_id - a query typically retrieves several chunks from one doc."""
    metadata_store = db_gateway.metadata_store()
    filenames_by_document_id: dict[str, str] = {}

    for chunk in chunks:
        document_id = chunk["document_id"]
        if document_id not in filenames_by_document_id:
            document = await metadata_store.get_document(document_id)
            filenames_by_document_id[document_id] = document["filename"] if document else "unknown"
        chunk["filename"] = filenames_by_document_id[document_id]
