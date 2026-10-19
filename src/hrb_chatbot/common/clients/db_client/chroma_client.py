"""ChromaDB client. Two modes via CHROMA_DB_MODE ("persistent"/"http"); built lazily in get_client(), not __init__."""

import re
import threading

import chromadb
from chromadb.config import Settings as ChromaSettings

from src.hrb_chatbot.common.clients.db_client.base_vector_db_client import BaseVectorDBClient
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("chroma_client")

_INVALID_COLLECTION_CHARACTERS = re.compile(r"[^a-zA-Z0-9._-]")


class ChromaDBClient(BaseVectorDBClient):
    """Talks to ChromaDB, embedded (persistent) or over HTTP to a Chroma server."""

    PROVIDER_NAME = "chromadb"
    ENV_KEY = "CHROMA_DB_PERSIST_DIR"

    DEFAULT_MODE = "persistent"
    DEFAULT_PERSIST_DIR = "data/chroma_db"
    DEFAULT_HOST = "localhost"
    DEFAULT_PORT = 8000
    DEFAULT_COLLECTION = "hrb_chatbot_kb"

    def __init__(
        self,
        mode: str | None = None,
        persist_dir: str | None = None,
        host: str | None = None,
        port: int | None = None,
        allow_reset: str | None = None,
        collection_name: str | None = None,
    ):
        """Read settings, but do not connect to anything yet - see module docstring."""
        self.mode = read_setting(mode, "CHROMA_DB_MODE", self.DEFAULT_MODE)
        self.persist_dir = read_setting(persist_dir, "CHROMA_DB_PERSIST_DIR", self.DEFAULT_PERSIST_DIR)
        self.host = read_setting(host, "CHROMA_DB_HOST", self.DEFAULT_HOST)
        self.port = int(read_setting(port, "CHROMA_DB_PORT", self.DEFAULT_PORT))

        allow_reset_setting = read_setting(allow_reset, "CHROMA_DB_ALLOW_RESET", "false")
        self.allow_reset = str(allow_reset_setting).strip().lower() in ("1", "true", "yes")

        self.default_collection_name = read_setting(
            collection_name, "CHROMA_DB_COLLECTION", self.DEFAULT_COLLECTION
        )

        self._client = None
        # Phase 145: chromadb.PersistentClient is SQLite-backed and not
        # safe for concurrent access from multiple threads - confirmed
        # the hard way: Phase 139's asyncio.to_thread() bulk-delete fix
        # (correct for Pinecone, a real concurrent-safe remote service)
        # let concurrent deletes reach this client's threads simultaneously
        # too, and the local persistent index ended up corrupted
        # ("Error finding id" from chromadb's own query layer). A single
        # process-wide lock serializes every real chromadb call this
        # client makes - cheap (chroma calls are a small fraction of total
        # indexing time next to parsing/embedding) and makes concurrent
        # indexing/deletion safe here the same way Pinecone already is.
        # RLock, not Lock: get_collection() calls get_client(), which also
        # acquires this lock (for the lazy-build race guard) - a plain
        # Lock would deadlock a thread against itself on that nested
        # acquire; RLock allows the same thread to re-enter.
        self.collection_lock = threading.RLock()

    def get_client(self):
        """Return the Chroma client object, building it on first use."""
        if self._client is None:
            with self.collection_lock:
                # Re-check inside the lock - another thread may have already
                # built it while this one was waiting.
                if self._client is None:
                    settings = ChromaSettings(allow_reset=self.allow_reset, anonymized_telemetry=False)

                    if self.mode == "http":
                        logger.info("[CHROMADB] connecting over HTTP to %s:%s", self.host, self.port)
                        self._client = chromadb.HttpClient(host=self.host, port=self.port, settings=settings)
                    else:
                        logger.info("[CHROMADB] using embedded persistent storage at %s", self.persist_dir)
                        self._client = chromadb.PersistentClient(path=self.persist_dir, settings=settings)

        return self._client

    def get_configuration(self) -> dict:
        """Return the settings this client is using - nothing here is a secret."""
        config = {"mode": self.mode, "collection": self.default_collection_name}
        if self.mode == "http":
            config["host"] = self.host
            config["port"] = self.port
        else:
            config["persist_dir"] = self.persist_dir
        return config

    @staticmethod
    def sanitize_collection_name(name: str) -> str:
        """Force a name to meet ChromaDB's rules: 3-512 chars, [a-zA-Z0-9._-], alphanumeric ends."""
        sanitized = _INVALID_COLLECTION_CHARACTERS.sub("_", name).strip("_").lower()

        if len(sanitized) < 3:
            sanitized = (sanitized + "___")[:3]

        return sanitized[:512]

    def get_collection(self, collection_name: str | None = None):
        """Return one collection, creating it on first use if it doesn't exist yet."""
        name = self.sanitize_collection_name(collection_name or self.default_collection_name)
        return self.get_client().get_or_create_collection(name=name)

    def upsert(
        self,
        collection_name: str,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict] | None = None,
    ) -> None:
        with self.collection_lock, log_backend_call(logger, "chromadb", "vector.upsert", collection=collection_name, chunk_count=len(ids)):
            collection = self.get_collection(collection_name)
            collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

    def query(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict | None = None,
    ) -> dict:
        with self.collection_lock, log_backend_call(logger, "chromadb", "vector.query", collection=collection_name, top_k=top_k):
            collection = self.get_collection(collection_name)
            return collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )

    def delete(self, collection_name: str, ids: list[str]) -> None:
        with self.collection_lock, log_backend_call(logger, "chromadb", "vector.delete", collection=collection_name, chunk_count=len(ids)):
            collection = self.get_collection(collection_name)
            collection.delete(ids=ids)

    def update_metadata(self, collection_name: str, ids: list[str], metadatas: list[dict]) -> None:
        with self.collection_lock, log_backend_call(
            logger, "chromadb", "vector.update_metadata", collection=collection_name, chunk_count=len(ids)
        ):
            collection = self.get_collection(collection_name)
            collection.update(ids=ids, metadatas=metadatas)

    def get_all_chunks(self, collection_name: str) -> list[dict]:
        with self.collection_lock, log_backend_call(logger, "chromadb", "vector.get_all_chunks", collection=collection_name):
            collection = self.get_collection(collection_name)
            # Phase 218 - "embeddings" added to the include list for exact-KNN's
            # brute-force search; BM25's existing caller just ignores the new key.
            result = collection.get(include=["documents", "metadatas", "embeddings"])

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

    def health_check(self) -> dict:
        """Report whether this client is usable - builds the real client and calls list_collections()."""
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        try:
            collections = self.get_client().list_collections()
            result["status"] = "healthy"
            result["collections_visible"] = len(collections)
        except Exception as error:
            # A health check must never crash - report the problem instead.
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
