"""Pinecone client - alternative to ChromaDB. Gotcha: query() returns "score" (higher=closer), not Chroma's "distance"."""

import json
import time

from pinecone import Pinecone, ServerlessSpec

from src.hrb_chatbot.common.clients.db_client.base_vector_db_client import BaseVectorDBClient
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("pinecone_client")

# Total wait for a freshly created index to report ready - serverless indexes are typically ready in seconds.
INDEX_READY_TIMEOUT_SECONDS = int(read_setting(None, "PINECONE_INDEX_READY_TIMEOUT_SECONDS", 60))
INDEX_READY_POLL_SECONDS = int(read_setting(None, "PINECONE_INDEX_READY_POLL_SECONDS", 2))


def _text_from_llama_index_node_content(metadata: dict) -> str:
    """LlamaIndex used to store chunk text in a "_node_content" blob instead of this client's "document" key."""
    raw_node_content = metadata.get("_node_content")
    if not raw_node_content:
        return ""
    try:
        return json.loads(raw_node_content).get("text", "")
    except (json.JSONDecodeError, AttributeError):
        return ""


class PineconeClient(BaseVectorDBClient):
    """Talks to Pinecone."""

    PROVIDER_NAME = "pinecone"
    ENV_KEY = "PINECONE_API_KEY"

    DEFAULT_CLOUD = "aws"
    DEFAULT_REGION = "us-east-1"
    DEFAULT_METRIC = "cosine"
    DEFAULT_DIMENSION = 1536

    def __init__(
        self,
        api_key: str | None = None,
        index_name: str | None = None,
        cloud: str | None = None,
        region: str | None = None,
        metric: str | None = None,
        dimension: int | None = None,
    ):
        """Read settings and build the lightweight Pinecone client object - no network call yet."""
        self.api_key = read_setting(api_key, "PINECONE_API_KEY")
        self.index_name = read_setting(index_name, "PINECONE_INDEX_NAME")
        self.cloud = read_setting(cloud, "PINECONE_CLOUD", self.DEFAULT_CLOUD)
        self.region = read_setting(region, "PINECONE_ENVIRONMENT", self.DEFAULT_REGION)
        self.metric = read_setting(metric, "PINECONE_METRIC", self.DEFAULT_METRIC)
        self.dimension = int(read_setting(dimension, "PINECONE_DIMENSION", self.DEFAULT_DIMENSION))

        if not self.api_key:
            logger.warning("[PINECONE] PINECONE_API_KEY not set")

        if self.api_key:
            self._client = Pinecone(api_key=self.api_key)
        else:
            self._client = None
        self._index = None
        self._index_ready = False

    def get_configuration(self) -> dict:
        """Return the settings this client is using - nothing here is a secret."""
        return {
            "index_name": self.index_name,
            "cloud": self.cloud,
            "region": self.region,
            "metric": self.metric,
            "dimension": self.dimension,
        }

    def _require_client(self) -> Pinecone:
        if self._client is None:
            raise RuntimeError("PINECONE_API_KEY is not configured")
        return self._client

    def _ensure_index(self) -> None:
        """Create the configured index if needed and wait for it to be ready - safe to call repeatedly."""
        if self._index_ready:
            return

        client = self._require_client()

        if not client.has_index(self.index_name):
            logger.info(
                "[PINECONE] creating serverless index %r (dimension=%s, metric=%s, %s/%s)",
                self.index_name,
                self.dimension,
                self.metric,
                self.cloud,
                self.region,
            )
            client.create_index(
                name=self.index_name,
                dimension=self.dimension,
                metric=self.metric,
                spec=ServerlessSpec(cloud=self.cloud, region=self.region),
            )

        waited = 0
        while not client.describe_index(self.index_name).status["ready"]:
            if waited >= INDEX_READY_TIMEOUT_SECONDS:
                raise TimeoutError(
                    f"Pinecone index {self.index_name!r} did not become ready within "
                    f"{INDEX_READY_TIMEOUT_SECONDS}s"
                )
            time.sleep(INDEX_READY_POLL_SECONDS)
            waited += INDEX_READY_POLL_SECONDS

        self._index_ready = True

    def get_index(self):
        """Return the Index handle, ensuring the index exists and is ready first."""
        self._ensure_index()

        if self._index is None:
            self._index = self._require_client().Index(self.index_name)

        return self._index

    def upsert(
        self,
        collection_name: str,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict] | None = None,
    ) -> None:
        if metadatas is None:
            # No metadata given - fill in an empty dict per id so the merge loop below has something to write into.
            metadatas = []
            for _ in ids:
                metadatas.append({})

        # Four lists line up by position - strict=True catches mismatched lengths instead of silently truncating.
        vectors = []
        for id_, embedding, document, metadata in zip(ids, embeddings, documents, metadatas, strict=True):
            # Pinecone has no native "document text" field - stash it in metadata alongside what's already there.
            vector_metadata = dict(metadata)
            vector_metadata["document"] = document
            vectors.append({"id": id_, "values": embedding, "metadata": vector_metadata})

        with log_backend_call(
            logger, "pinecone", "vector.upsert", namespace=collection_name, chunk_count=len(vectors)
        ):
            self.get_index().upsert(vectors=vectors, namespace=collection_name)

    def query(
        self,
        collection_name: str,
        query_embedding: list[float],
        top_k: int = 5,
        where: dict | None = None,
    ) -> dict:
        with log_backend_call(logger, "pinecone", "vector.query", namespace=collection_name, top_k=top_k):
            response = self.get_index().query(
                vector=query_embedding,
                top_k=top_k,
                namespace=collection_name,
                filter=where,
                include_metadata=True,
            )

        ids, documents, metadatas, scores = [], [], [], []
        for match in response.matches:
            metadata = dict(match.metadata or {})
            ids.append(match.id)
            documents.append(metadata.pop("document", "") or _text_from_llama_index_node_content(metadata))
            metadatas.append(metadata)
            scores.append(match.score)

        # Nested once to match Chroma's shape - "distances" here are Pinecone scores (higher = closer).
        return {"ids": [ids], "documents": [documents], "metadatas": [metadatas], "distances": [scores]}

    def delete(self, collection_name: str, ids: list[str]) -> None:
        with log_backend_call(
            logger, "pinecone", "vector.delete", namespace=collection_name, chunk_count=len(ids)
        ):
            self.get_index().delete(ids=ids, namespace=collection_name)

    def update_metadata(self, collection_name: str, ids: list[str], metadatas: list[dict]) -> None:
        """Pinecone's update() merges rather than replaces - harmless since callers pass the full metadata anyway."""
        with log_backend_call(
            logger, "pinecone", "vector.update_metadata", namespace=collection_name, chunk_count=len(ids)
        ):
            index = self.get_index()
            for id_, metadata in zip(ids, metadatas, strict=True):
                index.update(id=id_, set_metadata=metadata, namespace=collection_name)

    def get_all_chunks(self, collection_name: str) -> list[dict]:
        """Pinecone has no single "list everything" call - list() yields id batches, fetch() gets the rest."""
        index = self.get_index()

        with log_backend_call(logger, "pinecone", "vector.get_all_chunks", namespace=collection_name):
            all_ids = []
            for id_batch in index.list(namespace=collection_name):
                all_ids.extend(id_batch)

            chunks = []
            fetch_batch_size = 100
            for start in range(0, len(all_ids), fetch_batch_size):
                id_batch = all_ids[start : start + fetch_batch_size]
                response = index.fetch(ids=id_batch, namespace=collection_name)
                for chunk_id, vector in response.vectors.items():
                    metadata = dict(vector.metadata or {})
                    text = metadata.pop("document", "") or _text_from_llama_index_node_content(metadata)
                    chunks.append({"id": chunk_id, "text": text, "metadata": metadata})

        return chunks

    def health_check(self) -> dict:
        """Lists indexes then calls _ensure_index() - creates it on first call (billable), a no-op after."""
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        if not self.api_key:
            result["status"] = "unhealthy"
            result["message"] = "API key not configured"
            return result

        try:
            client = self._require_client()
            existing_indexes = [index["name"] for index in client.list_indexes()]
            index_already_existed = self.index_name in existing_indexes

            self._ensure_index()
            stats = self.get_index().describe_index_stats()

            result["status"] = "healthy"
            result["indexes_visible"] = len(existing_indexes)
            result["index_already_existed"] = index_already_existed
            result["total_vector_count"] = stats.get("total_vector_count", 0)
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
