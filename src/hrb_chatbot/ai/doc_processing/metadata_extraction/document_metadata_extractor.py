"""LLM-based extraction of document-level metadata - best-effort, never blocks indexing on a bad guess."""

import json

from langsmith import traceable

from src.hrb_chatbot.ai.prompts.extraction_prompts import DOCUMENT_METADATA_EXTRACTION_PROMPT
from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("doc_processing.metadata_extraction")

# Most fields are on a document's first page - no need to pay for tokens sending the whole doc.
MAX_CHARACTERS_SENT = int(read_setting(None, "METADATA_EXTRACTION_MAX_CHARACTERS", 3000))

# author/doc_date/doc_version often live in a closing colophon, past the head excerpt above.
TAIL_CHARACTERS_SENT = int(read_setting(None, "METADATA_EXTRACTION_TAIL_CHARACTERS", 1000))

EMPTY_RESULT = {
    "owner": None,
    "department": None,
    "doc_category": None,
    "purpose": None,
    "doc_description": None,
    # Phase 231 - never filled in by extraction below (only str values are
    # ever written into result, line ~57); an access-control gate can't be
    # an LLM guess. Caller-supplied only, via document_metadata_override.
    "restricted_roles": None,
    "effective_date": None,
    "audience": None,
    "confidentiality_level": None,
    "author": None,
    "doc_date": None,
    "doc_version": None,
}

# Prompt text now lives in ai/prompts/extraction_prompts.py (Phase 63) - kept as
# a local alias so nothing else in this file has to change.
EXTRACTION_QUESTION = DOCUMENT_METADATA_EXTRACTION_PROMPT


@traceable(name="extract_document_metadata")
def extract_document_metadata(text: str) -> dict:
    """Return EMPTY_RESULT's 12 keys filled in where possible - never raises.
    Phase 270 - @traceable: the real LLM call below is raw, not LangChain-
    native - without this it was invisible in LangSmith at ingestion time."""
    if not text.strip():
        return dict(EMPTY_RESULT)

    head = text[:MAX_CHARACTERS_SENT]
    tail = text[-TAIL_CHARACTERS_SENT:] if len(text) > MAX_CHARACTERS_SENT + TAIL_CHARACTERS_SENT else ""
    excerpt = f"{head}\n\n...\n\n{tail}" if tail else head

    try:
        chat_client = get_client_gateway().openai_chat()
        response = chat_client.ask(EXTRACTION_QUESTION, context=excerpt, temperature=0.0)
        extracted = _parse_json_object(response)
    except Exception as error:
        logger.warning("Document metadata extraction failed: %s: %s", type(error).__name__, error)
        return dict(EMPTY_RESULT)

    result = dict(EMPTY_RESULT)
    for key in result:
        value = extracted.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


def _parse_json_object(response: str) -> dict:
    """Pulls out the outermost {...} - models sometimes wrap JSON in prose/a code fence despite instructions."""
    start = response.find("{")
    end = response.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    return json.loads(response[start : end + 1])
