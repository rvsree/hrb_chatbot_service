"""Searches the vector store for chunks matching a query - similarity/MMR, plus LangChain's own retrievers layered on top."""

from langchain.chains.query_constructor.schema import AttributeInfo
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain.retrievers.self_query.base import SelfQueryRetriever
from langchain_community.query_constructors.chroma import ChromaTranslator
from langchain_community.query_constructors.pinecone import PineconeTranslator
from langchain_core.documents import Document

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
    "Sections of JPMC HR benefits policy documents - 401k, healthcare, paid/unpaid time off, "
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

SEARCH_STRATEGIES["keyword"] = search_keyword
SEARCH_STRATEGIES["hybrid"] = search_hybrid


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


def _parse_self_query_filter(
    store, provider: str, query: str, llm_provider: str
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
    return search_kwargs.get("filter")


async def retrieve_chunks(
    query: str,
    top_k: int = 5,
    vector_db: str | None = None,
    search_strategy: str | None = None,
    use_multi_query: bool = False,
    use_self_query: bool = False,
    llm_provider: str | None = None,
    lambda_mult: float | None = None,
) -> tuple[list[dict], dict | None]:
    """Returns (chunks, applied_filter) - score is null for MMR/MultiQuery results."""
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
            applied_filter = _parse_self_query_filter(store, provider, query, resolved_llm_provider)
        except Exception as error:
            logger.warning(
                "Self-Query filter parsing failed for %r - falling back to an unfiltered search: %s: %s",
                query,
                type(error).__name__,
                error,
            )
            applied_filter = None

    if use_multi_query:
        chunks = search_multi_query(
            query,
            top_k=top_k,
            vector_db=vector_db,
            search_strategy=resolved_strategy,
            llm_provider=resolved_llm_provider,
            extra_filter=applied_filter,
        )
    else:
        search_function = SEARCH_STRATEGIES[resolved_strategy]
        search_call_kwargs = {"top_k": top_k, "vector_db": vector_db, "extra_filter": applied_filter}
        if resolved_strategy == "mmr" and lambda_mult is not None:
            search_call_kwargs["lambda_mult"] = lambda_mult
        chunks = search_function(query, **search_call_kwargs)

    await _attach_filenames(chunks, db_gateway)

    logger.info(
        "Retrieved %d chunk(s) via %s, applied_filter=%s", len(chunks), resolved_strategy, applied_filter
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
