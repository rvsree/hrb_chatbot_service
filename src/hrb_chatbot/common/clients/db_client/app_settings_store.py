"""Phase 257 - a generic runtime key-value settings store, deliberately not
tied to any one feature. First real caller: the live-query LTM capture
threshold. Built generic on purpose - the other pending "editable from
Settings UI" needs (ReAct loop cap, circuit-breaker thresholds, judge-model
provider default) can reuse this same table in their own later phases
instead of each inventing a new one. Same psycopg + asyncio.to_thread()
pattern as every other store in this module. Uses psycopg.sql.Identifier/
SQL to compose the schema-qualified table name (not an f-string) - the
real, idiomatic-psycopg way to handle a dynamic identifier."""

import asyncio
import json

import psycopg
from psycopg import sql

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("app_settings_store")

_SCHEMA = "hrb_platform_settings"
_TABLE = sql.Identifier(_SCHEMA, "app_settings")

CREATE_SCHEMA = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(_SCHEMA))

CREATE_APP_SETTINGS_TABLE = sql.SQL(
    """
CREATE TABLE IF NOT EXISTS {table} (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
)
"""
).format(table=_TABLE)


class AppSettingsStore:
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
            host=self.host, port=self.port, dbname=self.db_name, user=self.user, password=self.password,
        )

    def _ensure_table_sync(self) -> None:
        with self._connect() as conn:
            conn.execute(CREATE_SCHEMA)
            conn.execute(CREATE_APP_SETTINGS_TABLE)
            conn.commit()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        await asyncio.to_thread(self._ensure_table_sync)
        self._table_ready = True

    def _get_setting_sync(self, key: str):
        with self._connect() as conn:
            row = conn.execute(sql.SQL("SELECT value FROM {table} WHERE key = %s").format(table=_TABLE), (key,)).fetchone()
        return row[0] if row is not None else None

    async def get_setting(self, key: str, default):
        """Never raises - any read failure (table not ready yet, DB
        unreachable, key never set) falls back to `default`. This is a
        side-channel lookup on the hot path of a real query, never allowed
        to break the answer it's configuring."""
        try:
            await self._ensure_table()
            with log_backend_call(logger, "postgres", "app_settings.get", key=key):
                value = await asyncio.to_thread(self._get_setting_sync, key)
            return value if value is not None else default
        except Exception as error:
            logger.warning("Could not read setting %r, using default %r: %s", key, default, error)
            return default

    def get_setting_sync(self, key: str, default):
        """Phase 260 - sync counterpart to get_setting(), for callers that
        are themselves synchronous (CircuitBreaker's own ask()-triggered
        calls - same sync/async split reasoning as circuit_breaker.py's own
        module docstring). Same never-raises, fail-to-default contract."""
        try:
            if not self._table_ready:
                self._ensure_table_sync()
                self._table_ready = True
            with log_backend_call(logger, "postgres", "app_settings.get", key=key):
                value = self._get_setting_sync(key)
            return value if value is not None else default
        except Exception as error:
            logger.warning("Could not read setting %r, using default %r: %s", key, default, error)
            return default

    def _set_setting_sync(self, key: str, value, updated_by: str | None) -> None:
        value_json = json.dumps(value)
        with self._connect() as conn:
            conn.execute(
                sql.SQL(
                    "INSERT INTO {table} (key, value, updated_by) VALUES (%s, %s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now(), updated_by = EXCLUDED.updated_by"
                ).format(table=_TABLE),
                (key, value_json, updated_by),
            )
            conn.commit()

    async def set_setting(self, key: str, value, updated_by: str | None = None) -> None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "app_settings.set", key=key):
            await asyncio.to_thread(self._set_setting_sync, key, value, updated_by)
