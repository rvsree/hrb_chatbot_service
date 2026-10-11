"""Tests for retrieve_chunks() (ai/rag_pipeline/query_retrieval/retriever.py).

retriever.py builds a real LangChain Chroma/PineconeVectorStore around this
project's vector store client (Phase 4, LangChain; the shared builder moved
to common/clients/db_client/langchain_vector_store.py in Phase 17) - it
can no longer be tested against conftest.py's plain-dict FakeVectorStore the
way the old raw-client version could. Uses a real, ephemeral (in-memory,
zero network) chromadb collection, plus conftest.py's FakeEmbeddings, which
returns hand-registered vectors instead of calling OpenAI - real vector
similarity math runs, but nothing here spends real API cost or needs a key.

Each test gets its own uuid-suffixed collection name, and patches
retriever.get_vector_store directly to return a Chroma object built from
that collection + FakeEmbeddings - simpler than patching the pieces
get_vector_store would otherwise use to build one itself, and correct
regardless of which module actually owns that construction.
"""

import uuid

import chromadb
from langchain_chroma import Chroma
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages.ai import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.hrb_chatbot.ai.rag_pipeline.query_retrieval import retriever
from tests.conftest import FakeDBGateway, FakeEmbeddings, FakeMetadataStore


class _FakeLLM(BaseChatModel):
    """Stands in for GatewayChatModel in these tests - returns one fixed
    response regardless of input, so MultiQueryRetriever/SelfQueryRetriever
    can be tested without a real LLM call. `provider` is accepted (matching
    GatewayChatModel(provider=...)'s call shape) but ignored."""

    response_text: str = ""
    provider: str = "openai"

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        generation = ChatGeneration(message=AIMessage(content=self.response_text))
        return ChatResult(generations=[generation])


class FakeVectorStoreClient:
    """Stands in for ChromaDBClient - a real, ephemeral chromadb client
    (get_client(), what retriever.py's _vector_store() actually needs for
    the Chroma path), not something that only duck-types BaseVectorDBClient."""

    PROVIDER_NAME = "chromadb"

    def __init__(self):
        self._client = chromadb.EphemeralClient()

    def get_client(self):
        return self._client

    def get_all_chunks(self, collection_name: str) -> list[dict]:
        # Phase 131 - real get() against the same ephemeral collection _seed_collection() writes into.
        result = self._client.get_or_create_collection(collection_name).get(include=["documents", "metadatas"])
        return [
            {"id": chunk_id, "text": document or "", "metadata": metadata or {}}
            for chunk_id, document, metadata in zip(result["ids"], result["documents"], result["metadatas"], strict=True)
        ]


def _seed_collection(fake_vector_store_client, collection_name: str, chunks: list[dict]) -> None:
    """chunks: list of {id, text, embedding, metadata} - written directly
    into the real ephemeral collection, bypassing the whole indexing
    pipeline (not what's under test here)."""
    collection = fake_vector_store_client.get_client().get_or_create_collection(collection_name)
    collection.add(
        ids=[chunk["id"] for chunk in chunks],
        embeddings=[chunk["embedding"] for chunk in chunks],
        documents=[chunk["text"] for chunk in chunks],
        metadatas=[chunk["metadata"] for chunk in chunks],
    )


def _setup(monkeypatch):
    """Common setup every test needs: a fresh, isolated collection name, a
    real ephemeral Chroma client, a fake metadata store, and a fake
    embeddings object retriever.py will use instead of calling OpenAI.

    retriever.get_vector_store is patched directly to a fixed (store,
    "chromadb") pair, built the same way the real get_vector_store() would
    for the chromadb branch - just with FakeEmbeddings instead of a real
    OpenAI call."""
    collection_name = f"test_{uuid.uuid4().hex}"
    vector_store_client = FakeVectorStoreClient()
    metadata_store = FakeMetadataStore()
    gateway = FakeDBGateway(vector_store=vector_store_client, metadata_store=metadata_store)
    monkeypatch.setattr(retriever, "get_db_gateway", lambda: gateway)

    embeddings = FakeEmbeddings()
    langchain_store = Chroma(
        client=vector_store_client.get_client(), collection_name=collection_name, embedding_function=embeddings
    )
    monkeypatch.setattr(
        retriever, "get_vector_store", lambda vector_db, embedding_model=None: (langchain_store, "chromadb")
    )

    return collection_name, vector_store_client, metadata_store, embeddings


async def test_retrieved_chunks_have_their_source_filename_attached(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-1:0",
                "text": "Parental leave is 16 weeks.",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-1", "chunk_index": 0, "is_current": True},
            }
        ],
    )
    embeddings.register("How much parental leave?", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("How much parental leave?", top_k=5)

    assert len(chunks) == 1
    assert chunks[0]["filename"] == "policy.pdf"
    assert chunks[0]["document_id"] == "doc-1"
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["text"] == "Parental leave is 16 weeks."
    assert chunks[0]["score"] is not None


async def test_a_chunk_whose_document_metadata_is_missing_gets_a_placeholder_filename(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    # A chunk exists in the vector store, but its document row was never
    # created (or was deleted) - retrieval must not crash on this.
    _seed_collection(
        vector_store_client,
        collection_name,
        [{"id": "orphan-doc:0", "text": "orphaned chunk text", "embedding": [1.0, 0.0], "metadata": {"document_id": "orphan-doc", "chunk_index": 0}}],
    )
    embeddings.register("any question", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("any question", top_k=5)

    assert chunks[0]["filename"] == "unknown"


async def test_superseded_chunks_are_excluded_from_retrieval(monkeypatch):
    """The core multi-version-retrieval correctness case: a chunk explicitly
    marked is_current=false (superseded) must never come back from a normal
    query, even though it's still physically present in the vector store."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-old", "policy-v1.pdf", "data/uploads/doc-old/policy-v1.pdf")
    await metadata_store.create_document("doc-new", "policy-v2.pdf", "data/uploads/doc-new/policy-v2.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {"id": "doc-old:0", "text": "stale policy text", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-old", "chunk_index": 0, "is_current": False}},
            {"id": "doc-new:0", "text": "current policy text", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-new", "chunk_index": 0, "is_current": True}},
        ],
    )
    embeddings.register("policy question", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("policy question", top_k=5)

    document_ids = [chunk["document_id"] for chunk in chunks]
    assert "doc-old" not in document_ids
    assert "doc-new" in document_ids


async def test_chunks_with_no_is_current_field_at_all_are_still_retrieved(monkeypatch):
    """Backward compatibility: chunks indexed before is_current existed have
    no such key in their metadata at all - an equality filter would wrongly
    exclude them too; only an explicit false should be excluded."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-legacy", "old-upload.pdf", "data/uploads/doc-legacy/old-upload.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        # No is_current key at all - simulates a pre-existing chunk from before this field.
        [{"id": "doc-legacy:0", "text": "legacy chunk", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-legacy", "chunk_index": 0}}],
    )
    embeddings.register("any question", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("any question", top_k=5)

    assert len(chunks) == 1
    assert chunks[0]["document_id"] == "doc-legacy"


async def test_a_chunk_worse_than_the_relevance_bar_is_excluded(monkeypatch):
    """The real bug this guards against: a question with nothing relevant
    indexed still returns top_k results (vector search has no built-in
    "good enough") - without this filter, those poor matches show up as
    misleading "sources" next to an answer that correctly says it doesn't
    know. See MAX_CHROMA_DISTANCE's own comment for the real scores this
    was calibrated against. Only similarity search has a real per-chunk
    score to compare against - this only applies to that strategy."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-relevant", "policy.pdf", "data/uploads/doc-relevant/policy.pdf")
    await metadata_store.create_document("doc-irrelevant", "unrelated.pdf", "data/uploads/doc-irrelevant/unrelated.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            # Identical to the query vector - distance ~0, well inside the bar.
            {"id": "doc-relevant:0", "text": "a good match", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-relevant", "chunk_index": 0}},
            # Far from the query vector - L2 distance well past MAX_CHROMA_DISTANCE (1.1).
            {"id": "doc-irrelevant:0", "text": "a bad match", "embedding": [10.0, 10.0], "metadata": {"document_id": "doc-irrelevant", "chunk_index": 0}},
        ],
    )
    embeddings.register("some question", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("some question", top_k=5)

    document_ids = [chunk["document_id"] for chunk in chunks]
    assert "doc-relevant" in document_ids
    assert "doc-irrelevant" not in document_ids


async def test_when_every_retrieved_chunk_fails_the_relevance_bar_result_is_empty(monkeypatch):
    """Confirms the empty-list path actually triggers - generate_answer()'s
    own no-chunks short-circuit (response_generation/response_generator.py) then
    kicks in downstream, skipping the LLM call entirely rather than
    generating from irrelevant context."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-1", "unrelated.pdf", "data/uploads/doc-1/unrelated.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [{"id": "doc-1:0", "text": "totally unrelated", "embedding": [50.0, 50.0], "metadata": {"document_id": "doc-1", "chunk_index": 0}}],
    )
    embeddings.register("some question nothing indexed answers", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("some question nothing indexed answers", top_k=5)

    assert chunks == []


async def test_top_k_limits_how_many_chunks_come_back(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {"id": f"doc-1:{i}", "text": f"chunk {i}", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-1", "chunk_index": i}}
            for i in range(5)
        ],
    )
    embeddings.register("a question", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("a question", top_k=2)

    assert len(chunks) == 2


async def test_mmr_search_strategy_returns_chunks_with_a_null_score(monkeypatch):
    """LangChain's max_marginal_relevance_search() does not return a
    per-chunk score at all, unlike similarity_search_with_score() -
    RetrievedChunk.score is null for MMR results, not a made-up number."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [{"id": "doc-1:0", "text": "chunk text", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-1", "chunk_index": 0}}],
    )
    embeddings.register("a question", [1.0, 0.0])

    chunks, applied_filter = await retriever.retrieve_chunks("a question", top_k=5, search_strategy="mmr")

    assert len(chunks) == 1
    assert chunks[0]["score"] is None


async def test_lambda_mult_is_passed_through_to_mmr_search(monkeypatch):
    """Phase 131 - retrieve_chunks(lambda_mult=...) must actually reach
    LangChain's max_marginal_relevance_search(), not just be accepted and
    dropped. Spies on the real Chroma store's own method rather than
    asserting on retrieved chunks, since lambda_mult's effect on ranking
    isn't reliably observable with only one seeded chunk."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [{"id": "doc-1:0", "text": "chunk text", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-1", "chunk_index": 0}}],
    )
    embeddings.register("a question", [1.0, 0.0])
    store, _ = retriever.get_vector_store(None)
    captured_kwargs = {}
    real_mmr_search = store.max_marginal_relevance_search

    def _spy_mmr_search(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return real_mmr_search(*args, **kwargs)

    monkeypatch.setattr(store, "max_marginal_relevance_search", _spy_mmr_search)
    monkeypatch.setattr(retriever, "get_vector_store", lambda vector_db, embedding_model=None: (store, "chromadb"))

    await retriever.retrieve_chunks("a question", top_k=5, search_strategy="mmr", lambda_mult=0.9)

    assert captured_kwargs["lambda_mult"] == 0.9


async def test_lambda_mult_defaults_to_point_five_when_not_given(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [{"id": "doc-1:0", "text": "chunk text", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-1", "chunk_index": 0}}],
    )
    embeddings.register("a question", [1.0, 0.0])
    store, _ = retriever.get_vector_store(None)
    captured_kwargs = {}
    real_mmr_search = store.max_marginal_relevance_search

    def _spy_mmr_search(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return real_mmr_search(*args, **kwargs)

    monkeypatch.setattr(store, "max_marginal_relevance_search", _spy_mmr_search)
    monkeypatch.setattr(retriever, "get_vector_store", lambda vector_db, embedding_model=None: (store, "chromadb"))

    await retriever.retrieve_chunks("a question", top_k=5, search_strategy="mmr")

    assert captured_kwargs["lambda_mult"] == 0.5


async def test_lambda_mult_is_ignored_for_non_mmr_strategies(monkeypatch):
    """lambda_mult only means anything to search_mmr() - passing it alongside
    search_strategy='similarity' must not raise (search_similarity() has no such kwarg)."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [{"id": "doc-1:0", "text": "chunk text", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-1", "chunk_index": 0}}],
    )
    embeddings.register("a question", [1.0, 0.0])

    chunks, _ = await retriever.retrieve_chunks("a question", top_k=5, search_strategy="similarity", lambda_mult=0.9)

    assert len(chunks) == 1


async def test_unknown_search_strategy_raises_value_error(monkeypatch):
    _setup(monkeypatch)

    try:
        await retriever.retrieve_chunks("a question", top_k=5, search_strategy="not-a-real-strategy")
        assert False, "expected a ValueError"
    except ValueError as error:
        assert "not-a-real-strategy" in str(error)


# --- Phase 20: MultiQueryRetriever + Self-Query Retriever -------------------

# Self-Query's own filter-language: eq(field, value) - what its LLM is asked
# to answer with, wrapped in the markdown-JSON shape its own output parser
# expects (parse_and_check_json_markdown - confirmed by reading the real
# parser, see StructuredQueryOutputParser.parse).
_SELF_QUERY_FILTER_RESPONSE = (
    '```json\n{\n  "query": "401k vesting schedule",\n  '
    '"filter": "eq(\\"doc_description\\", \\"401k\\")"\n}\n```'
)
_SELF_QUERY_NO_FILTER_RESPONSE = '```json\n{\n  "query": "how much PTO do I get",\n  "filter": "NO_FILTER"\n}\n```'


def test_combine_with_current_only_returns_the_bare_filter_when_nothing_extra():
    assert retriever._combine_with_current_only(None) == retriever.CURRENT_CHUNKS_ONLY


def test_combine_with_current_only_ands_extra_filter_with_is_current():
    """The spec's own hard rule: is_current must never be overridable by a
    parsed filter - a plain dict merge could let a same-shaped key silently
    replace CURRENT_CHUNKS_ONLY, so this must $and them instead."""
    extra = {"doc_description": {"$eq": "401k"}}
    combined = retriever._combine_with_current_only(extra)
    assert combined == {"$and": [retriever.CURRENT_CHUNKS_ONLY, extra]}


async def test_search_multi_query_merges_and_dedupes_across_rewritten_queries(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [{"id": "doc-1:0", "text": "chunk text", "embedding": [1.0, 0.0], "metadata": {"document_id": "doc-1", "chunk_index": 0}}],
    )
    # MultiQueryRetriever asks the LLM to rewrite the question into several
    # lines; each rewritten line is embedded and searched for separately.
    embeddings.register("rewritten question A", [1.0, 0.0])
    embeddings.register("rewritten question B", [1.0, 0.0])
    monkeypatch.setattr(
        retriever, "GatewayChatModel", lambda provider="openai": _FakeLLM(response_text="rewritten question A\nrewritten question B")
    )

    chunks = retriever.search_multi_query("original question", top_k=5)

    # Both rewritten queries embed to the same vector as the one seeded
    # chunk, so both "find" it - dedup must still collapse this to one.
    assert len(chunks) == 1
    assert chunks[0]["document_id"] == "doc-1"
    assert chunks[0]["score"] is None  # MultiQueryRetriever never returns a score


async def test_parse_self_query_filter_returns_the_models_own_parsed_filter(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    monkeypatch.setattr(retriever, "GatewayChatModel", lambda provider="openai": _FakeLLM(response_text=_SELF_QUERY_FILTER_RESPONSE))
    store, provider = retriever.get_vector_store(None)

    applied_filter = retriever._parse_self_query_filter(store, provider, "what's my 401k vesting schedule", "openai")

    assert applied_filter == {"doc_description": {"$eq": "401k"}}


async def test_parse_self_query_filter_returns_none_when_the_model_finds_nothing_to_filter_on(monkeypatch):
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    monkeypatch.setattr(retriever, "GatewayChatModel", lambda provider="openai": _FakeLLM(response_text=_SELF_QUERY_NO_FILTER_RESPONSE))
    store, provider = retriever.get_vector_store(None)

    applied_filter = retriever._parse_self_query_filter(store, provider, "how much PTO do I get", "openai")

    assert applied_filter is None


async def test_retrieve_chunks_use_self_query_excludes_superseded_chunks_even_when_a_filter_is_parsed(monkeypatch):
    """The core correctness case this phase's spec calls out explicitly:
    is_current must stay under this project's own control - a superseded
    chunk that also matches the parsed doc_description filter must still
    be excluded, not let through because it satisfies the parsed filter."""
    collection_name, vector_store_client, metadata_store, embeddings = _setup(monkeypatch)
    await metadata_store.create_document("doc-old", "401k-v1.pdf", "data/uploads/doc-old/401k-v1.pdf")
    await metadata_store.create_document("doc-new", "401k-v2.pdf", "data/uploads/doc-new/401k-v2.pdf")
    _seed_collection(
        vector_store_client,
        collection_name,
        [
            {
                "id": "doc-old:0",
                "text": "stale 401k text",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-old", "chunk_index": 0, "is_current": False, "doc_description": "401k"},
            },
            {
                "id": "doc-new:0",
                "text": "current 401k text",
                "embedding": [1.0, 0.0],
                "metadata": {"document_id": "doc-new", "chunk_index": 0, "is_current": True, "doc_description": "401k"},
            },
        ],
    )
    embeddings.register("what's my 401k vesting schedule", [1.0, 0.0])
    monkeypatch.setattr(retriever, "GatewayChatModel", lambda provider="openai": _FakeLLM(response_text=_SELF_QUERY_FILTER_RESPONSE))

    chunks, applied_filter = await retriever.retrieve_chunks("what's my 401k vesting schedule", top_k=5, use_self_query=True)

    document_ids = [chunk["document_id"] for chunk in chunks]
    assert "doc-new" in document_ids
    assert "doc-old" not in document_ids
    assert applied_filter == {"doc_description": {"$eq": "401k"}}
