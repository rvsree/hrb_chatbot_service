"""Tests for Phase 137's production lockdown - chromadb/sqlite are local-disk
stores, never shared across App Runner's multiple instances or reachable by
the separate Lambda ingestion worker, so a request/default that resolves to
either must be rejected when APP_ENVIRONMENT=production."""

import pytest

from src.hrb_chatbot.common.clients.db_client import db_gateway as db_gateway_module
from src.hrb_chatbot.common.clients.db_client.db_gateway import DBGateway


def test_chromadb_is_rejected_in_production(monkeypatch):
    monkeypatch.setattr(db_gateway_module, "get_app_environment", lambda: "production")

    with pytest.raises(ValueError, match="local-disk store"):
        DBGateway().vector_store(provider="chromadb")


def test_sqlite_is_rejected_in_production(monkeypatch):
    monkeypatch.setattr(db_gateway_module, "get_app_environment", lambda: "production")

    with pytest.raises(ValueError, match="local-disk store"):
        DBGateway().metadata_store(provider="sqlite")


def test_chromadb_still_works_outside_production(monkeypatch):
    monkeypatch.setattr(db_gateway_module, "get_app_environment", lambda: "development")

    client = DBGateway().vector_store(provider="chromadb")

    assert client is not None


def test_sqlite_still_works_outside_production(monkeypatch):
    monkeypatch.setattr(db_gateway_module, "get_app_environment", lambda: "development")

    client = DBGateway().metadata_store(provider="sqlite")

    assert client is not None


def test_pinecone_is_unaffected_by_the_production_guard(monkeypatch):
    monkeypatch.setattr(db_gateway_module, "get_app_environment", lambda: "production")

    client = DBGateway().vector_store(provider="pinecone")

    assert client is not None


def test_postgres_is_unaffected_by_the_production_guard(monkeypatch):
    monkeypatch.setattr(db_gateway_module, "get_app_environment", lambda: "production")

    client = DBGateway().metadata_store(provider="postgres")

    assert client is not None
