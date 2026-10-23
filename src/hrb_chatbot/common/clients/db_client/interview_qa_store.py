"""Phase 187 - Interview Q&A as real, editable rows, not a metadata mirror
of a static file. Same psycopg + asyncio.to_thread() pattern as every
other store here, but with real create/update/delete - this content is
genuinely edited through the admin UI, not just synced one-way from a
source file."""

import asyncio
import json

import psycopg

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("interview_qa_store")

# Phase 251 - schema-per-domain migration, see resources/db_scripts/schema_migration.sql.
_SCHEMA = "hrb_interview_qa"

CREATE_INTERVIEW_QA_TABLE = """
CREATE TABLE IF NOT EXISTS interview_qa_cards (
    id SERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    topic_order INTEGER NOT NULL DEFAULT 0,
    card_order INTEGER NOT NULL DEFAULT 0,
    question TEXT NOT NULL,
    hint TEXT,
    concept TEXT,
    situation TEXT,
    task TEXT,
    action TEXT,
    result TEXT,
    project_link TEXT,
    leadership_angle TEXT,
    trade_offs JSONB NOT NULL DEFAULT '[]',
    keywords JSONB NOT NULL DEFAULT '[]',
    tech_stack JSONB NOT NULL DEFAULT '[]',
    feature_references JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CREATE_TOPIC_INDEX = "CREATE INDEX IF NOT EXISTS idx_interview_qa_topic ON interview_qa_cards(topic_order, card_order)"

_JSON_FIELDS = ("trade_offs", "keywords", "tech_stack", "feature_references")
_TEXT_FIELDS = (
    "topic",
    "question",
    "hint",
    "concept",
    "situation",
    "task",
    "action",
    "result",
    "project_link",
    "leadership_angle",
)


class InterviewQaStore:
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
            conn.execute(CREATE_INTERVIEW_QA_TABLE)
            conn.execute(CREATE_TOPIC_INDEX)
            conn.commit()

    async def _ensure_table(self) -> None:
        if self._table_ready:
            return
        await asyncio.to_thread(self._ensure_table_sync)
        self._table_ready = True

    @staticmethod
    def _dict_row_factory(cursor):
        columns = [desc.name for desc in cursor.description]
        return lambda values: dict(zip(columns, values, strict=True))

    @staticmethod
    def _stringify_timestamps(row: dict) -> dict:
        row["created_at"] = row["created_at"].isoformat()
        row["updated_at"] = row["updated_at"].isoformat()
        return row

    def _list_cards_sync(self, topic: str | None) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                if topic:
                    cur.execute(
                        "SELECT * FROM interview_qa_cards WHERE topic = %s ORDER BY topic_order, card_order", (topic,)
                    )
                else:
                    cur.execute("SELECT * FROM interview_qa_cards ORDER BY topic_order, card_order")
                rows = cur.fetchall()
        return [self._stringify_timestamps(row) for row in rows]

    async def list_cards(self, topic: str | None = None) -> list[dict]:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "interview_qa_cards.list", topic=topic):
            return await asyncio.to_thread(self._list_cards_sync, topic)

    def _get_card_sync(self, card_id: int) -> dict | None:
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                cur.execute("SELECT * FROM interview_qa_cards WHERE id = %s", (card_id,))
                row = cur.fetchone()
        return self._stringify_timestamps(row) if row else None

    async def get_card(self, card_id: int) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "interview_qa_cards.get", card_id=card_id):
            return await asyncio.to_thread(self._get_card_sync, card_id)

    def _create_card_sync(self, fields: dict) -> dict:
        columns = [*_TEXT_FIELDS, "topic_order", "card_order", *_JSON_FIELDS]
        values = []
        for column in columns:
            value = fields.get(column)
            values.append(json.dumps(value) if column in _JSON_FIELDS else value)
        placeholders = ", ".join(["%s"] * len(columns))
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                # columns come only from the fixed _TEXT_FIELDS/_JSON_FIELDS
                # module constants above, never from request data; every
                # actual value is still %s-parameterized below.
                cur.execute(
                    f"INSERT INTO interview_qa_cards ({', '.join(columns)}) VALUES ({placeholders}) RETURNING *",  # nosec B608
                    values,
                )
                row = cur.fetchone()
            conn.commit()
        return self._stringify_timestamps(row)

    async def create_card(self, fields: dict) -> dict:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "interview_qa_cards.create", question=fields.get("question")):
            return await asyncio.to_thread(self._create_card_sync, fields)

    def _update_card_sync(self, card_id: int, fields: dict) -> dict | None:
        columns = [*_TEXT_FIELDS, "topic_order", "card_order", *_JSON_FIELDS]
        set_clause = ", ".join(f"{column} = %s" for column in columns)
        values = []
        for column in columns:
            value = fields.get(column)
            values.append(json.dumps(value) if column in _JSON_FIELDS else value)
        values.append(card_id)
        with self._connect() as conn:
            with conn.cursor(row_factory=self._dict_row_factory) as cur:
                # set_clause's column names are the same fixed constants as
                # above, never request data; values stay %s-parameterized.
                cur.execute(
                    f"UPDATE interview_qa_cards SET {set_clause}, updated_at = now() WHERE id = %s RETURNING *",  # nosec B608
                    values,
                )
                row = cur.fetchone()
            conn.commit()
        return self._stringify_timestamps(row) if row else None

    async def update_card(self, card_id: int, fields: dict) -> dict | None:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "interview_qa_cards.update", card_id=card_id):
            return await asyncio.to_thread(self._update_card_sync, card_id, fields)

    def _delete_card_sync(self, card_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM interview_qa_cards WHERE id = %s", (card_id,))
            conn.commit()
            return cur.rowcount > 0

    async def delete_card(self, card_id: int) -> bool:
        await self._ensure_table()
        with log_backend_call(logger, "postgres", "interview_qa_cards.delete", card_id=card_id):
            return await asyncio.to_thread(self._delete_card_sync, card_id)

    def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "host": self.host, "port": self.port, "db_name": self.db_name}

        if not self.host:
            result["status"] = "unhealthy"
            result["message"] = "POSTGRES_DB_HOST not set"
            return result

        try:
            with self._connect() as conn:
                conn.execute(CREATE_INTERVIEW_QA_TABLE)
                conn.commit()
                row = conn.execute("SELECT count(*) FROM interview_qa_cards").fetchone()
            result["status"] = "healthy"
            result["cards_stored"] = row[0]
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
