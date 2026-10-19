"""Document-level ACL (Phase 231, Gate 2) - resolves which documents the
caller's role/department deny them, then excludes those document_ids from
retrieval via a $nin filter. Same "resolve against real metadata before
querying" approach Phase 230 already established for doc_description."""

import json

from src.hrb_chatbot.common.enums import Role

# HR_SUPPORT manages/uploads documents, ADMIN is "Engineering Admin -
# everything" per Role's own docstring - both always see every document,
# regardless of restricted_roles/department. EMPLOYEE/MANAGER are gated.
ACL_BYPASS_ROLES = {Role.HR_SUPPORT.value, Role.ADMIN.value}


def _is_denied(document: dict, role: str | None, department: str | None) -> bool:
    restricted_roles_raw = document.get("restricted_roles")
    restricted_roles = json.loads(restricted_roles_raw) if restricted_roles_raw else None
    if restricted_roles and role not in restricted_roles:
        return True

    doc_department = document.get("department")
    if doc_department and (department or "").strip().lower() != doc_department.strip().lower():
        return True

    return False


async def build_acl_filter(db_gateway, role: str | None, department: str | None) -> dict | None:
    """Returns {"document_id": {"$nin": [...]}} excluding every document
    this caller is denied, or None when nothing needs excluding (the
    common case - most documents set neither restricted_roles nor
    department, so the gate is simply open)."""
    if role in ACL_BYPASS_ROLES:
        return None

    documents = await db_gateway.metadata_store().list_documents()
    # is_current comes back as an int (SQLite) or a real bool (Postgres) -
    # plain truthiness handles both; `is False`/`is not False` would miss SQLite's 0.
    denied_ids = [
        document["id"]
        for document in documents
        if document.get("is_current", True) and _is_denied(document, role, department)
    ]
    if not denied_ids:
        return None
    return {"document_id": {"$nin": denied_ids}}
