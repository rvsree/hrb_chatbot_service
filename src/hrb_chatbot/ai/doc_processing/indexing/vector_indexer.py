"""Writes chunks into a vector index built with LlamaIndex's VectorStoreIndex (see RAG-ROADMAP.md's Phase 44 entry)."""

import json
from contextlib import nullcontext
from datetime import UTC, datetime

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.vector_stores.pinecone import PineconeVectorStore

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.db_client.langchain_vector_store import COLLECTION_NAME
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("doc_processing.indexing")


def build_chunk_ids(document_id: str, chunk_count: int) -> list[str]:
    return [f"{document_id}:{i}" for i in range(chunk_count)]


def storage_chunk_ids(provider_name: str, document_id: str, chunk_ids: list[str]) -> list[str]:
    """Pinecone prefixes stored ids with f"{document_id}#" (LlamaIndex's
    doing, see RAG-ROADMAP.md's Phase 44 entry) - Chroma does not."""
    if provider_name == "pinecone":
        return [f"{document_id}#{chunk_id}" for chunk_id in chunk_ids]
    return chunk_ids


def _llama_vector_index(vector_store_client) -> VectorStoreIndex:
    # Wraps this project's already-connected client's raw collection/index in
    # LlamaIndex's own class, so it writes into the exact same physical store other code already uses.
    if vector_store_client.PROVIDER_NAME == "pinecone":
        pinecone_index = vector_store_client.get_index()
        llama_vector_store = PineconeVectorStore(pinecone_index=pinecone_index, namespace=COLLECTION_NAME)
    else:
        chroma_collection = vector_store_client.get_collection(COLLECTION_NAME)
        llama_vector_store = ChromaVectorStore(chroma_collection=chroma_collection)

    return VectorStoreIndex.from_vector_store(llama_vector_store)


def _extracted_fields(doc_category: str | None, department: str | None, doc_description: str | None) -> dict:
    # Only include fields with a value - Pinecone's update_metadata() rejects None outright.
    fields = {"doc_category": doc_category, "department": department, "doc_description": doc_description}
    return {key: value for key, value in fields.items() if value is not None}


def _build_nodes(
    document_id: str, chunk_ids: list[str], chunks: list[str], embeddings: list[list[float]], metadatas: list[dict]
) -> list[TextNode]:
    # document_id goes via the SOURCE relationship, not node.metadata - see RAG-ROADMAP.md's Phase 44 entry.
    nodes = []
    for chunk_id, text, embedding, metadata in zip(chunk_ids, chunks, embeddings, metadatas, strict=True):
        node = TextNode(id_=chunk_id, text=text, embedding=embedding, metadata=metadata)
        node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=document_id)
        nodes.append(node)
    return nodes


async def _lookup_existing_chunks(metadata_store, document_id: str) -> tuple[str, list[str], dict | None]:
    """Repo-layer read only - decides nothing, just reports what's there."""
    existing_document = await metadata_store.get_document(document_id)
    if existing_document and existing_document.get("chunk_ids"):
        return "update", json.loads(existing_document["chunk_ids"]), existing_document
    return "insert", [], existing_document


def _build_chunk_metadatas(
    existing_document: dict | None, chunk_count: int, now: str, section_ids: list[str | None] | None = None
) -> list[dict]:
    # Only a re-index's existing_document has these - a first index leaves them for apply_extracted_chunk_metadata().
    extracted_fields = _extracted_fields(
        existing_document.get("doc_category") if existing_document else None,
        existing_document.get("department") if existing_document else None,
        existing_document.get("doc_description") if existing_document else None,
    )
    resolved_section_ids = section_ids if section_ids is not None else [None] * chunk_count
    metadatas = []
    for i in range(chunk_count):
        metadata = {"chunk_index": i, "is_current": True, "indexed_at": now, **extracted_fields}
        # Phase 124 - omitted when None, same reasoning as _extracted_fields():
        # Pinecone's update_metadata() rejects a literal None value.
        if resolved_section_ids[i] is not None:
            metadata["section_id"] = resolved_section_ids[i]
        metadatas.append(metadata)
    return metadatas


def _write_new_vector_chunks(
    vector_store_client,
    resolved_vector_db: str,
    document_id: str,
    old_chunk_ids: list[str],
    new_chunk_ids: list[str],
    chunks: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    """Vector-store write only - delete-then-insert, no metadata-DB calls."""
    # Delete old chunks first - insert_nodes() uses plain add(), not upsert, so a reused id would silently no-op.
    if old_chunk_ids:
        vector_store_client.delete(
            collection_name=COLLECTION_NAME,
            ids=storage_chunk_ids(resolved_vector_db, document_id, old_chunk_ids),
        )

    # Phase 145: this builds the LlamaIndex wrapper directly from the raw
    # chroma collection (_llama_vector_index -> get_collection()), then
    # writes to it via insert_nodes() - entirely outside ChromaDBClient's
    # own methods, so its internal collection_lock never covers this call
    # on its own. Chroma's PersistentClient isn't safe for concurrent
    # access from multiple threads (confirmed - see chroma_client.py's own
    # note); acquire the same lock explicitly here so concurrent document
    # indexing (Phase 145) can't corrupt the local index the way Phase
    # 139's concurrent delete already did once. Pinecone has no such lock
    # (a real concurrent-safe remote service) - nullcontext() is then a
    # true no-op, not an unnecessary serialization point.
    lock = getattr(vector_store_client, "collection_lock", None) or nullcontext()
    with lock:
        llama_index = _llama_vector_index(vector_store_client)
        nodes = _build_nodes(document_id, new_chunk_ids, chunks, embeddings, metadatas)
        llama_index.insert_nodes(nodes)


async def _record_index_success(
    metadata_store,
    document_id: str,
    new_chunk_ids: list[str],
    embedding_model: str | None,
    embedding_dimension: int,
    resolved_vector_db: str,
    chunking_strategy: str | None,
    chunk_size: int | None,
    chunk_overlap: int | None,
) -> int:
    """Metadata-DB write only - the record-of-truth for this index run."""
    return await metadata_store.record_successful_index(
        document_id,
        new_chunk_ids,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        vector_db=resolved_vector_db,
        chunking_strategy=chunking_strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


async def _apply_supersede(
    metadata_store,
    vector_store_client,
    resolved_vector_db: str,
    document_id: str,
    supersedes: str | None,
    now: str,
) -> None:
    """First-index-only business rule plus the metadata/vector-DB writes it requires, kept together."""
    if not supersedes:
        return

    superseded_chunk_ids = await metadata_store.mark_superseded(supersedes, superseded_by=document_id)
    if not superseded_chunk_ids:
        return

    # update_metadata() REPLACES the full dict - chunk_index is parsed from the id, re-supplied for every field.
    old_metadatas = [
        {"chunk_index": int(chunk_id.split(":")[1]), "is_current": False, "indexed_at": now}
        for chunk_id in superseded_chunk_ids
    ]
    vector_store_client.update_metadata(
        collection_name=COLLECTION_NAME,
        ids=storage_chunk_ids(resolved_vector_db, supersedes, superseded_chunk_ids),
        metadatas=old_metadatas,
    )
    logger.info(
        "Document %s superseded by %s - %d old chunk(s) marked is_current=false",
        supersedes,
        document_id,
        len(superseded_chunk_ids),
    )


async def write_chunks(
    document_id: str,
    chunks: list[str],
    embeddings: list[list[float]],
    vector_db: str | None = None,
    embedding_model: str | None = None,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    section_ids: list[str | None] | None = None,
) -> dict:
    """Orchestrates one index run - each step is a single repo-layer call or business rule, not both mixed."""
    gateway = get_db_gateway()
    metadata_store = gateway.metadata_store()
    vector_store_client = gateway.vector_store(provider=vector_db)
    resolved_vector_db = vector_store_client.PROVIDER_NAME

    action, old_chunk_ids, existing_document = await _lookup_existing_chunks(metadata_store, document_id)

    now = datetime.now(UTC).isoformat()
    new_chunk_ids = build_chunk_ids(document_id, len(chunks))
    metadatas = _build_chunk_metadatas(existing_document, len(chunks), now, section_ids)

    _write_new_vector_chunks(
        vector_store_client, resolved_vector_db, document_id, old_chunk_ids, new_chunk_ids, chunks, embeddings, metadatas
    )

    # Stale = existed before but not in the fresh set - reported for the
    # caller, not a separate delete call (already handled above).
    stale_ids = [chunk_id for chunk_id in old_chunk_ids if chunk_id not in new_chunk_ids]
    if stale_ids:
        logger.info("Removed %d stale chunk(s) for document %s", len(stale_ids), document_id)

    # The embeddings this call was given, not a fresh embed call - Module 1's
    # own explicit step (pipeline.py) already computed these once.
    embedding_dimension = len(embeddings[0]) if embeddings else 0

    document_version = await _record_index_success(
        metadata_store, document_id, new_chunk_ids, embedding_model, embedding_dimension,
        resolved_vector_db, chunking_strategy, chunk_size, chunk_overlap,
    )

    # Only on this document's *first* index - no window where the old
    # version is hidden before the new one is live, no repeat on re-index.
    supersedes = existing_document.get("supersedes") if existing_document else None
    if action == "insert":
        await _apply_supersede(metadata_store, vector_store_client, resolved_vector_db, document_id, supersedes, now)

    logger.info(
        "indexing: wrote %d chunk(s) for document %s via LlamaIndex VectorStoreIndex (vector_db=%s)",
        len(chunks),
        document_id,
        resolved_vector_db,
    )

    return {
        "action": action,
        "chunks_indexed": len(chunks),
        "chunks_removed": len(stale_ids),
        "embedding_dimension": embedding_dimension,
        "document_version": document_version,
        # Extra key, not part of a return contract elsewhere - lets
        # pipeline.py reuse these ids without a second DB round-trip.
        "chunk_ids": new_chunk_ids,
    }


async def apply_extracted_chunk_metadata(
    document_id: str,
    chunk_ids: list[str],
    vector_db: str | None,
    doc_category: str | None,
    department: str | None,
    doc_description: str | None,
) -> None:
    """Patch extracted fields onto just-written chunks - only needed after a first index."""
    if not chunk_ids:
        return

    now = datetime.now(UTC).isoformat()
    extracted_fields = _extracted_fields(doc_category, department, doc_description)
    metadatas = [
        {"chunk_index": int(chunk_id.split(":")[1]), "is_current": True, "indexed_at": now, **extracted_fields}
        for chunk_id in chunk_ids
    ]

    vector_store_client = get_db_gateway().vector_store(provider=vector_db)
    vector_store_client.update_metadata(
        collection_name=COLLECTION_NAME,
        ids=storage_chunk_ids(vector_store_client.PROVIDER_NAME, document_id, chunk_ids),
        metadatas=metadatas,
    )
    logger.info(
        "Document %s: patched doc_category/department/doc_description onto %d chunk(s) after first-index extraction",
        document_id,
        len(chunk_ids),
    )
