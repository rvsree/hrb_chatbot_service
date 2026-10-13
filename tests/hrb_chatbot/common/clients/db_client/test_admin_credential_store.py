"""Phase 171: AdminCredentialStore - salted-hash storage/verification, no
real Postgres (_connect() faked with a tiny in-memory table, matching this
project's zero-network-call test guarantee, same seam feedback_store's own
tests use)."""

from src.hrb_chatbot.common.clients.db_client.admin_credential_store import AdminCredentialStore


class _FakeConnection:
    """A tiny in-memory stand-in for the one `admin_credentials` row this
    store ever touches per employee_id - routes by sniffing the SQL verb,
    same shape the real queries use."""

    def __init__(self, table: dict):
        self._table = table
        self._last_select_result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT"):
            (employee_id,) = params
            row = self._table.get(employee_id)
            self._last_select_result = (row["secret_code_hash"], row["secret_code_salt"], row["must_reset"]) if row else None
        elif sql.startswith("INSERT"):
            employee_id, secret_code_hash, secret_code_salt = params
            self._table[employee_id] = {
                "secret_code_hash": secret_code_hash,
                "secret_code_salt": secret_code_salt,
                "must_reset": True,
            }
        elif sql.startswith("UPDATE"):
            secret_code_hash, secret_code_salt, employee_id = params
            self._table[employee_id] = {
                "secret_code_hash": secret_code_hash,
                "secret_code_salt": secret_code_salt,
                "must_reset": False,
            }
        return self

    def fetchone(self):
        return self._last_select_result

    def commit(self):
        pass


def _store_with_fake_table(monkeypatch, table=None):
    store = AdminCredentialStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True  # skip _ensure_table()'s own CREATE TABLE call
    table = table if table is not None else {}
    monkeypatch.setattr(store, "_connect", lambda: _FakeConnection(table))
    return store, table


async def test_get_or_seed_creates_a_row_only_the_first_time(monkeypatch):
    store, table = _store_with_fake_table(monkeypatch)

    first = await store.get_or_seed("ADM001", "one-time-code")
    assert first["must_reset"] is True
    assert "ADM001" in table

    seeded_hash = table["ADM001"]["secret_code_hash"]
    second = await store.get_or_seed("ADM001", "a-totally-different-code")
    assert second["must_reset"] is True
    assert table["ADM001"]["secret_code_hash"] == seeded_hash  # unchanged - already seeded


async def test_verify_secret_code_accepts_the_seeded_one_time_code(monkeypatch):
    store, _table = _store_with_fake_table(monkeypatch)
    await store.get_or_seed("ADM001", "$reeRad")

    assert await store.verify_secret_code("ADM001", "$reeRad") is True


async def test_verify_secret_code_rejects_a_wrong_code(monkeypatch):
    store, _table = _store_with_fake_table(monkeypatch)
    await store.get_or_seed("ADM001", "$reeRad")

    assert await store.verify_secret_code("ADM001", "wrong-code") is False


async def test_verify_secret_code_rejects_empty_or_missing_code(monkeypatch):
    store, _table = _store_with_fake_table(monkeypatch)
    await store.get_or_seed("ADM001", "$reeRad")

    assert await store.verify_secret_code("ADM001", None) is False
    assert await store.verify_secret_code("ADM001", "") is False


async def test_verify_secret_code_on_an_unseeded_employee_id_never_matches_anything(monkeypatch):
    """Regression test for a real bug caught while writing this store: an
    earlier draft of verify_secret_code() called get_or_seed() internally,
    seeding a brand-new row with whatever the caller just typed - so the
    FIRST guess for any not-yet-seeded employee_id always "matched" its own
    seed. verify_secret_code() must only ever look up an existing row, never
    create one."""
    store, table = _store_with_fake_table(monkeypatch)

    assert await store.verify_secret_code("ADM001", "any-first-guess-at-all") is False
    assert "ADM001" not in table


async def test_the_stored_value_is_never_the_plaintext_code(monkeypatch):
    store, table = _store_with_fake_table(monkeypatch)

    await store.get_or_seed("ADM001", "$reeRad")

    assert table["ADM001"]["secret_code_hash"] != "$reeRad"
    assert "reeRad" not in table["ADM001"]["secret_code_hash"]


async def test_set_secret_code_replaces_the_hash_and_clears_must_reset(monkeypatch):
    store, table = _store_with_fake_table(monkeypatch)
    await store.get_or_seed("ADM001", "$reeRad")
    old_hash = table["ADM001"]["secret_code_hash"]

    await store.set_secret_code("ADM001", "a-new-code")

    assert table["ADM001"]["must_reset"] is False
    assert table["ADM001"]["secret_code_hash"] != old_hash
    assert await store.verify_secret_code("ADM001", "a-new-code") is True
    assert await store.verify_secret_code("ADM001", "$reeRad") is False


async def test_two_employees_with_the_same_code_get_different_hashes(monkeypatch):
    """Confirms the salt is actually random per-row, not a fixed constant -
    two identical plaintext codes must not produce identical stored hashes."""
    store, table = _store_with_fake_table(monkeypatch)

    await store.get_or_seed("ADM001", "same-code")
    await store.get_or_seed("ADM002", "same-code")

    assert table["ADM001"]["secret_code_hash"] != table["ADM002"]["secret_code_hash"]
    assert table["ADM001"]["secret_code_salt"] != table["ADM002"]["secret_code_salt"]
