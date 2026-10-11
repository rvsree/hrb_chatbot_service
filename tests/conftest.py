"""Shared test fixtures - fakes every test file below imports instead of
writing its own. No test may hit a real network, cost money, or need an
API key, so these fakes match the real clients' method signatures exactly.
`monkeypatch` (pytest) swaps a function/attribute for one test, then
restores it automatically - like Mockito, but on Python's module names."""

import os
from pathlib import Path

from langchain_core.embeddings import Embeddings

# Phase 46 (corrected - the first version of this fix was reviewed and
# found NOT to work): base_metadata_client.py/base_vector_db_client.py
# below have zero dependency on settings.py (confirmed - they only import
# `abc`), so settings.py's own load_dotenv(..., override=True) was never
# actually triggered by this file until something else (db_gateway.py,
# imported later during test collection) imported it for the first time -
# at which point .env's real SQLITE_DB_PATH silently stomped the override
# below back to the real dev DB path. Reproduced live: the dev DB's
# document count changed after a real pytest run, the "isolated" test DB
# had no documents table at all - the fix was a no-op.
#
# Correct fix: import settings.py explicitly, right here, so its one-time
# load_dotenv(override=True) fires during *this* module's own load - then
# the override below runs after that, not racing to run before it. Python
# caches modules (sys.modules), so db_gateway.py's later `import settings`
# reuses this same already-loaded module and does not call load_dotenv() again.
from src.hrb_chatbot.common.config import settings  # noqa: F401
from src.hrb_chatbot.common.clients.db_client.base_metadata_client import BaseMetadataClient
from src.hrb_chatbot.common.clients.db_client.base_vector_db_client import BaseVectorDBClient

_TEST_SQLITE_DB_PATH = "data/test_sqlite_db.sqlite3"
os.environ["SQLITE_DB_PATH"] = _TEST_SQLITE_DB_PATH
Path(_TEST_SQLITE_DB_PATH).unlink(missing_ok=True)

# Phase 84: rate limiting is now Redis-backed, and real .env has
# APP_RATE_LIMITING=true - without this override, every route test that
# incidentally passes through enforce_rate_limit() would try to build a
# real Redis connection (no REDIS_URL set in this environment) and crash.
# Forced off here, same reasoning/pattern as SQLITE_DB_PATH above;
# test_rate_limiter.py tests the enabled case directly, unaffected by this
# (it passes enabled="true" explicitly to the constructor, which wins over
# this env default) with its own injected FakeRedisClient, not real Redis.
os.environ["APP_RATE_LIMITING"] = "false"


class FakeEmbeddings(Embeddings):
    """LangChain's own Embeddings interface, satisfied without a network
    call - returns whichever vector was registered for exact text via
    register(), a small default otherwise. Used anywhere a test needs a
    real LangChain VectorStore object (Chroma, etc.) but not a real
    OpenAI call - retriever.py and vector_indexer.py both build one."""

    def __init__(self):
        self._vectors: dict[str, list[float]] = {}

    def register(self, text: str, vector: list[float]) -> None:
        self._vectors[text] = vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors.get(text, [0.0, 0.0]) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vectors.get(text, [0.0, 0.0])


class FakeEmbeddingClient:
    """Stands in for OpenAIEmbeddingClient - no network, a fixed-size vector
    per text, and a record of every call so a test can assert on what was
    actually asked for (which model, how many texts)."""

    def __init__(self, dimension: int = 4, model: str = "fake-embedding-model"):
        self.dimension = dimension
        self.model = model
        self.calls: list[dict] = []

    def get_embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        self.calls.append({"texts": texts, "model": model})
        embeddings = []
        for _ in texts:
            embeddings.append([0.1] * self.dimension)
        return embeddings

    def get_configuration(self) -> dict:
        return {"base_url": "https://fake", "model": self.model, "organization": None, "project": None}


class FakeChatClient:
    """Stands in for OpenAIChatClient - no network, a canned answer, and a
    record of every call so a test can assert on what was actually asked
    (the question text, the context, temperature/max_tokens)."""

    def __init__(self, model: str = "fake-chat-model", answer: str = "This is a fake grounded answer."):
        self.model = model
        self._answer = answer
        self.calls: list[dict] = []

    def ask(
        self,
        question: str,
        context: str | None = None,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens=None,
    ) -> str:
        self.calls.append(
            {
                "question": question,
                "context": context,
                "system_prompt": system_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self._answer


class FakeClientGateway:
    """Stands in for ClientGateway - just enough to return a FakeEmbeddingClient/
    FakeChatClient where real code calls get_client_gateway().openai_embedding()/openai_chat()."""

    def __init__(
        self,
        embedding_client: FakeEmbeddingClient | None = None,
        chat_client: FakeChatClient | None = None,
    ):
        self._embedding_client = embedding_client or FakeEmbeddingClient()
        self._chat_client = chat_client or FakeChatClient()

    def openai_embedding(self) -> FakeEmbeddingClient:
        return self._embedding_client

    def openai_chat(self) -> FakeChatClient:
        return self._chat_client


class FakeVectorStore(BaseVectorDBClient):
    """An in-memory vector store - a plain dict keyed by chunk id, standing in
    for ChromaDBClient/PineconeClient. Real enough to prove insert/update/
    delete logic works, with none of ChromaDB's or Pinecone's own setup."""

    PROVIDER_NAME = "fake"

    def __init__(self):
        # {collection_name: {chunk_id: {"document": ..., "embedding": ..., "metadata": ...}}}
        self.collections: dict[str, dict[str, dict]] = {}
        self.upsert_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        # A test can set score_overrides["chunk_id"] = 1.5 before calling
        # query() to simulate a specific relevance score - real backends
        # compute this from embedding similarity, which this fake doesn't do.
        self.score_overrides: dict[str, float] = {}

    def upsert(self, collection_name, ids, documents, embeddings, metadatas=None):
        self.upsert_calls.append({"collection_name": collection_name, "ids": list(ids)})
        if collection_name not in self.collections:
            self.collections[collection_name] = {}
        collection = self.collections[collection_name]

        if metadatas is None:
            metadatas = []
            for _ in ids:
                metadatas.append({})

        for chunk_id, document, embedding, metadata in zip(ids, documents, embeddings, metadatas, strict=True):
            collection[chunk_id] = {"document": document, "embedding": embedding, "metadata": metadata}

    def query(self, collection_name, query_embedding, top_k=5, where=None):
        # No real similarity math - just echoes back whatever was upserted
        # and matches `where`, up to top_k, in insertion order. Enough to
        # test the *pipeline* around a vector query (retrieval, is_current
        # filtering, filename lookup, dedup) without needing real embeddings
        # to rank against. Only supports the operators this project's own
        # code actually sends: plain equality and {"$ne": value}.
        collection = self.collections.get(collection_name, {})
        ids, documents, metadatas, scores = [], [], [], []
        for chunk_id, entry in collection.items():
            if not self._matches_where(entry["metadata"], where):
                continue
            ids.append(chunk_id)
            documents.append(entry["document"])
            metadatas.append(entry["metadata"])
            scores.append(self.score_overrides.get(chunk_id, 0.9))
            if len(ids) >= top_k:
                break
        return {"ids": [ids], "documents": [documents], "metadatas": [metadatas], "distances": [scores]}

    @staticmethod
    def _matches_where(metadata, where):
        if not where:
            return True
        for key, condition in where.items():
            actual = metadata.get(key)
            if isinstance(condition, dict) and "$ne" in condition:
                if actual == condition["$ne"]:
                    return False
            elif actual != condition:
                return False
        return True

    def delete(self, collection_name, ids):
        self.delete_calls.append({"collection_name": collection_name, "ids": list(ids)})
        collection = self.collections.get(collection_name, {})
        for chunk_id in ids:
            collection.pop(chunk_id, None)

    def update_metadata(self, collection_name, ids, metadatas):
        collection = self.collections.get(collection_name, {})
        for chunk_id, metadata in zip(ids, metadatas, strict=True):
            if chunk_id in collection:
                collection[chunk_id]["metadata"] = metadata

    def get_all_chunks(self, collection_name):
        collection = self.collections.get(collection_name, {})
        return [
            {"id": chunk_id, "text": entry["document"], "metadata": entry["metadata"]}
            for chunk_id, entry in collection.items()
        ]

    def health_check(self):
        return {"provider": self.PROVIDER_NAME, "status": "healthy"}


class FakeMetadataStore(BaseMetadataClient):
    """An in-memory metadata store - standing in for SQLiteClient/PostgresClient.
    Documents are kept in a plain dict, keyed by document_id."""

    PROVIDER_NAME = "fake"

    def __init__(self):
        self.documents: dict[str, dict] = {}

    async def create_document(
        self,
        document_id,
        filename,
        file_path,
        file_size_bytes=0,
        content_hash="",
        supersedes=None,
        uploaded_by=None,
    ):
        self.documents[document_id] = {
            "id": document_id,
            "filename": filename,
            "file_path": file_path,
            "status": "uploaded",
            "error_message": None,
            "chunk_ids": None,
            "document_version": 1,
            "file_size_bytes": file_size_bytes,
            "content_hash": content_hash,
            "chunk_count": 0,
            "embedding_model": None,
            "embedding_dimension": None,
            "vector_db": None,
            "chunk_size": None,
            "chunk_overlap": None,
            "last_indexed_at": None,
            "is_current": True,
            "supersedes": supersedes,
            "superseded_by": None,
            "owner": None,
            "department": None,
            "doc_category": None,
            "purpose": None,
            "doc_description": None,
            "author": None,
            "doc_date": None,
            "doc_version": None,
            "uploaded_by": uploaded_by,
            "pending_overrides": None,
        }

    async def find_by_content_hash(self, content_hash):
        matches = [doc for doc in self.documents.values() if doc.get("content_hash") == content_hash]
        if not matches:
            return None
        return matches[-1]

    async def delete_document(self, document_id):
        self.documents.pop(document_id, None)

    async def update_status(self, document_id, status, error_message=None):
        if document_id in self.documents:
            self.documents[document_id]["status"] = status
            self.documents[document_id]["error_message"] = error_message

    async def set_pending_overrides(self, document_id, overrides_json):
        if document_id in self.documents:
            self.documents[document_id]["pending_overrides"] = overrides_json

    async def set_chunk_ids(self, document_id, chunk_ids):
        import json

        if document_id in self.documents:
            self.documents[document_id]["chunk_ids"] = json.dumps(chunk_ids)

    async def record_successful_index(
        self,
        document_id,
        chunk_ids,
        embedding_model=None,
        embedding_dimension=None,
        vector_db=None,
        chunking_strategy=None,
        chunk_size=None,
        chunk_overlap=None,
    ):
        import json

        document = self.documents[document_id]
        document["chunk_ids"] = json.dumps(chunk_ids)
        document["chunk_count"] = len(chunk_ids)
        document["embedding_model"] = embedding_model
        document["chunking_strategy"] = chunking_strategy
        document["embedding_dimension"] = embedding_dimension
        document["vector_db"] = vector_db
        document["chunk_size"] = chunk_size
        document["chunk_overlap"] = chunk_overlap
        document["status"] = "indexed"
        document["error_message"] = None
        document["document_version"] += 1
        return document["document_version"]

    async def mark_superseded(self, document_id, superseded_by):
        import json

        document = self.documents.get(document_id)
        if document is None:
            return []
        document["is_current"] = False
        document["superseded_by"] = superseded_by
        return json.loads(document["chunk_ids"]) if document.get("chunk_ids") else []

    async def update_document_content(self, document_id, filename, file_path, file_size_bytes, content_hash):
        document = self.documents.get(document_id)
        if document is None:
            return
        document["filename"] = filename
        document["file_path"] = file_path
        document["file_size_bytes"] = file_size_bytes
        document["content_hash"] = content_hash

    async def record_document_metadata(
        self,
        document_id,
        owner,
        department,
        doc_category,
        purpose,
        doc_description,
        effective_date=None,
        audience=None,
        confidentiality_level=None,
        author=None,
        doc_date=None,
        doc_version=None,
    ):
        document = self.documents.get(document_id)
        if document is not None:
            document["owner"] = owner
            document["department"] = department
            document["doc_category"] = doc_category
            document["purpose"] = purpose
            document["doc_description"] = doc_description
            document["effective_date"] = effective_date
            document["audience"] = audience
            document["confidentiality_level"] = confidentiality_level
            document["author"] = author
            document["doc_date"] = doc_date
            document["doc_version"] = doc_version

    async def get_document(self, document_id):
        return self.documents.get(document_id)

    async def list_documents(self):
        return list(self.documents.values())

    def health_check(self):
        return {"provider": self.PROVIDER_NAME, "status": "healthy"}


class FakeConversationStore:
    """Stands in for ConversationStore (Phase 76) - plain in-memory dict,
    same async interface as the real Postgres-backed one, never touches a
    real database."""

    def __init__(self):
        self._turns: dict[str, list[dict]] = {}
        self._next_created_at = 0

    def _tick(self):
        self._next_created_at += 1
        return f"2026-10-07T00:00:{self._next_created_at:02d}Z"

    async def load_turns(self, conversation_id):
        return list(self._turns.get(conversation_id, []))

    async def save_turn(self, conversation_id, employee_id, role, content):
        turns = self._turns.setdefault(conversation_id, [])
        turns.append(
            {"employee_id": employee_id, "role": role, "content": content, "created_at": self._tick()}
        )

    async def delete_conversation(self, conversation_id, employee_id):
        turns = self._turns.get(conversation_id, [])
        matching = [turn for turn in turns if turn["employee_id"] == employee_id]
        if len(matching) != len(turns):
            return 0  # some turns belong to someone else - matches the real store's all-or-nothing scoping
        deleted_count = len(turns)
        self._turns.pop(conversation_id, None)
        return deleted_count

    async def get_conversation_turns(self, conversation_id, employee_id):
        turns = self._turns.get(conversation_id, [])
        if not turns or any(turn["employee_id"] != employee_id for turn in turns):
            return []
        return [{"role": t["role"], "content": t["content"], "created_at": t["created_at"]} for t in turns]

    async def list_conversations(self, employee_id):
        conversations = []
        for conversation_id, turns in self._turns.items():
            own_turns = [t for t in turns if t["employee_id"] == employee_id]
            if not own_turns:
                continue
            first_human = next((t for t in own_turns if t["role"] == "human"), own_turns[0])
            conversations.append(
                {
                    "conversation_id": conversation_id,
                    "title": first_human["content"],
                    "started_at": own_turns[0]["created_at"],
                    "last_updated_at": own_turns[-1]["created_at"],
                }
            )
        conversations.sort(key=lambda c: c["last_updated_at"], reverse=True)
        return conversations

    def health_check(self):
        return {"provider": "postgres", "status": "healthy"}


class FakeFeedbackStore:
    """Stands in for FeedbackStore (Phase 104) - plain in-memory list, same
    async interface as the real Postgres-backed one, never touches a real
    database."""

    def __init__(self):
        self._entries: list[dict] = []
        self._next_id = 1

    async def save_feedback(
        self, employee_id, conversation_id, message_id, vote, reason_tags, notes, question, answer
    ):
        feedback_id = self._next_id
        self._next_id += 1
        self._entries.append(
            {
                "id": feedback_id,
                "employee_id": employee_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "vote": vote,
                "reason_tags": list(reason_tags),
                "notes": notes,
                "question": question,
                "answer": answer,
                "created_at": "2026-10-06T00:00:00Z",
            }
        )
        return feedback_id

    async def list_feedback(self, employee_id):
        if employee_id is None:
            return list(reversed(self._entries))
        return list(reversed([entry for entry in self._entries if entry["employee_id"] == employee_id]))

    def health_check(self):
        return {"provider": "postgres", "status": "healthy"}


class FakeEmbeddingCache:
    """Stands in for EmbeddingCache (Phase 84, Redis-backed) - plain
    in-memory dict keyed by (content_hash, embedding_model), same async
    interface as the real Redis-backed one, never touches a real cache."""

    def __init__(self):
        self._entries: dict[tuple[str, str], list[float]] = {}

    async def get_many(self, content_hashes, embedding_model):
        return {
            content_hash: self._entries[(content_hash, embedding_model)]
            for content_hash in content_hashes
            if (content_hash, embedding_model) in self._entries
        }

    async def set_many(self, entries, embedding_model):
        for content_hash, embedding in entries:
            self._entries[(content_hash, embedding_model)] = embedding

    async def health_check(self):
        return {"provider": "redis", "status": "healthy"}


class FakeAnswerCache:
    """Stands in for AnswerCache (Phase 84, Redis-backed) - plain in-memory
    dict keyed by cache_key, same async interface as the real Redis-backed
    one, never touches a real cache."""

    def __init__(self):
        self._entries: dict[str, dict] = {}
        self._convo_tags: dict[str, set[str]] = {}
        self.clear_all_call_count = 0

    async def get(self, cache_key):
        return self._entries.get(cache_key)

    async def set(self, cache_key, query, answer):
        self._entries[cache_key] = answer

    async def tag_conversation(self, conversation_id, cache_key):
        self._convo_tags.setdefault(conversation_id, set()).add(cache_key)

    async def clear_for_conversation(self, conversation_id):
        cache_keys = self._convo_tags.pop(conversation_id, set())
        deleted = 0
        for cache_key in cache_keys:
            if self._entries.pop(cache_key, None) is not None:
                deleted += 1
        return deleted

    async def clear_all(self):
        count = len(self._entries)
        self._entries.clear()
        self.clear_all_call_count += 1
        return count

    async def health_check(self):
        return {"provider": "redis", "status": "healthy"}


class FakeDBGateway:
    """Stands in for DBGateway - returns the one FakeVectorStore/FakeMetadataStore/
    FakeConversationStore/FakeEmbeddingCache/FakeAnswerCache given to it regardless
    of provider name. A test needing two distinct providers should use two
    FakeDBGateway instances instead."""

    def __init__(
        self,
        vector_store: FakeVectorStore | None = None,
        metadata_store: FakeMetadataStore | None = None,
        conversation_store: FakeConversationStore | None = None,
        feedback_store: "FakeFeedbackStore | None" = None,
        embedding_cache: FakeEmbeddingCache | None = None,
        answer_cache: FakeAnswerCache | None = None,
    ):
        self._vector_store = vector_store or FakeVectorStore()
        self._metadata_store = metadata_store or FakeMetadataStore()
        self._conversation_store = conversation_store or FakeConversationStore()
        self._feedback_store = feedback_store or FakeFeedbackStore()
        self._embedding_cache = embedding_cache or FakeEmbeddingCache()
        self._answer_cache = answer_cache or FakeAnswerCache()

    def vector_store(self, provider=None):
        return self._vector_store

    def metadata_store(self, provider=None):
        return self._metadata_store

    def conversation_store(self):
        return self._conversation_store

    def feedback_store(self):
        return self._feedback_store

    def embedding_cache(self):
        return self._embedding_cache

    def answer_cache(self):
        return self._answer_cache
