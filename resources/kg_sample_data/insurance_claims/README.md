# Insurance claims — synthetic sample data

Hand-authored, clearly synthetic sample data for the knowledge-graph
exploration in
`docs/dev-reference/hrb_chatbot_v3/architecture/design/readme-knowledge-graph.md`
(Section 14). Not real employee or claims data, not wired into any
pipeline yet — these files exist only so the design sketch has real
sample data to point at instead of inline markdown tables.

- `providers.csv` — doctors/clinics, their specialty, and which carrier network they're in.
- `plan_limits.csv` — per-carrier, per-plan-year deductible/out-of-pocket/annual-max reference data.
- `claims.csv` — individual claims, referencing real employee IDs from `hrb_lms_mcp`'s seed data and real carriers named in `resources/kb_docs/AmazingBank_Healthcare_Benefits.pdf`.
- `appeals.csv` — appeals filed against denied claims in `claims.csv`.

`claim_id`/`provider_id`/`employee_id` are the join keys across these
files, the same way the Udemy course project's own CRM CSVs (Section 10.4
of the design doc) cross-reference each other.
