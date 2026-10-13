"""Phase 170 (round 1): DocMetadataStore - content-hash-driven upsert, no
real Postgres (_connect() faked, matching this project's zero-network-call
test guarantee, same seam feedback_store's own tests use)."""

from src.hrb_chatbot.common.clients.db_client.doc_metadata_store import DocMetadataStore


class _FakeConnection:
    """A tiny in-memory stand-in for the one `doc_metadata` table this
    store touches - routes by sniffing the SQL verb, same shape the real
    queries use."""

    def __init__(self, table: dict):
        self._table = table
        self._next_id = len(table) + 1
        self._last_select_result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT id, content_hash, doc_version"):
            feature_name, doc_type = params
            row = next(
                (r for r in self._table.values() if r["feature_name"] == feature_name and r["doc_type"] == doc_type),
                None,
            )
            self._last_select_result = (row["id"], row["content_hash"], row["doc_version"]) if row else None
        elif sql.startswith("INSERT"):
            feature_name, doc_title, doc_type, s3_bucket, s3_key, source_local_path, content_hash = params
            doc_id = self._next_id
            self._next_id += 1
            self._table[doc_id] = {
                "id": doc_id,
                "feature_name": feature_name,
                "doc_title": doc_title,
                "doc_type": doc_type,
                "doc_version": 1,
                "s3_bucket": s3_bucket,
                "s3_key": s3_key,
                "source_local_path": source_local_path,
                "content_hash": content_hash,
            }
            self._last_select_result = (doc_id,)
        elif sql.startswith("UPDATE doc_metadata SET last_synced_at"):
            pass
        elif sql.startswith("UPDATE doc_metadata SET doc_title"):
            doc_title, doc_type, new_version, s3_bucket, s3_key, source_local_path, content_hash, doc_id = params
            self._table[doc_id].update(
                {
                    "doc_title": doc_title,
                    "doc_type": doc_type,
                    "doc_version": new_version,
                    "s3_bucket": s3_bucket,
                    "s3_key": s3_key,
                    "source_local_path": source_local_path,
                    "content_hash": content_hash,
                }
            )
        return self

    def fetchone(self):
        return self._last_select_result

    def commit(self):
        pass


def _store_with_fake_table(monkeypatch, table=None):
    store = DocMetadataStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True
    table = table if table is not None else {}
    monkeypatch.setattr(store, "_connect", lambda: _FakeConnection(table))
    return store, table


async def test_upsert_inserts_a_new_doc_with_version_1(monkeypatch):
    store, table = _store_with_fake_table(monkeypatch)

    result = await store.upsert_doc(
        feature_name="request-unpaid-leave",
        doc_title="Leave Approval A2A",
        doc_type="design",
        s3_bucket="bucket",
        s3_key="admin-docs/request-unpaid-leave.html",
        source_local_path="docs/dev-reference/leave-approval-a2a-design.html",
        content_hash="hash-v1",
    )

    assert result["changed"] is True
    assert result["doc_version"] == 1
    assert len(table) == 1


async def test_upsert_with_unchanged_content_hash_is_a_no_op(monkeypatch):
    store, table = _store_with_fake_table(monkeypatch)
    await store.upsert_doc(
        feature_name="request-unpaid-leave",
        doc_title="Leave Approval A2A",
        doc_type="design",
        s3_bucket="bucket",
        s3_key="admin-docs/request-unpaid-leave.html",
        source_local_path="docs/dev-reference/leave-approval-a2a-design.html",
        content_hash="hash-v1",
    )

    result = await store.upsert_doc(
        feature_name="request-unpaid-leave",
        doc_title="Leave Approval A2A",
        doc_type="design",
        s3_bucket="bucket",
        s3_key="admin-docs/request-unpaid-leave.html",
        source_local_path="docs/dev-reference/leave-approval-a2a-design.html",
        content_hash="hash-v1",
    )

    assert result["changed"] is False
    assert result["doc_version"] == 1


async def test_upsert_with_a_changed_content_hash_bumps_the_version(monkeypatch):
    store, table = _store_with_fake_table(monkeypatch)
    await store.upsert_doc(
        feature_name="request-unpaid-leave",
        doc_title="Leave Approval A2A",
        doc_type="design",
        s3_bucket="bucket",
        s3_key="admin-docs/request-unpaid-leave.html",
        source_local_path="docs/dev-reference/leave-approval-a2a-design.html",
        content_hash="hash-v1",
    )

    result = await store.upsert_doc(
        feature_name="request-unpaid-leave",
        doc_title="Leave Approval A2A",
        doc_type="design",
        s3_bucket="bucket",
        s3_key="admin-docs/request-unpaid-leave.html",
        source_local_path="docs/dev-reference/leave-approval-a2a-design.html",
        content_hash="hash-v2",
    )

    assert result["changed"] is True
    assert result["doc_version"] == 2
    assert table[result["id"]]["content_hash"] == "hash-v2"


async def test_upsert_keys_by_feature_and_doc_type_not_feature_alone(monkeypatch):
    # Phase 179 - the same feature_name can now have several doc_types
    # (Spec/Architecture/Design/Decisions); each is its own row, not a
    # collision on the old feature_name-only uniqueness.
    store, table = _store_with_fake_table(monkeypatch)

    spec_result = await store.upsert_doc(
        feature_name="admin-secret-code",
        doc_title="Admin Secret Code - Spec",
        doc_type="spec",
        s3_bucket="bucket",
        s3_key="admin-docs/admin-secret-code-spec.html",
        source_local_path="docs/dev-reference/admin-secret-code/spec.html",
        content_hash="hash-spec-v1",
    )
    decisions_result = await store.upsert_doc(
        feature_name="admin-secret-code",
        doc_title="Admin Secret Code - Decisions",
        doc_type="decisions",
        s3_bucket="bucket",
        s3_key="admin-docs/admin-secret-code-decisions.html",
        source_local_path="docs/dev-reference/admin-secret-code/decisions.html",
        content_hash="hash-decisions-v1",
    )

    assert spec_result["changed"] is True
    assert decisions_result["changed"] is True
    assert spec_result["id"] != decisions_result["id"]
    assert len(table) == 2
