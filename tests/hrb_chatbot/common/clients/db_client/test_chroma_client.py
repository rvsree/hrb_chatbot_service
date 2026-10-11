"""Tests for ChromaDBClient.get_all_chunks() (Phase 131) - real embedded
ChromaDB against a pytest tmp_path, no network, matching this project's
existing real-but-isolated-backend testing convention."""

import threading

from src.hrb_chatbot.common.clients.db_client.chroma_client import ChromaDBClient


def _new_client(tmp_path):
    return ChromaDBClient(mode="persistent", persist_dir=str(tmp_path), collection_name="test_collection")


def test_get_all_chunks_returns_every_chunk_with_text_and_metadata(tmp_path):
    client = _new_client(tmp_path)
    client.upsert(
        "test_collection",
        ids=["chunk-1", "chunk-2"],
        documents=["first chunk text", "second chunk text"],
        embeddings=[[0.1, 0.2], [0.3, 0.4]],
        metadatas=[{"doc_id": "doc-1"}, {"doc_id": "doc-1"}],
    )

    chunks = client.get_all_chunks("test_collection")

    assert {chunk["id"] for chunk in chunks} == {"chunk-1", "chunk-2"}
    by_id = {chunk["id"]: chunk for chunk in chunks}
    assert by_id["chunk-1"]["text"] == "first chunk text"
    assert by_id["chunk-1"]["metadata"] == {"doc_id": "doc-1"}


def test_get_all_chunks_on_empty_collection_returns_empty_list(tmp_path):
    client = _new_client(tmp_path)
    client.get_collection("test_collection")  # creates it, still empty

    assert client.get_all_chunks("test_collection") == []


def test_concurrent_upserts_from_multiple_threads_do_not_corrupt_the_index(tmp_path):
    """Phase 145 - the real bug this closes: chromadb.PersistentClient is
    SQLite-backed and not safe for concurrent access from multiple
    threads. Confirmed live: the user's own local index was corrupted
    ("Error finding id") after Phase 139's asyncio.to_thread() bulk-delete
    fix let concurrent deletes reach this client from separate OS threads
    simultaneously. collection_lock (this phase) serializes every real
    chromadb call - this test fires real upserts from 5 real threads at
    once (same concurrency shape asyncio.to_thread() produces) and asserts
    every chunk lands intact, nothing raises, and nothing corrupts."""
    client = _new_client(tmp_path)
    errors = []

    def _upsert_one(index: int) -> None:
        try:
            client.upsert(
                "test_collection",
                ids=[f"chunk-{index}"],
                documents=[f"document text {index}"],
                embeddings=[[float(index), 0.0]],
                metadatas=[{"doc_id": f"doc-{index}"}],
            )
        except Exception as error:  # noqa: BLE001 - captured for the assertion below, not swallowed
            errors.append(error)

    threads = [threading.Thread(target=_upsert_one, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    chunks = client.get_all_chunks("test_collection")
    assert {chunk["id"] for chunk in chunks} == {f"chunk-{i}" for i in range(5)}
