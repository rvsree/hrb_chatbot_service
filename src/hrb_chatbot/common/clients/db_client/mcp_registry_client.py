"""Writes to hr_chatbot.app_tracking's existing MCP registry tables, reused as-is."""

import asyncio
import json

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("mcp_registry_client")

UPSERT_SERVER = """
INSERT INTO app_tracking.mcp_server_registry
    (server_id, server_name, server_type, connection_type, base_url, endpoint_path, status, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, now())
ON CONFLICT (server_id) DO UPDATE SET
    server_name = EXCLUDED.server_name, status = EXCLUDED.status, updated_at = now()
"""

UPSERT_TOOL = """
INSERT INTO app_tracking.mcp_tools_registry
    (tool_id, tool_name, server_id, description, tool_definition, input_schema, status, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, 'active', now())
ON CONFLICT (tool_id) DO UPDATE SET
    tool_definition = EXCLUDED.tool_definition, input_schema = EXCLUDED.input_schema, updated_at = now()
"""

UPSERT_CONNECTION = """
INSERT INTO app_tracking.mcp_server_connections
    (server_id, connection_status, health_status, last_health_check_at, last_health_check_result,
     consecutive_failures, last_error_message, last_error_at, updated_at)
VALUES (%s, %s, %s, now(), %s,
    CASE WHEN %s THEN 0 ELSE 1 END, %s, CASE WHEN %s THEN NULL ELSE now() END, now())
ON CONFLICT (server_id) DO UPDATE SET
    connection_status = EXCLUDED.connection_status,
    health_status = EXCLUDED.health_status,
    last_health_check_at = now(),
    last_health_check_result = EXCLUDED.last_health_check_result,
    consecutive_failures = CASE WHEN EXCLUDED.consecutive_failures = 0 THEN 0
                                 ELSE app_tracking.mcp_server_connections.consecutive_failures + 1 END,
    last_error_message = EXCLUDED.last_error_message,
    last_error_at = EXCLUDED.last_error_at,
    updated_at = now()
"""


class McpRegistryClient:
    """Writes to the shared hr_chatbot database - a second Postgres database, not new credentials."""

    def __init__(self, host: str | None = None, port: str | None = None, user: str | None = None, password: str | None = None):
        self.host = read_setting(host, "POSTGRES_DB_HOST")
        self.port = read_setting(port, "POSTGRES_DB_PORT", "5432")
        self.db_name = read_setting(None, "HR_CHATBOT_SHARED_DB_NAME", "hr_chatbot")
        self.user = read_setting(user, "POSTGRES_DB_USER")
        self.password = read_setting(password, "POSTGRES_DB_PASSWORD")

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(host=self.host, port=self.port, dbname=self.db_name, user=self.user, password=self.password, connect_timeout=5)

    def _register_server_sync(self, server_id: str, server_name: str, server_type: str, connection_type: str, base_url: str, endpoint_path: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(UPSERT_SERVER, (server_id, server_name, server_type, connection_type, base_url, endpoint_path, status))
            conn.commit()

    async def register_server(self, server_id: str, server_name: str, server_type: str, connection_type: str, base_url: str, endpoint_path: str, status: str) -> None:
        await asyncio.to_thread(self._register_server_sync, server_id, server_name, server_type, connection_type, base_url, endpoint_path, status)

    def _register_tools_sync(self, server_id: str, tools: list[dict]) -> None:
        with self._connect() as conn:
            for tool in tools:
                tool_id = f"{server_id}:{tool['name']}"
                conn.execute(
                    UPSERT_TOOL,
                    (tool_id, tool["name"], server_id, tool.get("description"),
                     json.dumps(tool), json.dumps(tool.get("inputSchema", {}))),
                )
            conn.commit()

    async def register_tools(self, server_id: str, tools: list[dict]) -> None:
        await asyncio.to_thread(self._register_tools_sync, server_id, tools)

    def _record_connection_attempt_sync(self, server_id: str, success: bool, result: dict, error_message: str | None) -> None:
        # CHECK-constrained by the existing table - 'connected'/'error' and 'healthy'/'unhealthy' are the real values.
        connection_status = "connected" if success else "error"
        health_status = "healthy" if success else "unhealthy"
        with self._connect() as conn:
            conn.execute(
                UPSERT_CONNECTION,
                (server_id, connection_status, health_status, json.dumps(result), success, error_message, success),
            )
            conn.commit()

    async def record_connection_attempt(self, server_id: str, success: bool, result: dict, error_message: str | None = None) -> None:
        await asyncio.to_thread(self._record_connection_attempt_sync, server_id, success, result, error_message)

    @staticmethod
    def _dict_row_factory(cursor):
        columns = [desc.name for desc in cursor.description]
        return lambda values: dict(zip(columns, values, strict=True))

    def _get_connection_status_sync(self, server_id: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute(
                    "SELECT connection_status, consecutive_failures, last_health_check_at "
                    "FROM app_tracking.mcp_server_connections WHERE server_id = %s",
                    (server_id,),
                )
                row = cur.fetchone()
        return row

    async def get_connection_status(self, server_id: str) -> dict | None:
        """Phase 185 - the circuit breaker's pre-flight read. Returns None
        if no row exists yet (e.g. startup registration hasn't run) -
        callers must treat that the same as "unknown, attempt the real
        call," never as "known down."""
        return await asyncio.to_thread(self._get_connection_status_sync, server_id)

    def health_check(self) -> dict:
        result = {"provider": "mcp_registry", "host": self.host, "db_name": self.db_name}
        try:
            with self._connect() as conn:
                count = conn.execute("SELECT COUNT(*) FROM app_tracking.mcp_server_registry").fetchone()[0]
            result["status"] = "healthy"
            result["registered_servers"] = count
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)
        return result
