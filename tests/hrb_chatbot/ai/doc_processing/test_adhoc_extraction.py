"""Tests for adhoc_extraction.py (Phase 136) - real PDF/DOCX/CSV bytes, no
fakes needed (pypdf/zipfile/csv are all real, fast, local, no network)."""

import io
import zipfile

import pytest

from src.hrb_chatbot.ai.doc_processing import adhoc_extraction


def _build_docx_bytes(paragraphs: list[str]) -> bytes:
    """A minimal real .docx - just enough word/document.xml for the real
    extractor to parse, not a full python-docx-generated file."""
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraphs_xml = "".join(
        f'<w:p xmlns:w="{namespace}"><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{namespace}"><w:body>{paragraphs_xml}</w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def test_extract_text_rejects_an_unsupported_extension():
    with pytest.raises(ValueError, match="Unsupported file type"):
        adhoc_extraction.extract_text("malware.exe", b"junk")


def test_extract_text_reads_csv_as_comma_joined_rows():
    content = b"name,role\nAlice,Manager\nBob,Employee\n"

    result = adhoc_extraction.extract_text("team.csv", content)

    assert result == "name, role\nAlice, Manager\nBob, Employee"


def test_extract_text_reads_docx_paragraph_text():
    content = _build_docx_bytes(["First paragraph.", "Second paragraph."])

    result = adhoc_extraction.extract_text("notes.docx", content)

    assert result == "First paragraph.\n\nSecond paragraph."


def test_docx_with_a_doctype_declaration_is_rejected_not_parsed():
    # Real security finding (bandit B314) - a DOCTYPE/ENTITY declaration is
    # the real XXE/entity-expansion-bomb attack vector; a real Word
    # document.xml never legitimately has one, so this rejects rather than
    # parses it, without adding a new XML library.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE foo [<!ENTITY xxe "boom">]><w:document/>',
        )

    with pytest.raises(ValueError, match="disallowed XML construct"):
        adhoc_extraction.extract_text("evil.docx", buffer.getvalue())


def test_extract_text_truncates_past_the_per_file_cap(monkeypatch):
    monkeypatch.setattr(adhoc_extraction, "MAX_CHARS_PER_FILE", 20)
    content = b"a,b\n" + b"1,2\n" * 20  # well past 20 characters

    result = adhoc_extraction.extract_text("big.csv", content)

    assert result.startswith("a, b\n1, 2\n1")
    assert "[truncated," in result
    assert len(result) < len(content)
