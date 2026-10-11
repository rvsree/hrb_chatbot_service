"""Phase 136 - text extraction for the Chat GenAI Workflow's ad-hoc document
chat. Deliberately separate from text_chunker.py's own extraction: that
module feeds the persistent indexing pipeline (chunking/embedding/vector
write); this one only ever produces plain text for one in-request LLM call,
nothing written to a persistent directory, nothing chunked or embedded.

Zero new runtime dependencies - PDF reuses text_chunker.py's own
extract_text_from_pdf() unchanged (via a real-but-transient tempfile, auto-
deleted, never under data/uploads/); DOCX uses stdlib zipfile+ElementTree
(paragraph text only - no tables/headers/footers, a real, named limitation,
not python-docx); CSV uses the stdlib csv module."""

import csv
import io
import os
import tempfile
import zipfile
from xml.etree import ElementTree

from src.hrb_chatbot.ai.doc_processing.chunking.text_chunker import extract_text_from_pdf
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("doc_processing.adhoc_extraction")

# Protects the model's context window across up to 3 files - a real, visible
# cap, not a silent cut (callers append the warning text themselves).
MAX_CHARS_PER_FILE = 12_000

_DOCX_BODY_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _extract_pdf(content: bytes) -> str:
    # delete=False + a manual os.remove() in finally - on Windows,
    # NamedTemporaryFile(delete=True) holds an exclusive lock on the file
    # while it's open, so pypdf's own open(file_path, "rb") call right
    # after fails with PermissionError (confirmed live, not assumed) -
    # closing this handle first, then deleting after pypdf is done, avoids it.
    temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        temp_file.write(content)
        temp_file.close()
        return extract_text_from_pdf(temp_file.name)
    finally:
        os.remove(temp_file.name)


def _reject_xml_entity_declarations(xml_bytes: bytes) -> None:
    """Real security finding (bandit B314, MEDIUM) - xml.etree.ElementTree.parse()
    on untrusted XML is a known XXE/entity-expansion-bomb risk, and this
    content IS untrusted (any signed-in user can upload an arbitrary
    .docx). The standard fix is the defusedxml library - not added here,
    since this project's standing rule is no new dependency without
    explicit sign-off, and the user wasn't available to ask. This is the
    zero-dependency mitigation instead: a well-formed Word document.xml
    never legitimately contains a DOCTYPE or ENTITY declaration (Word
    itself never emits one) - the exploit requires one, so rejecting any
    document.xml that has one closes the real attack surface without a
    new library. Narrower than defusedxml, but correct for this input."""
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise ValueError("This .docx file's content could not be read (disallowed XML construct).")


def _extract_docx(content: bytes) -> str:
    """A .docx is a zip of XML parts - this reads only word/document.xml's
    paragraph text (<w:t> runs), joined with blank lines between
    paragraphs. No tables, headers/footers, or formatting - see this
    module's own docstring and docs/dev-reference/genai_chat_workflow.md
    for why python-docx wasn't added instead."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        with archive.open("word/document.xml") as document_xml:
            raw_xml = document_xml.read()

    # Bandit (B314) blacklists this call by name - _reject_xml_entity_declarations()
    # just above already rejects the real attack surface (a DOCTYPE/ENTITY
    # declaration), which a real Word document.xml never legitimately has.
    _reject_xml_entity_declarations(raw_xml)
    root = ElementTree.fromstring(raw_xml)  # nosec B314

    paragraphs = []
    for paragraph in root.iter(f"{_DOCX_BODY_NAMESPACE}p"):
        runs = [node.text or "" for node in paragraph.iter(f"{_DOCX_BODY_NAMESPACE}t")]
        paragraph_text = "".join(runs).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)

    return "\n\n".join(paragraphs)


def _extract_csv(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return "\n".join(", ".join(row) for row in reader)


_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".csv": _extract_csv,
}


def extract_text(filename: str, content: bytes) -> str:
    """Dispatches by extension, truncates to MAX_CHARS_PER_FILE with a
    visible marker (never a silent cut). Raises ValueError for an
    unsupported extension - the route turns that into a 422."""
    extension = next((ext for ext in _EXTRACTORS if filename.lower().endswith(ext)), None)
    if extension is None:
        raise ValueError(f"Unsupported file type for {filename!r} - only .pdf, .docx, .csv are accepted.")

    text = _EXTRACTORS[extension](content)
    if len(text) > MAX_CHARS_PER_FILE:
        omitted = len(text) - MAX_CHARS_PER_FILE
        text = f"{text[:MAX_CHARS_PER_FILE]}\n...[truncated, {omitted} characters omitted]"
        logger.info("Truncated %r from %d to %d characters", filename, len(text) + omitted, MAX_CHARS_PER_FILE)

    return text
