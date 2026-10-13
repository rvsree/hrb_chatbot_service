"""Phase 171 - the admin secret code's real storage: salted SHA-256 (stdlib
hashlib/secrets/hmac only - no new dependency), same psycopg + asyncio.to_thread()
pattern as feedback_store.py. Replaces Phase 169's plaintext literal in
known_personas.py."""

import asyncio
import hashlib
import hmac
import secrets

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("admin_credential_store")

CREATE_ADMIN_CREDENTIALS_TABLE = """
CREATE TABLE IF NOT EXISTS admin_credentials (
    employee_id TEXT PRIMARY KEY,
    secret_code_hash TEXT NOT NULL,
    secret_code_salt TEXT NOT NULL,
    must_reset BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _hash_secret_code(secret_code: str, salt: str) -> str:
    return hashlib.sha256((salt + secret_code).encode()).hexdigest()


class AdminCredentialStore:
    """Stores and verifies admin secret codes in Postgres - never the
    plaintext code itself, only a salted hash."""

    PROVIDER_NAME = "postgres"
    ENV_KEY = "POSTGRES_DB_HOST"

    DEFAULT_PORT = "5432"

    def __init__(
        self,
        host: str | None = None,
        port: str | None = None,
        db_name: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        self.host = read_setting(host, "POSTGRES_DB_HOST")
        self.port = read_setting(port, "POSTGRES_DB_PORT", self.DEFAULT_PORT)
        self.db_name = read_setting(db_name, "POSTGRES_DB_NAME")
        self.user = read_setting(user, "POSTGRES_DB_USER")
        self.password = read_setting(password, "POSTGRES_DB_PASSWORD")

        if not self.host:
            logger.warning("[POSTGRES] POSTGRES_DB_HOST not set")

        self._table_ready = False

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(
            host=self.host, port=self.port, dbname=self.db_name, user=self.user, password=self.password
        )

    def _ensure_table_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_ADMIN_CREDENTIALS_TABLE)
            conn.commit()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        await asyncio.to_thread(self._ensure_table_sync)
        self._table_ready = True

    def _get_credential_sync(self, employee_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT secret_code_hash, secret_code_salt, must_reset FROM admin_credentials WHERE employee_id = %s",
                (employee_id,),
            ).fetchone()
            if row is None:
                return None
            return {"secret_code_hash": row[0], "secret_code_salt": row[1], "must_reset": row[2]}

    async def get_credential(self, employee_id: str) -> dict | None:
        """Plain lookup - never inserts. Deliberately separate from
        get_or_seed() below: verify_secret_code() must never silently seed
        a row using whatever the caller just typed, or a wrong first guess
        on an un-seeded employee_id would seed-and-match itself."""
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "admin_credentials.get_credential", employee_id=employee_id):
            return await asyncio.to_thread(self._get_credential_sync, employee_id)

    def _insert_seed_sync(self, employee_id: str, default_secret_code: str) -> dict:
        salt = secrets.token_hex(16)
        secret_code_hash = _hash_secret_code(default_secret_code, salt)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO admin_credentials (employee_id, secret_code_hash, secret_code_salt, must_reset) "
                "VALUES (%s, %s, %s, TRUE)",
                (employee_id, secret_code_hash, salt),
            )
            conn.commit()
        logger.info("Seeded one-time admin secret code for employee_id=%s", employee_id)
        return {"secret_code_hash": secret_code_hash, "secret_code_salt": salt, "must_reset": True}

    async def get_or_seed(self, employee_id: str, default_secret_code: str) -> dict:
        """Idempotent: seeds a one-time code only if this employee_id has no
        row yet, otherwise returns the existing row unchanged. Only ever
        called with a known-safe default (the login route's own
        ADMIN_ONE_TIME_SEED_SECRET_CODE constant) - never with a value the
        caller just typed in."""
        existing = await self.get_credential(employee_id)
        if existing is not None:
            return existing
        with log_backend_call(logger, "postgres", "admin_credentials.seed", employee_id=employee_id):
            return await asyncio.to_thread(self._insert_seed_sync, employee_id, default_secret_code)

    async def verify_secret_code(self, employee_id: str, candidate: str | None) -> bool:
        if not candidate:
            return False
        credential = await self.get_credential(employee_id)
        if credential is None:
            return False
        expected_hash = _hash_secret_code(candidate, credential["secret_code_salt"])
        return hmac.compare_digest(expected_hash, credential["secret_code_hash"])

    def _set_secret_code_sync(self, employee_id: str, new_secret_code: str) -> None:
        salt = secrets.token_hex(16)
        secret_code_hash = _hash_secret_code(new_secret_code, salt)
        with self._connect() as conn:
            conn.execute(
                "UPDATE admin_credentials SET secret_code_hash = %s, secret_code_salt = %s, "
                "must_reset = FALSE, updated_at = now() WHERE employee_id = %s",
                (secret_code_hash, salt, employee_id),
            )
            conn.commit()

    async def set_secret_code(self, employee_id: str, new_secret_code: str) -> None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "admin_credentials.set_secret_code", employee_id=employee_id):
            await asyncio.to_thread(self._set_secret_code_sync, employee_id, new_secret_code)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_ADMIN_CREDENTIALS_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM admin_credentials").fetchone()
            result["status"] = "healthy"
            result["admin_credentials_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
