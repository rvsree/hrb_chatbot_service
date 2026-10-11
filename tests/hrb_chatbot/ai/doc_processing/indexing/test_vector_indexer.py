"""Tests for write_chunks() (ai/doc_processing/indexing/vector_indexer.py).

Covers the highest-value logic in the indexing pipeline: insert vs. update,
cleaning up stale chunks when a re-indexed document shrinks (guards against
orphaned vectors), and the supersede-flip. write_chunks() is async, so
tests are too (pytest-asyncio's asyncio_mode=auto).

Phase 44 reverted write_chunks() from LangChain's index()/SQLRecordManager
back to LlamaIndex's VectorStoreIndex.insert_nodes() (course-ware
alignment, reversing Phase 17). LlamaIndex needs a real chromadb.Collection/
pinecone.Index object - it can't be satisfied by a plain-dict fake the way
a raw upsert() call could. EphemeralChromaVectorStore below (real, in-memory
chromadb.EphemeralClient() - no disk, no network) stands in for
ChromaDBClient, same reasoning this project already applies everywhere
else to keep real API cost out of pytest. Unlike Phase 17's content-hash
ids, chunk ids are positional again (build_chunk_ids()) - LlamaIndex's
insert_nodes() has no skip-if-unchanged, so a re-index always rewrites
every chunk at its position, not just changed ones (a known, accepted
regression - see this phase's RAG-ROADMAP.md entry)."""

import uuid

import chromadb

from src.hrb_chatbot.ai.doc_processing.indexing import vector_indexer
from src.hrb_chatbot.common.clients.db_client.base_vector_db_client import BaseVectorDBClient
from tests.conftest import FakeDBGateway, FakeMetadataStore


class EphemeralChromaVectorStore(BaseVectorDBClient):
    """A real, in-memory ChromaDB client standing in for ChromaDBClient in
    tests. get_collection() is what LlamaIndex's ChromaVectorStore needs;
    delete()/update_metadata() satisfy the rest of write_chunks()'s own
    BaseVectorDBClient calls - all three operate on the same real collection."""

    PROVIDER_NAME = "chromadb"

    def __init__(self):
        self._client = chromadb.EphemeralClient()
        # chromadb's "ephemeral" mode still shares collection storage by name
        # across separate EphemeralClient() instances within the same test
        # process - a random suffix per instance is what actually isolates
        # one test from another, not just constructing a fresh client.
        self._suffix = uuid.uuid4().hex

    def get_collection(self, collection_name: str):
        return self._client.get_or_create_collection(f"{collection_name}_{self._suffix}")

    def upsert(self, collection_name, ids, documents, embeddings, metadatas=None):
        raise NotImplementedError("write_chunks() writes new chunks via LlamaIndex now, not upsert() directly")

    def query(self, collection_name, query_embedding, top_k=5, where=None):
        raise NotImplementedError("not used by write_chunks()")

    def delete(self, collection_name: str, ids: list[str]) -> None:
        self.get_collection(collection_name).delete(ids=ids)

    def update_metadata(self, collection_name: str, ids: list[str], metadatas: list[dict]) -> None:
        self.get_collection(collection_name).update(ids=ids, metadatas=metadatas)

    def get_all_chunks(self, collection_name: str) -> list[dict]:
        raise NotImplementedError("not used by write_chunks()")

    def health_check(self) -> dict:
        return {"provider": self.PROVIDER_NAME, "status": "healthy"}

    def chunk_ids_present(self, collection_name: str) -> set[str]:
        # Test helper only, not part of BaseVectorDBClient - the real ids
        # actually stored right now, for asserting stale chunks are gone.
        return set(self.get_collection(collection_name).get()["ids"])

    def metadata_for(self, collection_name: str, chunk_id: str) -> dict:
        # Test helper only - one chunk's real, current metadata.
        result = self.get_collection(collection_name).get(ids=[chunk_id])
        return result["metadatas"][0]


def _new_setup():
    """One real, isolated ephemeral chromadb collection wired into
    write_chunks() via monkeypatch-free fakes - returns (metadata_store,
    vector_store, gateway)."""
    vector_store = EphemeralChromaVectorStore()
    metadata_store = FakeMetadataStore()
    gateway = FakeDBGateway(vector_store=vector_store, metadata_store=metadata_store)
    return metadata_store, vector_store, gateway


async def test_first_index_of_a_document_is_reported_as_insert(monkeypatch):
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    result = await vector_indexer.write_chunks("doc-1", ["alpha", "beta"], [[0.1], [0.2]])

    assert result["action"] == "insert"
    assert result["chunks_indexed"] == 2
    assert result["chunks_removed"] == 0
    assert result["embedding_dimension"] == 1
    assert result["document_version"] == 2


async def test_reindexing_the_same_document_is_reported_as_update(monkeypatch):
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    await vector_indexer.write_chunks("doc-1", ["alpha"], [[0.1]])
    result = await vector_indexer.write_chunks("doc-1", ["alpha v2"], [[0.1]])

    assert result["action"] == "update"


async def test_reindexing_with_identical_content_still_rewrites_every_chunk(monkeypatch):
    """Unlike Phase 17's LangChain index(), LlamaIndex's insert_nodes() has
    no skip-if-unchanged - a re-index always rewrites every chunk at its
    position, even when the content didn't change. A known, accepted
    regression (see this phase's RAG-ROADMAP.md entry), not a bug."""
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    await vector_indexer.write_chunks("doc-1", ["alpha", "beta"], [[0.1], [0.2]])
    result = await vector_indexer.write_chunks("doc-1", ["alpha", "beta"], [[0.1], [0.2]])

    assert result["chunks_indexed"] == 2
    assert result["chunks_removed"] == 0


async def test_reindexing_a_shrunken_document_deletes_the_now_stale_chunks(monkeypatch):
    """Core correctness case: a document that shrinks from 3 chunks to 1
    must not leave the extra 2 sitting in the vector store forever."""
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    await vector_indexer.write_chunks("doc-1", ["alpha", "beta", "gamma"], [[0.1], [0.2], [0.3]])
    assert len(vector_store.chunk_ids_present(vector_indexer.COLLECTION_NAME)) == 3

    result = await vector_indexer.write_chunks("doc-1", ["alpha v2"], [[0.1]])

    assert result["action"] == "update"
    assert result["chunks_indexed"] == 1
    assert result["chunks_removed"] == 2
    # Proof beyond the reported numbers: only 1 chunk should actually
    # remain in the real vector store (guards against a report that looks
    # correct while masking a real double-execution bug).
    assert len(vector_store.chunk_ids_present(vector_indexer.COLLECTION_NAME)) == 1


async def test_new_chunks_are_tagged_is_current_true_with_a_timestamp(monkeypatch):
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    await vector_indexer.write_chunks("doc-1", ["alpha"], [[0.1]])

    metadata = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, "doc-1:0")
    assert metadata["is_current"] is True
    assert metadata["indexed_at"]  # a real timestamp string, not empty/missing
    assert metadata["chunk_index"] == 0
    # document_id is set via the node's SOURCE relationship, not a plain
    # metadata field (see vector_indexer._build_nodes()'s docstring) -
    # confirming it still reads back correctly, not silently lost/overwritten.
    assert metadata["document_id"] == "doc-1"


async def test_chunk_ids_are_deterministic_by_document_and_position():
    assert vector_indexer.build_chunk_ids("doc-1", 3) == ["doc-1:0", "doc-1:1", "doc-1:2"]


async def test_storage_chunk_ids_prefixes_only_for_pinecone():
    chunk_ids = ["doc-1:0", "doc-1:1"]
    assert vector_indexer.storage_chunk_ids("chromadb", "doc-1", chunk_ids) == chunk_ids
    assert vector_indexer.storage_chunk_ids("pinecone", "doc-1", chunk_ids) == ["doc-1#doc-1:0", "doc-1#doc-1:1"]


async def test_superseding_document_flips_the_old_documents_chunks_to_not_current(monkeypatch):
    """Core correctness case for document versioning: once the new document
    (doc-2, which supersedes doc-1) successfully indexes, doc-1's chunks
    must be marked is_current=false in both SQL and the vector store - not
    deleted, but excluded from normal retrieval. chunk_index must survive
    the flip too - update_metadata() replaces the full metadata dict, so a
    dropped field here would silently vanish, not just fail loudly."""
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy-v1.pdf", "data/uploads/doc-1/policy-v1.pdf")
    await vector_indexer.write_chunks("doc-1", ["old chunk a", "old chunk b"], [[0.1], [0.2]])

    await metadata_store.create_document(
        "doc-2", "policy-v2.pdf", "data/uploads/doc-2/policy-v2.pdf", supersedes="doc-1"
    )
    await vector_indexer.write_chunks("doc-2", ["new chunk a"], [[0.3]])

    old_document = await metadata_store.get_document("doc-1")
    assert old_document["is_current"] is False
    assert old_document["superseded_by"] == "doc-2"

    for chunk_id in ("doc-1:0", "doc-1:1"):
        metadata = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, chunk_id)
        assert metadata["is_current"] is False
        assert metadata["document_id"] == "doc-1"
    assert "doc-1:0" in vector_store.chunk_ids_present(vector_indexer.COLLECTION_NAME)  # still present, not deleted

    new_metadata = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, "doc-2:0")
    assert new_metadata["is_current"] is True


async def test_reindexing_a_document_does_not_repeat_the_supersede_flip(monkeypatch):
    """The supersede propagation only runs on the *first* successful index
    (action == "insert") - re-indexing doc-2 again must not re-process
    doc-1, which by then may have been re-uploaded or deleted."""
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy-v1.pdf", "data/uploads/doc-1/policy-v1.pdf")
    await vector_indexer.write_chunks("doc-1", ["old chunk"], [[0.1]])

    await metadata_store.create_document(
        "doc-2", "policy-v2.pdf", "data/uploads/doc-2/policy-v2.pdf", supersedes="doc-1"
    )
    await vector_indexer.write_chunks("doc-2", ["new chunk"], [[0.2]])
    # Manually restore doc-1 to current, as if it were a fresh, unrelated
    # upload again - a second index of doc-2 must NOT flip it back to false.
    metadata_store.documents["doc-1"]["is_current"] = True

    await vector_indexer.write_chunks("doc-2", ["new chunk v2"], [[0.2]])

    assert metadata_store.documents["doc-1"]["is_current"] is True


async def test_first_index_writes_chunks_with_no_doc_category_fields_yet(monkeypatch):
    """Phase 19: a first index doesn't know doc_category/department/doc_description
    yet (extraction hasn't run - see pipeline.py), so those keys are simply
    absent from the chunk metadata, not present-with-null."""
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    result = await vector_indexer.write_chunks("doc-1", ["alpha"], [[0.1]])

    metadata = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, result["chunk_ids"][0])
    assert "doc_category" not in metadata
    assert "department" not in metadata
    assert "doc_description" not in metadata


async def test_reindex_carries_forward_doc_category_fields_already_known_from_sql(monkeypatch):
    """Phase 19: on a re-index, doc_category/department/doc_description are
    already sitting in existing_document (extracted on the first index) -
    write_chunks() must put them straight into the new chunk metadata, no
    follow-up call needed."""
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    await vector_indexer.write_chunks("doc-1", ["alpha"], [[0.1]])
    metadata_store.documents["doc-1"]["doc_category"] = "benefits"
    metadata_store.documents["doc-1"]["department"] = "HR"
    metadata_store.documents["doc-1"]["doc_description"] = "401k"

    result = await vector_indexer.write_chunks("doc-1", ["alpha v2"], [[0.1]])

    metadata = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, result["chunk_ids"][0])
    assert metadata["doc_category"] == "benefits"
    assert metadata["department"] == "HR"
    assert metadata["doc_description"] == "401k"


async def test_apply_extracted_chunk_metadata_patches_chunks_after_first_index(monkeypatch):
    """Phase 19: the follow-up call pipeline.py makes once extraction
    finishes on a document's first index - every existing field (chunk_index,
    is_current, indexed_at) must survive the replace, not just the three new
    ones (same lesson as the supersede-flip test above)."""
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    result = await vector_indexer.write_chunks("doc-1", ["alpha", "beta"], [[0.1], [0.2]])

    await vector_indexer.apply_extracted_chunk_metadata(
        "doc-1",
        result["chunk_ids"],
        None,
        doc_category="benefits",
        department="HR",
        doc_description="401k",
    )

    for chunk_id in result["chunk_ids"]:
        metadata = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, chunk_id)
        assert metadata["doc_category"] == "benefits"
        assert metadata["department"] == "HR"
        assert metadata["doc_description"] == "401k"
        assert metadata["is_current"] is True
        assert metadata["document_id"] == "doc-1"


async def test_apply_extracted_chunk_metadata_omits_fields_extraction_could_not_determine(monkeypatch):
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    result = await vector_indexer.write_chunks("doc-1", ["alpha"], [[0.1]])

    await vector_indexer.apply_extracted_chunk_metadata(
        "doc-1", result["chunk_ids"], None, doc_category=None, department=None, doc_description=None
    )

    metadata = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, result["chunk_ids"][0])
    assert "doc_category" not in metadata
    assert "department" not in metadata
    assert "doc_description" not in metadata


async def test_section_ids_are_stored_as_chunk_metadata_when_given(monkeypatch):
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    await vector_indexer.write_chunks(
        "doc-1", ["alpha", "beta"], [[0.1], [0.2]], section_ids=["eligibility", "eligibility/employee-eligibility"]
    )

    first = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, "doc-1:0")
    second = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, "doc-1:1")
    assert first["section_id"] == "eligibility"
    assert second["section_id"] == "eligibility/employee-eligibility"


async def test_section_id_is_omitted_when_not_given(monkeypatch):
    # Pinecone's update_metadata() rejects a literal None value - omitted entirely, same as doc_category etc.
    metadata_store, vector_store, gateway = _new_setup()
    monkeypatch.setattr(vector_indexer, "get_db_gateway", lambda: gateway)

    await metadata_store.create_document("doc-1", "policy.pdf", "data/uploads/doc-1/policy.pdf")
    await vector_indexer.write_chunks("doc-1", ["alpha"], [[0.1]])

    metadata = vector_store.metadata_for(vector_indexer.COLLECTION_NAME, "doc-1:0")
    assert "section_id" not in metadata
