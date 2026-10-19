"""Phase 136 - the Chat GenAI Workflow's own route. Deliberately NOT under
api/rag/ - this never touches ai/rag_pipeline/ or ai/doc_processing/
indexing at all. See docs/dev-reference/genai_chat_workflow.md.

Phase 163 added session memory (chat_workflow_store) and a checkbox-driven
auto-email path, deliberately separate code from the agent's own in-text
SendEmailWithAnswer decision below - see adhoc_document_agent.py's own
run_agent() docstring for why that keeps the single-turn "summarize and
email this" case working regardless of memory."""

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from src.hrb_chatbot.ai.agents.workflow_agents import adhoc_document_agent
from src.hrb_chatbot.ai.doc_processing.adhoc_extraction import extract_text
from src.hrb_chatbot.ai.pre_processing.guardrails_input import GuardrailBlockedError, check_input
from src.hrb_chatbot.ai.rag_pipeline.response_generation.guardrails_output import check_output
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.email_client.ses_client import send_email
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.adhoc_chat import (
    ALLOWED_EXTENSIONS,
    MAX_FILES,
    MAX_FILE_SIZE_BYTES,
    AdhocDocumentChatResponse,
    AdhocSessionDetailResponse,
    AdhocSessionListResponse,
    AdhocSessionSummary,
    AdhocSessionTurn,
    EmailEvidence,
)
from src.hrb_chatbot.models.common import UserProfile

logger = get_logger("adhoc_document_chat")

router_adhoc_document_chat = APIRouter(tags=["adhoc-chat"])

# Same plain-regex approach as the rest of this project (no email-validator
# dependency anywhere here) - good enough to catch an obviously malformed
# address before it reaches SES, not meant to be exhaustive RFC 5322.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Phase 165 - strips the trailing [System note: ...] block(s) save_turn()'s
# own stored_response_text appends (see the POST route below) - those exist
# purely so a LATER turn's chat_history knows an email outcome happened,
# never meant to be shown to a person. Found live, not assumed: the new
# sidebar history view (get_adhoc_session below) would otherwise render
# this internal bookkeeping text verbatim.
SYSTEM_NOTE_SUFFIX_PATTERN = re.compile(r"\n\n\[System note:.*\]$", re.DOTALL)


def _strip_system_notes(text: str) -> str:
    return SYSTEM_NOTE_SUFFIX_PATTERN.sub("", text)


def _validate_files(files: list[UploadFile]) -> str | None:
    """Returns an error message, or None if every file is acceptable."""
    if len(files) == 0:
        return "At least one file is required."
    if len(files) > MAX_FILES:
        return f"At most {MAX_FILES} files are allowed, got {len(files)}."

    for file in files:
        filename = file.filename or ""
        if not filename.lower().endswith(ALLOWED_EXTENSIONS):
            return f"{filename!r} - only {', '.join(ALLOWED_EXTENSIONS)} files are accepted."

    return None


def _build_chat_history(turns: list[dict]) -> list:
    """Converts chat_workflow_store.load_turns()'s own {user_query_text,
    agent_response_text} rows into the [HumanMessage, AIMessage, ...] shape
    adhoc_document_agent.run_agent() (and orchestration_agent.py before it)
    expects."""
    messages: list = []
    for turn in turns:
        messages.append(HumanMessage(content=turn["user_query_text"]))
        messages.append(AIMessage(content=turn["agent_response_text"]))
    return messages


@router_adhoc_document_chat.post("/query", response_model=AdhocDocumentChatResponse)
async def adhoc_document_chat(
    request: Request,
    user_profile: str = Form(...),
    question: str = Form(..., min_length=1, max_length=2000),
    recipient_email: str | None = Form(None),
    files: list[UploadFile] = File(...),
    session_id: str | None = Form(None),
    send_email_on_answer: bool = Form(False),
    cc_email: str | None = Form(None),
):
    try:
        parsed_profile = UserProfile.model_validate_json(user_profile)
    except ValidationError:
        return json_error(422, "user_profile is not valid JSON, or doesn't match the expected shape.", code=error_codes.VALIDATION_ERROR)

    # Open to all 3 roles, unlike document upload - a personal, ephemeral
    # tool that touches no shared state, not KB management.
    userProfile = require_role(parsed_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)
    await enforce_rate_limit(request)

    # Phase 163: server-side validation of the checkbox-driven path, same
    # defense-in-depth reasoning as every other boundary check in this
    # route - the UI already validates this, this is the real source of
    # truth. cc_email is comma-separated, each address checked individually.
    cc_addresses: list[str] = []
    if send_email_on_answer:
        if not recipient_email or not EMAIL_PATTERN.match(recipient_email):
            return json_error(422, "A valid recipient email is required when 'send email on answer' is checked.", code=error_codes.VALIDATION_ERROR)
        if cc_email:
            cc_addresses = [address.strip() for address in cc_email.split(",") if address.strip()]
            invalid = [address for address in cc_addresses if not EMAIL_PATTERN.match(address)]
            if invalid:
                return json_error(422, f"Invalid CC address: {invalid[0]!r}.", code=error_codes.VALIDATION_ERROR)

    validation_error = _validate_files(files)
    if validation_error:
        return json_error(422, validation_error, code=error_codes.INVALID_FILE_TYPE)

    file_texts: dict[str, str] = {}
    # Phase 152: kept alongside file_texts so SendEmailWithAnswer's
    # attach_files can send the file exactly as uploaded, not a re-encoding
    # of the extracted text.
    file_bytes: dict[str, bytes] = {}
    for file in files:
        content = await file.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            return json_error(
                422,
                f"{file.filename!r} is {len(content)} bytes, which exceeds the {MAX_FILE_SIZE_BYTES}-byte limit.",
                code=error_codes.FILE_TOO_LARGE,
            )
        try:
            extracted_text = extract_text(file.filename, content)
        except ValueError as error:
            return json_error(422, str(error), code=error_codes.INVALID_FILE_TYPE)

        # Phase 138: a document's content is just as untrusted as typed
        # input - reuse the same input rails (jailbreak/injection/PII
        # categories) rather than letting file content skip screening
        # entirely, which was the gap before this phase.
        try:
            file_texts[file.filename], _ = await check_input(extracted_text)
        except GuardrailBlockedError as error:
            return json_error(
                422,
                f"{file.filename!r} was rejected by a safety check: {error}",
                code=error_codes.INPUT_GUARDRAIL_BLOCKED,
            )
        file_bytes[file.filename] = content

    try:
        checked_question, _ = await check_input(question)
    except GuardrailBlockedError as error:
        return json_error(422, str(error), code=error_codes.INPUT_GUARDRAIL_BLOCKED)

    # The agent gets the recipient_email folded into the question itself
    # when given, since SendEmailWithAnswer is a real tool call the agent
    # decides to make, not something this route drives directly. Phase 159:
    # purely informational, not a directive - the UI's recipient-email
    # field is sticky across turns, so an unconditional "please email the
    # answer" here used to get appended to every later message too,
    # including ones with nothing to do with email (e.g. "did you send the
    # email?"), and the model mostly complied with it anyway - confirmed
    # live. A first attempt at a conditional directive ("only if this
    # message asks...") overcorrected into false negatives on genuine email
    # requests (also confirmed live, 2 of 3 explicit "email it to me"
    # requests silently didn't send) - likely the double conditional
    # (system prompt's own instruction plus this one re-explaining the same
    # condition) confusing the model rather than clarifying it. Staying
    # purely informational here and trusting the system prompt's own
    # existing instruction (already states "only call this if the user
    # explicitly asked") to be the one place that governs the decision.
    agent_question = checked_question
    if recipient_email:
        agent_question = f"{checked_question}\n\n(For reference, if needed: the user's email address is {recipient_email}.)"

    # Phase 163: resolved the same way orchestration_agent.py resolves
    # conversation_id - client-sent to continue a session, server-generated
    # on the first turn. Always-on for this workflow (not an opt-in flag,
    # unlike the other 3 modes' enable_conversation_memory).
    store = get_db_gateway().chat_workflow_store()
    resolved_session_id = session_id or store.new_session_id()
    chat_history: list = []
    if session_id:
        try:
            prior_turns = await store.load_turns(session_id)
            chat_history = _build_chat_history(prior_turns)
        except Exception as error:
            # Best-effort: a history-load failure shouldn't block answering
            # the question it's about to help answer - continue with no
            # history rather than fail the whole request.
            logger.warning("Loading chat history for session_id=%r failed, continuing without it: %s", session_id, error)

    try:
        result = await adhoc_document_agent.run_agent(agent_question, file_texts, file_bytes, chat_history=chat_history)
    except Exception as error:
        logger.error("Adhoc document chat failed for %r: %s: %s", question, type(error).__name__, error)
        return json_error(500, "The question could not be answered. Please try again.", code=error_codes.QUERY_FAILED)

    result["answer"], _ = await check_output(checked_question, result["answer"])

    # Phase 163: the checkbox-driven path - deliberately separate code from
    # the agent's own in-text SendEmailWithAnswer decision above, which has
    # already run (or not) by this point, untouched. Both can legitimately
    # fire in the same turn (accepted edge case, see RAG-ROADMAP.md) -
    # every attempt from either path gets its own persisted event below;
    # the checkbox-driven one takes priority in the API response since it's
    # the more deterministic, explicitly-requested one.
    model_decision_evidence = result.get("email_evidence")
    checkbox_auto_evidence: dict | None = None
    if send_email_on_answer:
        subject = "Your answer from HR Benefits Chat"
        send_result = send_email(recipient_email, subject, result["answer"], cc_addresses=cc_addresses or None)
        checkbox_auto_evidence = {
            "recipient_email": recipient_email,
            "subject": subject,
            "sent": send_result["sent"],
            "message": send_result["message"],
            "attached_files": [],
            "sent_at": datetime.now(UTC).isoformat(),
            "trigger_source": "checkbox_auto",
        }

    response_email_evidence = checkbox_auto_evidence or model_decision_evidence

    # Phase 163: live-tested and caught before this shipped - chat_history
    # only ever carried the plain answer text, so a later turn's "did you
    # send it?" had no way to know an earlier turn's email actually
    # succeeded, and the model answered "I have not sent any email yet" -
    # the exact bug from the user's own original production report,
    # reintroduced by memory itself rather than fixed by it. The fix: the
    # STORED version of this turn's answer (never the user-facing one
    # returned below) carries a short factual outcome note for each email
    # attempt this turn, so a future turn's chat_history actually knows
    # what happened, not just what was said.
    stored_response_text = result["answer"]
    for evidence in (model_decision_evidence, checkbox_auto_evidence):
        if evidence is None:
            continue
        if evidence["sent"]:
            stored_response_text += f"\n\n[System note: an email was successfully sent to {evidence['recipient_email']} this turn.]"
        else:
            stored_response_text += f"\n\n[System note: an email to {evidence['recipient_email']} was attempted this turn but failed: {evidence['message']}]"

    # Phase 163: best-effort persistence - the user already has their real
    # answer by this point; a DB hiccup here shouldn't turn a successful
    # answer into a 500. Losing one turn's memory is recoverable, unlike
    # losing the answer itself.
    try:
        session_title = checked_question[:80]
        await store.start_or_touch_session(resolved_session_id, userProfile.employee_id, userProfile.full_name, session_title)
        turn_id = await store.save_turn(
            resolved_session_id, userProfile.employee_id, checked_question, stored_response_text, result["files_used"]
        )
        if model_decision_evidence:
            await store.save_email_event(
                turn_id,
                model_decision_evidence["recipient_email"],
                None,
                model_decision_evidence["subject"],
                "sent" if model_decision_evidence["sent"] else "failed",
                model_decision_evidence["message"],
                model_decision_evidence["attached_files"],
                "model_decision",
            )
        if checkbox_auto_evidence:
            await store.save_email_event(
                turn_id,
                checkbox_auto_evidence["recipient_email"],
                ", ".join(cc_addresses) if cc_addresses else None,
                checkbox_auto_evidence["subject"],
                "sent" if checkbox_auto_evidence["sent"] else "failed",
                checkbox_auto_evidence["message"],
                [],
                "checkbox_auto",
            )
    except Exception as error:
        logger.warning("Persisting chat workflow history for session_id=%r failed: %s", resolved_session_id, error)

    return AdhocDocumentChatResponse(
        question=question,
        answer=result["answer"],
        files_used=result["files_used"],
        web_searches=result["web_searches"],
        email_sent_to=checkbox_auto_evidence["recipient_email"] if checkbox_auto_evidence and checkbox_auto_evidence["sent"] else result["email_sent_to"],
        email_evidence=EmailEvidence(**response_email_evidence) if response_email_evidence else None,
        session_id=resolved_session_id,
        model_used=result["model_used"],
        iterations=result["iterations"],
        llm_call_count=result["llm_call_count"],
        token_usage=result["token_usage"],
        latency_ms=result["latency_ms"],
    )


@router_adhoc_document_chat.get("/sessions", response_model=AdhocSessionListResponse)
async def list_adhoc_sessions(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 165 - the sidebar's "GenAI Chat Workflow History" section.
    Query-param identity, same Phase 96 pattern as every other GET route -
    a GET can't carry a body at all. Scoped to the caller's own
    employee_id, same non-disclosure as manage_conversations.py's own
    list/get routes."""
    userProfile = require_role(user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)

    rows = await get_db_gateway().chat_workflow_store().list_sessions(userProfile.employee_id)
    return AdhocSessionListResponse(count=len(rows), sessions=[AdhocSessionSummary(**row) for row in rows])


@router_adhoc_document_chat.get("/sessions/{session_id}", response_model=AdhocSessionDetailResponse)
async def get_adhoc_session(session_id: str, user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """A session that isn't the caller's own (or doesn't exist) returns an
    empty turns list - load_turns() itself isn't employee-scoped (it only
    takes session_id), so this route checks ownership against the
    session's own employee_id from list_sessions() first, rather than
    trusting the caller-supplied session_id alone."""
    userProfile = require_role(user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)

    store = get_db_gateway().chat_workflow_store()
    owned_session_ids = {row["session_id"] for row in await store.list_sessions(userProfile.employee_id)}
    if session_id not in owned_session_ids:
        return AdhocSessionDetailResponse(session_id=session_id, turns=[])

    raw_turns = await store.load_turns(session_id)
    turns: list[AdhocSessionTurn] = []
    for turn in raw_turns:
        turns.append(AdhocSessionTurn(role="human", content=turn["user_query_text"], created_at=turn["created_at"]))
        turns.append(
            AdhocSessionTurn(
                role="ai", content=_strip_system_notes(turn["agent_response_text"]), created_at=turn["created_at"]
            )
        )
    return AdhocSessionDetailResponse(session_id=session_id, turns=turns)
