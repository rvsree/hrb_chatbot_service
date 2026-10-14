#!/usr/bin/env python
"""Phase 170 (round 1) - uploads the architecture docs the admin-only docs
viewer serves to S3 (LEAVE_DOCS_S3_BUCKET, under admin-docs/ - see
s3_upload_client.py's own comment for why not S3_UPLOAD_BUCKET) and
upserts doc_metadata by content hash - a re-run of an unchanged file is a
no-op (same dedup principle KB ingestion already uses). Run as:
python -m scripts.sync_admin_docs"""

import asyncio
import hashlib
import os
import sys

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.storage_client.s3_upload_client import upload_admin_doc_file
from src.hrb_chatbot.common.config.settings import read_setting

ADMIN_DOCS_S3_PREFIX = "admin-docs/"

# Phase 179 - a feature can now list several doc_types (Spec/Architecture/
# Design/Decisions), not just one - feature_name -> {doc_type: (doc_title,
# local_path, content_type)}. Every pre-Phase-179 feature keeps its single
# "architecture"/"design" entry unchanged, just nested one level deeper.
DOCS_TO_SYNC = {
    "request-unpaid-leave": {
        "design": (
            "Leave Approval A2A",
            "docs/dev-reference/leave-approval-a2a-design.html",
            "text/html",
        ),
    },
    # Phase 180 (round 4) - Spec/Design/Decisions added for all 4 real
    # rag-retrieval features, per direct instruction. Architecture stays
    # the existing, already-verified doc for each - deliberately NOT a
    # deck-slide replacement here (see genai-rag-chat's own Decisions
    # GR-1: the deck's closest candidate, slide 8, depicts a materially
    # different target microservices architecture - LangGraph even for
    # plain genai-rag, SQS-async cache/conversation writes - neither true
    # today, confirmed against the real code before deciding not to use it).
    "genai-rag-chat": {
        "spec": (
            "GenAI RAG Chat - Spec",
            "docs/dev-reference/genai-rag-chat/spec.html",
            "text/html",
        ),
        "architecture": (
            "RAG Architecture Layers",
            "docs/dev-reference/rag-architecture-layers.html",
            "text/html",
        ),
        "design": (
            "GenAI RAG Chat - Design",
            "docs/dev-reference/genai-rag-chat/design.html",
            "text/html",
        ),
        "decisions": (
            "GenAI RAG Chat - Decisions",
            "docs/dev-reference/genai-rag-chat/decisions.html",
            "text/html",
        ),
    },
    # Phase 175 - "RAG Pipeline:" dropdown, remaining 2 of 3 options.
    "single-agentic-rag": {
        "spec": (
            "Single-Agentic RAG - Spec",
            "docs/dev-reference/single-agentic-rag/spec.html",
            "text/html",
        ),
        "architecture": (
            "RAG Pipeline: Current State",
            "docs/dev-reference/rag-retrieval/rag-pipeline-current-state.html",
            "text/html",
        ),
        "design": (
            "Single-Agentic RAG - Design",
            "docs/dev-reference/single-agentic-rag/design.html",
            "text/html",
        ),
        "decisions": (
            "Single-Agentic RAG - Decisions",
            "docs/dev-reference/single-agentic-rag/decisions.html",
            "text/html",
        ),
    },
    "multi-agentic-rag": {
        "spec": (
            "Multi-Agentic RAG - Spec",
            "docs/dev-reference/multi-agentic-rag/spec.html",
            "text/html",
        ),
        "architecture": (
            "Multi-Agent Graph",
            "docs/dev-reference/react_agents/multi-agent-graph.html",
            "text/html",
        ),
        "design": (
            "Multi-Agentic RAG - Design",
            "docs/dev-reference/multi-agentic-rag/design.html",
            "text/html",
        ),
        "decisions": (
            "Multi-Agentic RAG - Decisions",
            "docs/dev-reference/multi-agentic-rag/decisions.html",
            "text/html",
        ),
    },
    # Phase 175 - "Retrieval:" dropdown - architecture doc shared by all 4
    # search strategy options (similarity/mmr/keyword/hybrid); no per-method
    # doc exists yet, this is the closest real content (retrieval strategy
    # is one of its six gates) - flagged directly, not invented.
    "retrieval-strategies": {
        "spec": (
            "Retrieval Strategies - Spec",
            "docs/dev-reference/retrieval-strategies/spec.html",
            "text/html",
        ),
        "architecture": (
            "RAG Validation Gates",
            "docs/dev-reference/rag-validation-gates.html",
            "text/html",
        ),
        "design": (
            "Retrieval Strategies - Design",
            "docs/dev-reference/retrieval-strategies/design.html",
            "text/html",
        ),
        "decisions": (
            "Retrieval Strategies - Decisions",
            "docs/dev-reference/retrieval-strategies/decisions.html",
            "text/html",
        ),
    },
    # Phase 175 - "Enable GenAI Chat Workflow" checkbox.
    "genai-chat-workflow": {
        "architecture": (
            "GenAI Chat Workflow Architecture",
            "docs/dev-reference/genai-chat-workflow-architecture.html",
            "text/html",
        ),
    },
    # Phase 179 - pilot for the Spec/Architecture/Design/Decisions model:
    # 4 doc_types for one feature, used to confirm the multi-doc viewer
    # works end to end before deciding whether to extend it further.
    "admin-secret-code": {
        "spec": (
            "Admin Secret Code - Spec",
            "docs/dev-reference/admin-secret-code/spec.html",
            "text/html",
        ),
        "architecture": (
            "Admin Secret Code - Architecture",
            "docs/dev-reference/admin-secret-code/architecture.html",
            "text/html",
        ),
        "design": (
            "Admin Secret Code - Design",
            "docs/dev-reference/admin-secret-code/design.html",
            "text/html",
        ),
        "decisions": (
            "Admin Secret Code - Decisions",
            "docs/dev-reference/admin-secret-code/decisions.html",
            "text/html",
        ),
    },
    # Phase 180 - second Spec/Architecture/Design/Decisions pilot, a real
    # chatbot feature this time (direct feedback: Admin Secret Code wasn't
    # representative). Filed under upload-documents - the feature_name
    # UploadPage.tsx's existing DocLink already points at, previously
    # flagged as having zero docs synced. Rebuilt (round 4) after direct
    # feedback: no phase/gap narration in these docs (that's
    # RAG-ROADMAP.md's job), diagram-first not text-first, and a real
    # "overview" entry page with child links - none of which the first
    # draft had.
    "upload-documents": {
        "overview": (
            "RAG Ingestion - Overview",
            "docs/dev-reference/rag-ingestion/overview.html",
            "text/html",
        ),
        "spec": (
            "RAG Ingestion - Spec",
            "docs/dev-reference/rag-ingestion/spec.html",
            "text/html",
        ),
        "architecture": (
            "RAG Ingestion - Architecture",
            "docs/dev-reference/rag-ingestion/architecture.html",
            "text/html",
        ),
        "design": (
            "RAG Ingestion - Design",
            "docs/dev-reference/rag-ingestion/design.html",
            "text/html",
        ),
        "decisions": (
            "RAG Ingestion - Decisions",
            "docs/dev-reference/rag-ingestion/decisions.html",
            "text/html",
        ),
    },
    # Phase 180 (round 3) - the real, actively-maintained PowerPoint deck
    # itself (not an export from it) - system-level, not tied to one
    # feature, so admin can always download the latest working version to
    # review/correct offline rather than only ever seeing static exports.
    # Deliberately points at the user's own Downloads folder, not a copy
    # checked into this repo - that file is their live working copy,
    # incremented (v9, v10, v11, ...) each time a correction is made here;
    # copying it into the repo would create a second, driftable source.
    # The local_path below needs updating by hand to the current version
    # each time it changes - no automatic "latest version" detection.
    "architecture-deck": {
        "deck": (
            "HRB V2 Architecture Deck (PowerPoint)",
            r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v10.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    },
    # Phase 180 (round 9) - genai-rag-chat/design.html and single-agentic-
    # rag/design.html both cross-reference this system-wide latency doc for
    # their own NFR sections, but it was never synced under any feature
    # name - every such link resolved to a literal "type=None" (confirmed
    # live, found during the bookmark-link audit). System-level, not tied
    # to one feature, so its own entry rather than folded into either.
    "scaling-latency-design": {
        "design": (
            "Scaling & Latency Design",
            "docs/dev-reference/design/scaling-latency-design.html",
            "text/html",
        ),
    },
}


def _content_hash(local_path: str) -> str:
    with open(local_path, "rb") as file_handle:
        return hashlib.sha256(file_handle.read()).hexdigest()


async def main() -> int:
    bucket = read_setting(None, "LEAVE_DOCS_S3_BUCKET")
    if not bucket:
        print("LEAVE_DOCS_S3_BUCKET not set - nothing to sync to.")
        return 1

    store = get_db_gateway().doc_metadata_store()

    for feature_name, docs_by_type in DOCS_TO_SYNC.items():
        for doc_type, (doc_title, local_path, content_type) in docs_by_type.items():
            content_hash = _content_hash(local_path)
            # Extension matches the real source file - not hardcoded
            # .html, since the deck entry below is a real .pptx.
            extension = os.path.splitext(local_path)[1] or ".html"
            # Phase 180 (round 6) - a real subdirectory per feature, not a
            # flat "{feature}-{doc_type}.html" filename. The flat scheme
            # broke every cross-doc link: a document opened from its own
            # presigned URL (e.g. admin-docs/upload-documents-spec.html)
            # resolves a plain <a href="architecture.html"> per standard
            # relative-URL rules against the *last path segment*, landing
            # on admin-docs/architecture.html - silently dropping the
            # feature prefix, confirmed live from a real AccessDenied
            # screenshot. Docs in the same feature are true siblings under
            # one subdirectory now, so a bare "architecture.html" link
            # resolves correctly with no path-construction logic needed
            # in the HTML itself.
            s3_key = f"{ADMIN_DOCS_S3_PREFIX}{feature_name}/{doc_type}{extension}"

            upload_admin_doc_file(local_path, s3_key, content_type)
            result = await store.upsert_doc(
                feature_name=feature_name,
                doc_title=doc_title,
                doc_type=doc_type,
                s3_bucket=bucket,
                s3_key=s3_key,
                source_local_path=local_path,
                content_hash=content_hash,
            )
            status = "updated" if result["changed"] else "unchanged"
            print(f"{feature_name}/{doc_type}: {status} (id={result['id']}, doc_version={result['doc_version']})")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
