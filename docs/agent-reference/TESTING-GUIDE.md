# Testing guide

A simple, follow-along guide to this project's test suite - what's tested,
what isn't yet, and the pattern to copy when you add your own tests for
the hand-written RAG pipeline later. This doc covers whether the *code*
works (the pytest suite); for whether the chatbot's *answers* are actually
good (golden/synthetic/live-query datasets, the RAG quality side), see
[testing-strategies.md](testing-strategies.md) instead.

## Running the tests

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # once
.venv\Scripts\python.exe -m pytest -v                              # every test
.venv\Scripts\python.exe -m pytest tests/hrb_chatbot/ai/ -v        # just one folder
.venv\Scripts\python.exe -m pytest -k "chunk_size" -v              # just tests whose name matches
```

No test here needs a real API key, a real database, or an internet
connection - every one runs in about the same time it takes to read this
sentence. If a test in this suite ever needs a key to pass, that's a bug
in the test, not something to work around by adding one to `.env`.

## What's actually tested today, and why these cases specifically

Selective on purpose, matching how this suite was scoped: a handful of
cases chosen for what's most likely to silently break, not exhaustive
coverage of every function in the codebase.

| File | What it tests | Why these cases |
|---|---|---|
| `tests/hrb_chatbot/ai/doc_processing/chunking/test_text_chunker.py` | `chunk_text()` - splitting and overlap | Empty input, input shorter than one chunk, overlap actually overlapping, and the `chunk_overlap=0` case specifically (a real value that a careless `or DEFAULT` refactor would silently discard - see `pipeline.py`'s own comment on this exact bug shape) |
| `tests/hrb_chatbot/ai/doc_processing/embedding/test_embedding_generator.py` | `generate_embeddings()` calling the (fake) embedding client correctly | The empty-list short-circuit, and that a `embedding_model` override actually reaches the client - not just that *some* embeddings come back |
| `tests/hrb_chatbot/ai/doc_processing/indexing/test_vector_indexer.py` | `write_chunks()` - insert vs. update, stale-chunk cleanup | This is the highest-value file in the suite: a document that shrinks on re-index must not leave orphaned chunks in the vector store forever - checked by counting what's *actually* left in the fake store, not just trusting the returned report (the same discipline `docs/agent-reference/RAG-ROADMAP.md`'s Phase 4 notes describe catching a real double-execution bug with) |
| `tests/hrb_chatbot/api/rag/test_routes_query.py` | `POST /rag/query`'s validation and stub behavior | Confirms the stub fails the *right* way (501, naming the file to implement) and that request validation (empty query, `top_k` range, the new `model_name`/`temperature`/`max_tokens` fields) works without needing Phase 6 to exist |
| `tests/hrb_chatbot/test_ab_testing_demo.py` | A **reference pattern** for A/B comparisons, not real evaluation | See its own docstring - this exists to show the shape of an A/B test, not to evaluate anything real yet |

**Not tested here, and why**: `ai/rag_pipeline/` (retrieval + generation),
`ai/pre_processing/` (query decomposition, guardrails), and
`ai/rag_pipeline/evaluations/` are all hand-written work per the
division-of-labor table in `docs/agent-reference/RAG-ROADMAP.md` and mostly don't exist
yet (Phase 6+) - there's nothing real to test until that code is written.
The one thing that *is* tested from that area is the query endpoint's
current stub behavior (above), since that's Claude-Code-owned API
plumbing, not the hand-written pipeline logic itself.

## The pattern: fakes, not real backends, not mocks-that-mock-everything

Every test in this suite follows the same shape, and it's worth
understanding once rather than re-deriving per file:

1. **A fake class implements the same interface as the real client.**
   `FakeVectorStore` in `tests/conftest.py` implements
   `BaseVectorDBClient` exactly the way `ChromaDBClient` does - same
   method names, same arguments - just backed by a plain Python dict
   instead of a real ChromaDB connection. Code under test can't tell the
   difference between calling the fake and calling the real thing.
2. **`monkeypatch` swaps the real gateway lookup for the fake, for one
   test only.** `monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)`
   replaces `get_db_gateway` inside `vector_indexer.py`'s own module
   namespace, for the duration of that one test function - pytest puts the
   real one back automatically when the test ends, even if the test fails.
3. **Assert on behavior, then prove it with real state, not just the
   returned value.** See `test_reindexing_a_shrunken_document_deletes_the_now_stale_chunks` -
   it checks the returned `chunks_removed` count *and* separately counts
   what's actually left in the fake vector store, because a function can
   report the right numbers while still leaving orphaned data behind (a
   real bug this project already found once, the hard way - see
   `docs/agent-reference/RAG-ROADMAP.md`'s Phase 4 notes).

## When you build the hand-written pipeline: the pattern to copy

Once `ai/rag_pipeline/query_retrieval/` and
`ai/rag_pipeline/response_generation/` have real logic instead of
`NotImplementedError`, a test for them looks exactly like
`test_vector_indexer.py` does today:

```python
async def test_retrieval_returns_the_top_k_closest_chunks(monkeypatch):
    vector_store = FakeVectorStore()
    # ... pre-populate vector_store with some fake chunks + embeddings ...
    gateway = FakeDBGateway(vector_store=vector_store)
    monkeypatch.setattr(query_retrieval, "get_db_gateway", lambda: gateway)

    results = await query_retrieval.retrieve_chunks(["a question"], top_k=3)

    assert len(results) <= 3
```

No real vector store, no real embedding call, no real LLM call - the same
fakes already in `tests/conftest.py` (or new ones following the same
shape, if a new interface needs one) work for the hand-written pipeline
too. `FakeEmbeddingClient` already exists for exactly this - `retrieve_chunks()`
will need to embed the query text before searching, and it doesn't need a
real OpenAI call to prove the surrounding logic works.

For **generation**, the interesting cases to test aren't really about the
LLM call itself (that's `openai_client.py`'s job, tested implicitly by
every health check that already exercises it) - they're about prompt
construction and grounding: does `generate_answer()` actually include the
retrieved chunks in the prompt it builds? Does it behave sensibly when
`chunks` is empty (no relevant context found)? Those are testable today,
right now, with a fake LLM client - they don't need to wait for anything.

## Adding a test for a new chunking strategy

The project plans to add semantic, fixed-size, and document-structure-based
chunking alongside the recursive strategy already built. Whichever
strategy is added, the tests in `test_text_chunker.py` show the shape to
copy directly - the same handful of properties matter regardless of
*how* a strategy decides where to split:

- Does an empty or trivially short input come back empty/unsplit?
- Does the output actually respect chunk_size (or fail informatively if
  a single semantic unit genuinely can't be split smaller)?
- Does overlap (if the new strategy has one) actually overlap?
- Does an edge value like `chunk_overlap=0` or `chunk_size=1` behave
  sensibly rather than crash?

A new strategy earns its own test file
(`test_semantic_chunker.py`, `test_fixed_size_chunker.py`, ...) rather than
being crammed into the existing one - same reasoning `ChromaDBClient` and
`PineconeClient` get separate test files even though they implement the
same contract.
