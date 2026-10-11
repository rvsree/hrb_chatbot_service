"""Phase 136 - the Chat GenAI Workflow's own route. Deliberately NOT under
api/rag/ - this never touches ai/rag_pipeline/ or ai/doc_processing/
indexing at all. See docs/dev-reference/genai_chat_workflow.md."""

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import ValidationError

from src.hrb_chatbot.ai.agents.workflow_agents import adhoc_document_agent
from src.hrb_chatbot.ai.doc_processing.adhoc_extraction import extract_text
from src.hrb_chatbot.ai.pre_processing.guardrails_input import GuardrailBlockedError, check_input
from src.hrb_chatbot.ai.rag_pipeline.response_generation.guardrails_output import check_output
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.adhoc_chat import ALLOWED_EXTENSIONS, MAX_FILES, MAX_FILE_SIZE_BYTES, AdhocDocumentChatResponse
from src.hrb_chatbot.models.common import UserProfile

logger = get_logger("adhoc_document_chat")

router_adhoc_document_chat = APIRouter(tags=["adhoc-chat"])


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


@router_adhoc_document_chat.post("/query", response_model=AdhocDocumentChatResponse)
async def adhoc_document_chat(
    request: Request,
    user_profile: str = Form(...),
    question: str = Form(..., min_length=1, max_length=2000),
    recipient_email: str | None = Form(None),
    files: list[UploadFile] = File(...),
):
    try:
        parsed_profile = UserProfile.model_validate_json(user_profile)
    except ValidationError:
        return json_error(422, "user_profile is not valid JSON, or doesn't match the expected shape.", code=error_codes.VALIDATION_ERROR)

    # Open to all 3 roles, unlike document upload - a personal, ephemeral
    # tool that touches no shared state, not KB management.
    require_role(parsed_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT)
    await enforce_rate_limit(request)

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
            file_texts[file.filename] = await check_input(extracted_text)
        except GuardrailBlockedError as error:
            return json_error(
                422,
                f"{file.filename!r} was rejected by a safety check: {error}",
                code=error_codes.INPUT_GUARDRAIL_BLOCKED,
            )
        file_bytes[file.filename] = content

    try:
        checked_question = await check_input(question)
    except GuardrailBlockedError as error:
        return json_error(422, str(error), code=error_codes.INPUT_GUARDRAIL_BLOCKED)

    # The agent gets the recipient_email folded into the question itself
    # when given, since SendEmailWithAnswer is a real tool call the agent
    # decides to make, not something this route drives directly.
    agent_question = checked_question
    if recipient_email:
        agent_question = f"{checked_question}\n\n(Please email the answer to {recipient_email}.)"

    try:
        result = await adhoc_document_agent.run_agent(agent_question, file_texts, file_bytes)
    except Exception as error:
        logger.error("Adhoc document chat failed for %r: %s: %s", question, type(error).__name__, error)
        return json_error(500, "The question could not be answered. Please try again.", code=error_codes.QUERY_FAILED)

    result["answer"] = await check_output(checked_question, result["answer"])

    return AdhocDocumentChatResponse(
        question=question,
        answer=result["answer"],
        files_used=result["files_used"],
        web_searches=result["web_searches"],
        email_sent_to=result["email_sent_to"],
        model_used=result["model_used"],
        iterations=result["iterations"],
        llm_call_count=result["llm_call_count"],
        token_usage=result["token_usage"],
        latency_ms=result["latency_ms"],
    )
