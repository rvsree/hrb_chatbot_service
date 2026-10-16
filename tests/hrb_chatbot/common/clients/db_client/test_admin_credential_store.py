"""Phase 171: AdminCredentialStore - salted-hash storage/verification, no
real Postgres (_connect() faked with a tiny in-memory table, matching this
project's zero-network-call test guarantee, same seam feedback_store's own
tests use). Milestone 3 adds the lockout columns/queries to this same fake."""

from datetime import UTC, datetime

from src.hrb_chatbot.common.clients.db_client.admin_credential_store import AdminCredentialStore, MAX_FAILED_ATTEMPTS


class _FakeConnection:
    """A tiny in-memory stand-in for the one `admin_credentials` row this
    store ever touches per employee_id - routes by sniffing the SQL verb
    and a few distinguishing substrings, same shape the real queries use."""

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
            if row is None:
                self._last_select_result = None
            else:
                locked_until = row["locked_until"]
                is_locked = locked_until is not None and locked_until > datetime.now(UTC)
                self._last_select_result = (
                    row["secret_code_hash"],
                    row["secret_code_salt"],
                    row["must_reset"],
                    row["failed_attempts"],
                    locked_until,
                    is_locked,
                )
        elif sql.startswith("INSERT"):
            employee_id, secret_code_hash, secret_code_salt = params
            self._table[employee_id] = {
                "secret_code_hash": secret_code_hash,
                "secret_code_salt": secret_code_salt,
                "must_reset": True,
                "failed_attempts": 0,
                "locked_until": None,
            }
        elif sql.startswith("UPDATE") and "failed_attempts = failed_attempts + 1" in sql:
            _max_attempts, candidate_locked_until, employee_id = params
            row = self._table[employee_id]
            row["failed_attempts"] += 1
            if row["failed_attempts"] >= MAX_FAILED_ATTEMPTS:
                row["locked_until"] = candidate_locked_until
        elif sql.startswith("UPDATE") and "must_reset = TRUE" in sql:
            secret_code_hash, secret_code_salt, employee_id = params
            self._table[employee_id] = {
                "secret_code_hash": secret_code_hash,
                "secret_code_salt": secret_code_salt,
                "must_reset": True,
                "failed_attempts": 0,
                "locked_until": None,
            }
        elif sql.startswith("UPDATE") and "failed_attempts = 0, locked_until = NULL" in sql:
            (employee_id,) = params
            row = self._table[employee_id]
            row["failed_attempts"] = 0
            row["locked_until"] = None
        elif sql.startswith("UPDATE"):
            secret_code_hash, secret_code_salt, employee_id = params
            row = self._table[employee_id]
            row["secret_code_hash"] = secret_code_hash
            row["secret_code_salt"] = secret_code_salt
            row["must_reset"] = False
        return self

    def fetchone(self):
        return self._last_select_result

    def commit(self):
        pass


def _store_with_fake_table(monkeypatch, table=None):
    store = AdminCredentialStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True  # skip _ensure_table()'s own CREATE TABLE/ALTER TABLE calls
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


# --- Milestone 3: lockout, recovery, auto-expiry ---------------------------


async def test_new_credential_starts_unlocked_with_zero_failed_attempts(monkeypatch):
    store, _table = _store_with_fake_table(monkeypatch)

    credential = await store.get_or_seed("ADM001", "$reeRad")

    assert credential["failed_attempts"] == 0
    assert credential["locked_until"] is None
    assert credential["is_locked"] is False


async def test_failed_attempts_below_threshold_does_not_lock(monkeypatch):
    store, _table = _store_with_fake_table(monkeypatch)
    await store.get_or_seed("ADM001", "$reeRad")

    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        await store.record_failed_attempt("ADM001")

    credential = await store.get_credential("ADM001")
    assert credential["failed_attempts"] == MAX_FAILED_ATTEMPTS - 1
    assert credential["is_locked"] is False


async def test_reaching_max_failed_attempts_locks_the_account(monkeypatch):
    store, _table = _store_with_fake_table(monkeypatch)
    await store.get_or_seed("ADM001", "$reeRad")

    for _ in range(MAX_FAILED_ATTEMPTS):
        await store.record_failed_attempt("ADM001")

    credential = await store.get_credential("ADM001")
    assert credential["failed_attempts"] == MAX_FAILED_ATTEMPTS
    assert credential["is_locked"] is True
    assert credential["locked_until"] is not None


async def test_reset_failed_attempts_clears_the_lock(monkeypatch):
    store, _table = _store_with_fake_table(monkeypatch)
    await store.get_or_seed("ADM001", "$reeRad")
    for _ in range(MAX_FAILED_ATTEMPTS):
        await store.record_failed_attempt("ADM001")

    await store.reset_failed_attempts("ADM001")

    credential = await store.get_credential("ADM001")
    assert credential["failed_attempts"] == 0
    assert credential["locked_until"] is None
    assert credential["is_locked"] is False


async def test_force_unlock_and_require_reset_replaces_code_and_clears_lock(monkeypatch):
    store, _table = _store_with_fake_table(monkeypatch)
    await store.get_or_seed("ADM001", "$reeRad")
    for _ in range(MAX_FAILED_ATTEMPTS):
        await store.record_failed_attempt("ADM001")
    assert (await store.get_credential("ADM001"))["is_locked"] is True

    await store.force_unlock_and_require_reset("ADM001", "recovery-code")

    credential = await store.get_credential("ADM001")
    assert credential["is_locked"] is False
    assert credential["failed_attempts"] == 0
    assert credential["must_reset"] is True
    assert await store.verify_secret_code("ADM001", "recovery-code") is True
    # The old (possibly forgotten) code no longer works - it was replaced, not just unlocked.
    assert await store.verify_secret_code("ADM001", "$reeRad") is False
