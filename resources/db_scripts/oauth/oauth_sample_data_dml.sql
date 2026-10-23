-- Sample data for the OAuth2 simulation tables. Run after oauth_schema_ddl.sql.
-- password_hash/client_secret_hash values below are PLACEHOLDER text, not
-- real bcrypt hashes - replace with real hashes (e.g. via passlib) before
-- this is ever wired into working login code.
--
-- Assigns this project's own RBAC roles to REAL rows already in
-- hrb_emp_lms.employees (MGR006/EMP051/EMP052) - no duplicated employee
-- data. `employee_roles.employee_id` is the real BIGINT `id`, looked up
-- by the real `employee_id` business key - a plain value, not a
-- DB-enforced FK (see oauth_schema_ddl.sql's header for why), so these
-- lookups are ordinary subqueries, not something a FK does for free.
--
-- Run as: psql -d hr_chatbot -f oauth_sample_data_dml.sql

INSERT INTO hrb_chatbot_service_core.roles (role_name, description) VALUES
    ('employee', 'Can query the HR benefits chatbot'),
    ('manager', 'Same query access as employee today'),
    ('hr_support', 'Can upload/manage documents, plus query')
ON CONFLICT (role_name) DO NOTHING;

INSERT INTO hrb_chatbot_service_core.employee_roles (employee_id, role_id, password_hash) VALUES
    ((SELECT id FROM hrb_emp_lms.employees WHERE employee_id = 'MGR006'),
        (SELECT id FROM hrb_chatbot_service_core.roles WHERE role_name = 'manager'), 'REPLACE_WITH_REAL_BCRYPT_HASH'),
    ((SELECT id FROM hrb_emp_lms.employees WHERE employee_id = 'EMP051'),
        (SELECT id FROM hrb_chatbot_service_core.roles WHERE role_name = 'hr_support'), 'REPLACE_WITH_REAL_BCRYPT_HASH'),
    ((SELECT id FROM hrb_emp_lms.employees WHERE employee_id = 'EMP052'),
        (SELECT id FROM hrb_chatbot_service_core.roles WHERE role_name = 'employee'), 'REPLACE_WITH_REAL_BCRYPT_HASH')
ON CONFLICT (employee_id) DO NOTHING;

-- hrb-lms-mcp-client: app-to-app - this app calling OUT to hrb_lms_mcp's
-- MCP server as itself, no human involved. hrb_lms_mcp's own auth today
-- is a single static X-API-Key (see its README), not real OAuth2 - this
-- row is this project's own record of "who's allowed to make that call",
-- independent of however hrb_lms_mcp checks it on its side.
INSERT INTO hrb_chatbot_service_core.oauth_clients (client_id, client_secret_hash, client_name) VALUES
    ('postman-client', 'REPLACE_WITH_REAL_BCRYPT_HASH', 'Postman (manual testing)'),
    ('hrb-lms-mcp-client', 'REPLACE_WITH_REAL_BCRYPT_HASH', 'hrb_chatbot_service calling hrb_lms_mcp')
ON CONFLICT (client_id) DO NOTHING;

-- Read-only to start - widen deliberately, not by default.
INSERT INTO hrb_chatbot_service_core.client_scopes (client_id, scope)
SELECT id, scope_value FROM hrb_chatbot_service_core.oauth_clients,
    UNNEST(ARRAY['mcp:get_leave_balance', 'mcp:get_leave_history']) AS scope_value
WHERE client_id = 'hrb-lms-mcp-client'
ON CONFLICT (client_id, scope) DO NOTHING;
