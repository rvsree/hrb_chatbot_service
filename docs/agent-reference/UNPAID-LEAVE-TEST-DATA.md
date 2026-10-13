# Request Unpaid Leave - manual test-data walkthrough

Pairs `KNOWN-PERSONAS.md`'s existing login roster with concrete sample
request data for manually exercising the "Request Unpaid Leave" feature
(Phase 162/163/164) end to end, both sides - employee submission and HR
specialist review. Doesn't replace `KNOWN-PERSONAS.md`; it's the identities
from there plus the request-specific data that file doesn't cover.

No seed row in `hrb_lms_mcp`'s sample data uses the `UNPAID` leave type
(confirmed by reading `db-script-sample-data.sql` directly) - every
persona below starts with zero unpaid-leave history. The "repeat" scenario
isn't pre-seeded; it's exercised by submitting twice in the same test
session (see below).

## Employee side - submitting a request

Log in as any `employee`-role persona from `KNOWN-PERSONAS.md`. Two
concrete runs:

**Run 1 - first-time request (not a repeat)**

| Field | Value |
|---|---|
| Persona | `EMP052` / Eddy Employee |
| Start date | 10 business days from today |
| End date | start date + 4 days |
| Purpose | "Caring for a family member recovering from surgery - no PTO remaining this cycle." |
| Supporting document | any real `.pdf` or `.docx` under 10MB - a scanned letter, a sample offer letter, anything on hand |

Expected: `is_repeat_within_12_months: false` in the response.

**Run 2 - repeat request (same persona, submitted again)**

Immediately after Run 1 succeeds, submit a second request for the same
`EMP052` persona:

| Field | Value |
|---|---|
| Start date | 20 business days from today |
| End date | start date + 2 days |
| Purpose | "Extended medical leave - same situation as my last request." |
| Supporting document | optional this time |

Expected: `is_repeat_within_12_months: true` - because Run 1's request now
falls inside the trailing-365-day window `unpaid_leave_agent.py`'s
eligibility check looks at. This is the one scenario that genuinely needs
2 submissions, not seed data, to exercise.

## HR specialist side - reviewing a request

Log in as any `hr_support`-role persona from `KNOWN-PERSONAS.md` -
`EMP021` through `EMP026` (6 personas, all real `department='HR'` rows).
Any one of them can see and resolve any pending request today (shared
queue, no per-specialist assignment - see
`docs/dev-reference/leave-approval-a2a-design.html` §09/§08 Q6).

| Persona | Full name |
|---|---|
| `EMP021` | Daniel Rodriguez |
| `EMP022` | Jessica Lewis |
| `EMP023` | Matthew Walker |
| `EMP024` | Sarah Hall |
| `EMP025` | Anthony Allen |
| `EMP026` | Karen Young |

Open "Leave approvals" from the Admin menu. Both requests from Run 1/Run 2
above should appear, Run 2 flagged as a repeat. Approve one, reject the
other, with a short HR comment each (e.g. "Approved - documentation
checks out." / "Please resubmit with updated dates."), to exercise both
decision paths.

## What this doesn't cover yet

No notification currently reaches the employee after a specialist
resolves their request, and no document-download link exists yet for the
HR reviewer - both are open gaps tracked in
`docs/dev-reference/leave-approval-a2a-design.html` §09, not something
this test-data doc can exercise until they're built.
