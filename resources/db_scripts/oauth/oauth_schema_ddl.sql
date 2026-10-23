-- OAuth2 simulation schema (design only, not wired into the app yet).
-- Postgres. Mirrors this project's real Role enum (common/enums.py):
-- employee, manager, hr_support - not an open-ended list.
--
-- Lives as its own schema (hrb_chatbot_service_core) INSIDE the shared
-- `hr_chatbot` database, not a standalone employees table in this
-- project's own database. `hr_chatbot` already has a real, populated
-- `hrb_emp_lms.employees` table (shared with hrb_lms_mcp/hrb_emp_assist) -
-- `employee_roles.employee_id` stores that same real id, no duplicated
-- employee rows, no synthetic data.
--
-- Renamed from hrb_chatbot_v2_auth 2026-09-22, alongside creating an
-- empty sibling schema `hrb_chatbot_service_sessions` (reserved for future
-- conversation/session-state tables, no tables yet - nothing to build
-- until a conversation-memory feature actually exists). Three schemas,
-- one per bounded context, same physical `hr_chatbot` database: this
-- project's own identity/RBAC data (`hrb_chatbot_service_core`), this
-- project's own future session state (`hrb_chatbot_service_sessions`), and
-- hrb_lms_mcp's leave data (`hrb_emp_lms`, untouched, not owned by this
-- project) - schema-per-service, a step toward real service isolation
-- even while sharing one physical database.
--
-- No FOREIGN KEY constraints anywhere in this schema - redesigned
-- 2026-09-22, third pass, deliberately. A DB-enforced FK across schemas
-- owned by different services (employee_roles -> hrb_emp_lms.employees)
-- is exactly the tight coupling the "shared database" pattern gets
-- criticized for in real distributed systems: it blocks either service
-- from migrating/sharding/dropping rows independently, and a schema
-- change on either side can break the other silently. Even the FKs
-- entirely within this project's own schema (employee_roles.role_id,
-- client_scopes.client_id) were dropped for consistency - this is a
-- capstone/portfolio project, not a production system with a real
-- data-integrity SLA, so the simpler, more loosely-coupled shape is the
-- better teaching example. Referential lookups still work fine via a
-- plain application-level JOIN (see oauth_sample_data_dml.sql's own
-- verification query) - integrity just isn't DB-enforced.
--
-- Run as: psql -d hr_chatbot -f oauth_schema_ddl.sql

CREATE SCHEMA IF NOT EXISTS hrb_chatbot_service_core;

-- Reserved, deliberately empty - no conversation/session-state feature
-- exists yet. Created now so the bounded-context boundary exists before
-- any table does, not retrofitted after tables already landed elsewhere.
CREATE SCHEMA IF NOT EXISTS hrb_chatbot_service_sessions;

CREATE TABLE IF NOT EXISTS hrb_chatbot_service_core.roles (
    id BIGSERIAL PRIMARY KEY,
    role_name TEXT NOT NULL UNIQUE,
    description TEXT
);

-- This project's own RBAC role per real employee - hrb_lms_mcp has no
-- `role` concept at all (its authorization is manager_id hierarchy, for
-- leave-approval routing, a different concern). One row per employee who
-- has ever logged into this app - not every hrb_emp_lms.employees row
-- needs one. employee_id/role_id are plain BIGINT/INTEGER, not FKs - see
-- the file header for why.
CREATE TABLE IF NOT EXISTS hrb_chatbot_service_core.employee_roles (
    id BIGSERIAL PRIMARY KEY,
    employee_id BIGINT NOT NULL UNIQUE,  -- matches hrb_emp_lms.employees.id, not FK-enforced
    role_id INTEGER NOT NULL,            -- matches roles.id, not FK-enforced
    password_hash TEXT NOT NULL,  -- bcrypt, checked at /oauth/token, never stored plain
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- OAuth2 "client credentials" needs a registered caller, not just a user -
-- e.g. Postman itself, a future web frontend, or this app calling OUT to
-- hrb_lms_mcp as a service - each with its own secret, no human involved.
-- This is the "app-to-app" persona; `employee_roles`/`roles` above is
-- "human-to-app".
CREATE TABLE IF NOT EXISTS hrb_chatbot_service_core.oauth_clients (
    id BIGSERIAL PRIMARY KEY,
    client_id TEXT NOT NULL UNIQUE,
    client_secret_hash TEXT NOT NULL,
    client_name TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- What one client is allowed to call - the app-to-app equivalent of
-- `roles` for humans. E.g. hrb_chatbot_service's own MCP client gets
-- 'mcp:get_leave_balance'/'mcp:get_leave_history' but not
-- 'mcp:submit_leave_request' - read-only until that's deliberately
-- widened. Plain scope strings, not a separate scopes table - there's no
-- shared vocabulary to enforce yet across more than one client.
CREATE TABLE IF NOT EXISTS hrb_chatbot_service_core.client_scopes (
    id BIGSERIAL PRIMARY KEY,
    client_id BIGINT NOT NULL,  -- matches oauth_clients.id, not FK-enforced
    scope TEXT NOT NULL,
    UNIQUE(client_id, scope)
);

CREATE INDEX IF NOT EXISTS idx_employee_roles_role_id ON hrb_chatbot_service_core.employee_roles(role_id);
CREATE INDEX IF NOT EXISTS idx_client_scopes_client_id ON hrb_chatbot_service_core.client_scopes(client_id);
