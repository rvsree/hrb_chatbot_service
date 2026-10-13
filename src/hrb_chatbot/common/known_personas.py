"""Phase 106: a small fixed roster for lightweight login validation - not a
real user directory, just enough to deny an unknown/typo'd identity instead
of accepting anything typed into the login form. Extends the EMP051/EMP052
identities already used throughout postman/ and tests/, not new ones.

Phase 147: expanded from 3 to 18 personas (6 per role) - every id/name
below is a real row in hrb_emp_lms.employees (the MCP server's own
Postgres database, queried directly before adding these, not invented).
See docs/agent-reference/KNOWN-PERSONAS.md for the full table and how the
hr_support role was inferred (that role has no matching field in the MCP's
own schema - same reasoning the original EMP051 entry already relied on)."""

KNOWN_PERSONAS = {
    "EMP051": {"full_name": "Hana Support", "role": "hr_support"},
    "EMP052": {"full_name": "Eddy Employee", "role": "employee"},
    "EMP053": {"full_name": "Mia Manager", "role": "manager"},
    # Phase 147 - employee role (department/employment-type diversity)
    "EMP001": {"full_name": "John Doe", "role": "employee"},
    "EMP011": {"full_name": "Richard Thomas", "role": "employee"},
    "EMP029": {"full_name": "Donald Lopez", "role": "employee"},
    "EMP037": {"full_name": "Joshua Mitchell", "role": "employee"},
    "EMP045": {"full_name": "Edward Edwards", "role": "employee"},
    "EMP049": {"full_name": "Timothy Morris", "role": "employee"},
    # Phase 147 - manager role (all 6 real MGR* rows, none left out)
    "MGR001": {"full_name": "Alice Johnson", "role": "manager"},
    "MGR002": {"full_name": "Bob Smith", "role": "manager"},
    "MGR003": {"full_name": "Carol Williams", "role": "manager"},
    "MGR004": {"full_name": "David Brown", "role": "manager"},
    "MGR005": {"full_name": "Emma Davis", "role": "manager"},
    "MGR006": {"full_name": "Mona Manager", "role": "manager"},
    # Phase 147 - hr_support role (real department='HR' rows)
    "EMP021": {"full_name": "Daniel Rodriguez", "role": "hr_support"},
    "EMP022": {"full_name": "Jessica Lewis", "role": "hr_support"},
    "EMP023": {"full_name": "Matthew Walker", "role": "hr_support"},
    "EMP024": {"full_name": "Sarah Hall", "role": "hr_support"},
    "EMP025": {"full_name": "Anthony Allen", "role": "hr_support"},
    "EMP026": {"full_name": "Karen Young", "role": "hr_support"},
    # Phase 168 - admin role. Deliberately NOT a real hrb_emp_lms.employees
    # row, unlike every persona above - admin operations never resolve the
    # admin's own identity through MCP the way, say, GetLeaveBalance does
    # for an employee asking about themselves, so there's nothing for a
    # real backing row to serve here. A documented first exception to the
    # "every persona is real" rule this file otherwise holds to.
    # Phase 169 added an extra login check for this one role; Phase 171
    # moved the secret code itself out of this file entirely (it was a
    # plaintext literal) into admin_credential_store.py's Postgres-backed,
    # salted-hash storage - see AdminCredentialStore.verify_secret_code().
    "ADM001": {"full_name": "Sree Rad", "role": "admin"},
}


def is_known_persona(employee_id: str, full_name: str, role: str) -> bool:
    persona = KNOWN_PERSONAS.get(employee_id)
    if persona is None:
        return False
    if persona["full_name"].strip().lower() != full_name.strip().lower():
        return False
    return persona["role"] == role
