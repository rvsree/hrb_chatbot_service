-- Phase 251: schema-per-domain migration, local Postgres only (see
-- RAG-ROADMAP.md's Phase 251 spec for the full real-table-inventory audit
-- behind this list). Every table lives unqualified in `public` today;
-- this groups them by the future service that will own each one.
-- Every schema is prefixed hrb_<name> (user-directed) - distinguishes this
-- project's own schemas from any other service's in the same database
-- (e.g. hrb_lms_mcp's own hrb_emp_lms/hrb_lms_mcp_auth).
--
-- Deliberately excluded (see spec): answer_cache/embedding_cache (orphaned,
-- Redis replaced them), checkpoint_blobs/checkpoint_migrations/
-- checkpoint_writes/checkpoints (LangGraph's own AsyncPostgresSaver-managed
-- tables, no schema override exists in that library), mcp_registry
-- (confirmed foreign-owned, a different database entirely).
--
-- Idempotent: safe to run more than once. Each ALTER TABLE is guarded so a
-- table that doesn't exist yet locally (e.g. `chunks`, since
-- RAG_METADATA_STORE=sqlite is this project's active local default) is a
-- no-op, not an error.

CREATE SCHEMA IF NOT EXISTS hrb_rag_ingestion;
CREATE SCHEMA IF NOT EXISTS hrb_rag_retrieval;
CREATE SCHEMA IF NOT EXISTS hrb_chat_feedback;
CREATE SCHEMA IF NOT EXISTS hrb_chat_hitl;
CREATE SCHEMA IF NOT EXISTS hrb_interview_qa;
CREATE SCHEMA IF NOT EXISTS hrb_build_deployment;
CREATE SCHEMA IF NOT EXISTS hrb_chat_metrics;
CREATE SCHEMA IF NOT EXISTS hrb_admin_controls;

DO $$
DECLARE
    moves text[][] := ARRAY[
        ARRAY['documents', 'hrb_rag_ingestion'],
        ARRAY['chunks', 'hrb_rag_ingestion'],
        ARRAY['conversation_turns', 'hrb_rag_retrieval'],
        ARRAY['feedback', 'hrb_chat_feedback'],
        ARRAY['agent_threads', 'hrb_chat_hitl'],
        ARRAY['chat_session_records', 'hrb_chat_hitl'],
        ARRAY['chat_turn_records', 'hrb_chat_hitl'],
        ARRAY['email_send_events', 'hrb_chat_hitl'],
        ARRAY['interview_qa_cards', 'hrb_interview_qa'],
        ARRAY['pipeline_runs', 'hrb_build_deployment'],
        ARRAY['eval_runs', 'hrb_build_deployment'],
        ARRAY['eval_run_cases', 'hrb_build_deployment'],
        ARRAY['golden_dataset_cases', 'hrb_build_deployment'],
        ARRAY['request_metrics', 'hrb_chat_metrics'],
        ARRAY['admin_credentials', 'hrb_admin_controls'],
        ARRAY['faq_submissions', 'hrb_admin_controls'],
        -- Correction found during implementation (not the planning doc's
        -- claim): doc_metadata_store.py tracks admin architecture/design
        -- docs synced to S3 for the admin doc viewer - unrelated to RAG
        -- ingestion content despite the similar name. Belongs with the
        -- other admin-only tables, not rag_ingestion.
        ARRAY['doc_metadata', 'hrb_admin_controls']
    ];
    move text[];
BEGIN
    FOREACH move SLICE 1 IN ARRAY moves
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = move[1]
        ) THEN
            EXECUTE format('ALTER TABLE public.%I SET SCHEMA %I', move[1], move[2]);
            RAISE NOTICE 'moved public.% -> %.%', move[1], move[2], move[1];
        ELSE
            RAISE NOTICE 'skipped % - table does not exist in public (not created locally yet)', move[1];
        END IF;
    END LOOP;
END $$;
