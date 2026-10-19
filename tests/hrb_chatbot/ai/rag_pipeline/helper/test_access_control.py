"""Tests for build_acl_filter() (Phase 231, Document ACL -
ai/rag_pipeline/helper/access_control.py). Uses FakeMetadataStore/
FakeDBGateway directly - no vector store involved, this module only
resolves a document_id deny-list from real document metadata."""

from src.hrb_chatbot.ai.rag_pipeline.helper import access_control
from tests.conftest import FakeDBGateway, FakeMetadataStore


async def _seed(metadata_store, document_id, department=None, restricted_roles=None):
    await metadata_store.create_document(document_id, f"{document_id}.pdf", f"data/uploads/{document_id}/{document_id}.pdf")
    await metadata_store.record_document_metadata(
        document_id, owner=None, department=department, doc_category="benefits",
        purpose=None, doc_description=None, restricted_roles=restricted_roles,
    )


async def test_no_documents_set_any_restriction_returns_none():
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1")
    gateway = FakeDBGateway(metadata_store=metadata_store)

    assert await access_control.build_acl_filter(gateway, role="employee", department=None) is None


async def test_hr_support_bypasses_every_gate_even_with_restricted_documents():
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1", restricted_roles=["manager"])
    await _seed(metadata_store, "doc-2", department="Finance")
    gateway = FakeDBGateway(metadata_store=metadata_store)

    assert await access_control.build_acl_filter(gateway, role="hr_support", department=None) is None


async def test_admin_bypasses_every_gate_too():
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1", restricted_roles=["manager"])
    gateway = FakeDBGateway(metadata_store=metadata_store)

    assert await access_control.build_acl_filter(gateway, role="admin", department=None) is None


async def test_role_restricted_document_is_denied_to_a_role_not_in_the_list():
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1", restricted_roles=["manager", "hr_support"])
    await _seed(metadata_store, "doc-2")
    gateway = FakeDBGateway(metadata_store=metadata_store)

    result = await access_control.build_acl_filter(gateway, role="employee", department=None)

    assert result == {"document_id": {"$nin": ["doc-1"]}}


async def test_role_restricted_document_is_allowed_to_a_role_in_the_list():
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1", restricted_roles=["manager", "hr_support"])
    gateway = FakeDBGateway(metadata_store=metadata_store)

    assert await access_control.build_acl_filter(gateway, role="manager", department=None) is None


async def test_department_restricted_document_is_denied_on_a_mismatch():
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1", department="Finance")
    gateway = FakeDBGateway(metadata_store=metadata_store)

    result = await access_control.build_acl_filter(gateway, role="employee", department="Engineering")

    assert result == {"document_id": {"$nin": ["doc-1"]}}


async def test_department_restricted_document_is_allowed_on_a_case_insensitive_match():
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1", department="Finance")
    gateway = FakeDBGateway(metadata_store=metadata_store)

    assert await access_control.build_acl_filter(gateway, role="employee", department="finance") is None


async def test_department_restricted_document_is_denied_when_caller_has_no_department():
    """The safe-by-default side, per the contracts doc: a null caller
    department never matches a set document department."""
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1", department="Finance")
    gateway = FakeDBGateway(metadata_store=metadata_store)

    result = await access_control.build_acl_filter(gateway, role="employee", department=None)

    assert result == {"document_id": {"$nin": ["doc-1"]}}


async def test_superseded_documents_are_never_added_to_the_deny_list():
    """A document already excluded by is_current has no reason to also
    appear in the ACL deny-list - redundant, not wrong, but kept minimal."""
    metadata_store = FakeMetadataStore()
    await _seed(metadata_store, "doc-1", restricted_roles=["manager"])
    await metadata_store.mark_superseded("doc-1", "doc-2")
    gateway = FakeDBGateway(metadata_store=metadata_store)

    assert await access_control.build_acl_filter(gateway, role="employee", department=None) is None
