# Known personas

The full, current login roster from `src/hrb_chatbot/common/known_personas.py`
(Phase 106/147) - the only `employee_id`/`full_name`/`role` combinations
`POST /v1/auth/login` accepts. This isn't a real user directory; it's a
small fixed allowlist that denies an unknown/typo'd identity instead of
accepting anything typed into the login form - see `LoginPage.tsx`'s own
note on this ("still isn't real authentication - role is self-asserted on
every request", `docs/agent-reference/BACKLOG.md`).

**Every row below is a real employee in `hrb_emp_lms.employees`** - the MCP
server's (`hrb_lms_mcp`) own Postgres table - queried directly before being
added here, not invented. This matters because a login's `employee_id` is
also what gets sent to MCP tool calls (`GetLeaveBalance`/`GetLeaveHistory`);
an id that isn't a real row there fails those calls even though login
itself succeeds. Phase 146 found and fixed exactly this: a stale browser
identity (`employee_id: "E200"`, never a real row in either system) had
been silently accepted by the frontend for an unknown length of time
because nothing re-validated it after the initial sign-in - see that
phase's entry in `RAG-ROADMAP.md` for the full incident, including the
data cleanup it required (6 local document records had to be corrected
from `uploaded_by: "E200"` to a real persona after the fact).

## employee

| employee_id | full_name | real department (hrb_emp_lms.employees) |
|---|---|---|
| EMP052 | Eddy Employee | Engineering |
| EMP001 | John Doe | Engineering |
| EMP011 | Richard Thomas | Sales |
| EMP029 | Donald Lopez | Marketing |
| EMP037 | Joshua Mitchell | Finance |
| EMP045 | Edward Edwards | Engineering (part-time) |
| EMP049 | Timothy Morris | Finance (contractor) |

## manager

All 6 real `MGR*` rows in `hrb_emp_lms.employees` - a complete set, nothing
left out.

| employee_id | full_name | real department |
|---|---|---|
| EMP053 | Mia Manager | Operations |
| MGR001 | Alice Johnson | Engineering |
| MGR002 | Bob Smith | Sales |
| MGR003 | Carol Williams | HR |
| MGR004 | David Brown | Marketing |
| MGR005 | Emma Davis | Finance |
| MGR006 | Mona Manager | Sales |

## hr_support

**Honest caveat:** `hr_support` is an app-permission concept in this
project - it has no matching field in the MCP's own schema at all (the
real table only has `department`/`employment_type`). These were inferred
from `department = 'HR'`, the same reasoning the original `EMP051` entry
already relied on - not a verified "this person actually does HR support"
fact.

| employee_id | full_name | real department |
|---|---|---|
| EMP051 | Hana Support | HR |
| EMP021 | Daniel Rodriguez | HR |
| EMP022 | Jessica Lewis | HR |
| EMP023 | Matthew Walker | HR |
| EMP024 | Sarah Hall | HR |
| EMP025 | Anthony Allen | HR |
| EMP026 | Karen Young | HR |

## Other real rows not (yet) added as personas

`hrb_emp_lms.employees` has 62 rows total; the 18 above are a sample, not
the full table. The rest (EMP002-EMP010, EMP012-EMP020, EMP027-EMP028,
EMP030-EMP036, EMP038-EMP044, EMP046-EMP048, EMP050, and three
`emp_11111`/`emp_12345`/`emp_67890` test rows) are real but not in this
login roster - add them the same way (confirm the row is real, pick a
role, add one line to `KNOWN_PERSONAS`) if a test scenario needs one of
them specifically.
