"""Extracts PDF text and splits it into chunks via LangChain's own splitters
(workshop Module 2) - six plain functions, one per technique, no classes."""

import re

from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import (
    CharacterTextSplitter,
    HTMLHeaderTextSplitter,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from pypdf import PdfReader

from src.hrb_chatbot.ai.doc_processing.tables.table_extractor import extract_tables_from_pdf
from src.hrb_chatbot.common.config.settings import read_setting, read_url_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("doc_processing.chunking")

# 1000 chars keeps a chunk topically focused; 150 char overlap is roughly a
# sentence, enough that a boundary-split sentence still appears whole somewhere.
DEFAULT_CHUNK_SIZE = int(read_setting(None, "CHUNK_DEFAULT_SIZE", 1000))
DEFAULT_CHUNK_OVERLAP = int(read_setting(None, "CHUNK_DEFAULT_OVERLAP", 150))

# Below this length, a document fits in one chunk anyway - matches the "not
# critical for short tickets/documents" takeaway from workshop Module 1.
WHOLE_DOCUMENT_MAX_LENGTH = DEFAULT_CHUNK_SIZE

# table_extractor.py appends tables as [TABLE]...[/TABLE] blocks - pulled out
# before chunking (Phase 75) so a table is never split across two chunks.
TABLE_BLOCK_PATTERN = re.compile(r"\[TABLE\](.*?)\[/TABLE\]", re.DOTALL)

# Phase 124 - matches this project's real KB documents' actual heading style
# ("Section 2: Eligibility", "2.1 Employee Eligibility"), verified by regex
# count against every real file in resources/kb_docs/ - not a markdown/HTML
# heading guess, which never fires on real PDF-extracted text.
SECTION_HEADING_PATTERN = re.compile(r"^Section \d+:\s*(.+)$", re.MULTILINE)
SUBSECTION_HEADING_PATTERN = re.compile(r"^\d+\.\d+ ([A-Z].+)$", re.MULTILINE)

# Above this length, a document would fragment into 10+ tiny chunks at the
# default size, each losing surrounding context - use a larger chunk size instead.
LARGE_DOCUMENT_MIN_LENGTH = int(read_setting(None, "CHUNK_LARGE_DOCUMENT_MIN_LENGTH", 10_000))
LARGE_DOCUMENT_CHUNK_SIZE = int(read_setting(None, "CHUNK_LARGE_DOCUMENT_CHUNK_SIZE", 1500))


def _split_out_tables(text: str) -> tuple[str, list[str]]:
    """Pulls every [TABLE]...[/TABLE] block out of text - the table-free text
    plus each table block (with its markers) kept separate, so a table is
    never at the mercy of a chunk-size boundary and never influences
    chunk sizing for the rest of the document (Phase 75)."""
    table_blocks = [f"[TABLE]{match}[/TABLE]" for match in TABLE_BLOCK_PATTERN.findall(text)]
    text_without_tables = TABLE_BLOCK_PATTERN.sub("", text).strip()
    return text_without_tables, table_blocks


def extract_text_from_pdf(file_path: str) -> str:
    """Return every page's text plus any tables, appended as markdown blocks after the page text."""
    reader = PdfReader(file_path)
    pages_text = [page.extract_text() or "" for page in reader.pages]
    text = "\n\n".join(pages_text)

    tables = extract_tables_from_pdf(file_path)
    if tables:
        tables_section = "\n\n".join(f"[TABLE]\n{table}\n[/TABLE]" for table in tables)
        text = f"{text}\n\n{tables_section}"

    return text


def chunk_fixed(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    # Splits on a single separator only ("\n") - simple and fast, but may cut
    # a sentence in half. Good for quick prototypes, not the default.
    splitter = CharacterTextSplitter(separator="\n", chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return splitter.split_text(text)


def chunk_recursive(
    text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
) -> list[str]:
    # Tries paragraph, then line, then sentence breaks before falling back to
    # a hard cut - the workshop's own "recommended default" for general text.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " "],
    )
    return splitter.split_text(text)


def _split_oversized_chunks(chunks: list[str], max_chunk_size: int, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """Phase 149, extended Phase 156 - a safety net, not a replacement for a
    strategy's own primary splitting logic: re-splits any chunk over
    max_chunk_size with the recursive splitter. Originally built for
    SemanticChunker (no size ceiling of its own - a topically-uniform
    document could collapse into two 15K+ character chunks, diluting their
    embeddings); Phase 156 reuses it as the same safety cap for
    markdown/html/none too, so every strategy now respects a caller-given
    chunk_size, not just the 3 that take it as a direct split target."""
    result = []
    for chunk in chunks:
        if len(chunk) > max_chunk_size:
            result.extend(chunk_recursive(chunk, chunk_size=max_chunk_size, chunk_overlap=chunk_overlap))
        else:
            result.append(chunk)
    return result


def chunk_semantic(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    # Embeds each sentence and splits where meaning shifts, not at a fixed
    # size - higher quality, but costs one embedding call per sentence.
    # Phase 149/156: oversized results get capped at chunk_size - see
    # _split_oversized_chunks(). chunk_size only ever shrinks a chunk that's
    # already too large; it never forces smaller natural topic boundaries apart.
    api_key = read_setting(None, "OPENAI_API_KEY")
    base_url = read_url_setting(None, "OPENAI_BASE_URL", "https://api.openai.com/v1")
    embedding_model = read_setting(None, "OPENAI_EMBED_MODEL", "text-embedding-3-small")
    embeddings = OpenAIEmbeddings(api_key=api_key, base_url=base_url, model=embedding_model)
    splitter = SemanticChunker(embeddings, breakpoint_threshold_type="standard_deviation")
    raw_chunks = splitter.split_text(text)
    return _split_oversized_chunks(raw_chunks, chunk_size, chunk_overlap)


def chunk_markdown(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    # Splits on markdown headers (#, ##, ###) so each chunk stays under one
    # heading - for documentation/wikis, not plain PDF-extracted text (which
    # has no markdown headers at all, so this usually yields one big chunk -
    # Phase 156's chunk_size cap below is what keeps that case from being
    # the same oversized-chunk problem Phase 149 found in "semantic").
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
    )
    documents = splitter.split_text(text)
    chunks = [document.page_content for document in documents if document.page_content.strip()]
    return _split_oversized_chunks(chunks, chunk_size, chunk_overlap)


def chunk_html(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    # Same idea as chunk_markdown, but for <h1>/<h2>/<h3> tags instead -
    # same chunk_size cap, same reasoning (Phase 156).
    splitter = HTMLHeaderTextSplitter(headers_to_split_on=[("h1", "Header 1"), ("h2", "Header 2"), ("h3", "Header 3")])
    documents = splitter.split_text(text)
    chunks = [document.page_content for document in documents if document.page_content.strip()]
    return _split_oversized_chunks(chunks, chunk_size, chunk_overlap)


def chunk_none(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    # No deliberate splitting - fine for short content where a boundary
    # split would only lose context for no benefit. Phase 156: still capped
    # at chunk_size as a safety net for a document that turns out too large
    # for one chunk - without this, a big document under "none" hit the
    # exact same uncapped-giant-chunk problem Phase 149 fixed for "semantic".
    stripped = text.strip()
    if not stripped:
        return []
    return _split_oversized_chunks([stripped], chunk_size, chunk_overlap)


def _slugify(heading_text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", heading_text.strip().lower())
    return slug.strip("-")


def chunk_by_document_structure(
    text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
) -> list[dict]:
    """Phase 124 - splits on this project's real "Section N: Title"/"N.N
    Subtitle" headings, tagging each chunk with a stable section_id derived
    from the heading's own text (not its number, which can shift on a
    renumbered edit). Falls back to plain recursive chunking with
    section_id=None when no section headings are found - not an error."""
    section_matches = list(SECTION_HEADING_PATTERN.finditer(text))
    if not section_matches:
        return [{"text": chunk, "section_id": None} for chunk in chunk_recursive(text, chunk_size, chunk_overlap)]

    results: list[dict] = []

    preamble = text[: section_matches[0].start()].strip()
    if preamble:
        results += [{"text": chunk, "section_id": None} for chunk in chunk_recursive(preamble, chunk_size, chunk_overlap)]

    for index, match in enumerate(section_matches):
        section_end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(text)
        section_text = text[match.start() : section_end]
        section_slug = _slugify(match.group(1))

        subsection_matches = list(SUBSECTION_HEADING_PATTERN.finditer(section_text))
        if not subsection_matches:
            results += [
                {"text": chunk, "section_id": section_slug}
                for chunk in chunk_recursive(section_text, chunk_size, chunk_overlap)
            ]
            continue

        section_intro = section_text[: subsection_matches[0].start()].strip()
        if section_intro:
            results += [
                {"text": chunk, "section_id": section_slug}
                for chunk in chunk_recursive(section_intro, chunk_size, chunk_overlap)
            ]

        for sub_index, sub_match in enumerate(subsection_matches):
            sub_end = subsection_matches[sub_index + 1].start() if sub_index + 1 < len(subsection_matches) else len(section_text)
            subsection_text = section_text[sub_match.start() : sub_end]
            compound_id = f"{section_slug}/{_slugify(sub_match.group(1))}"
            results += [
                {"text": chunk, "section_id": compound_id}
                for chunk in chunk_recursive(subsection_text, chunk_size, chunk_overlap)
            ]

    return results


def chunk_document_structure(
    text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP
) -> list[str]:
    # CHUNKING_STRATEGIES-compatible wrapper, text only - call
    # chunk_by_document_structure()/chunk_text_with_sections() directly for section ids.
    return [chunk["text"] for chunk in chunk_by_document_structure(text, chunk_size, chunk_overlap)]


# Every strategy a caller can pass explicitly, mapped to its function -
# "semantic" is explicit-only (see decide_chunking_strategy), never auto-selected.
# "document_structure" is explicit-only too (Phase 124) - unlike semantic,
# it WOULD actually fire for every real KB document if auto-selected, so
# auto-enabling it risks silently shifting golden-dataset scores on a
# routine re-index; kept opt-in deliberately, not an oversight.
CHUNKING_STRATEGIES = {
    "fixed": chunk_fixed,
    "recursive": chunk_recursive,
    "semantic": chunk_semantic,
    "markdown": chunk_markdown,
    "html": chunk_html,
    "none": chunk_none,
    "document_structure": chunk_document_structure,
}


def decide_chunking_strategy(text: str) -> str:
    """Auto-pick a strategy when none was given - "semantic" stays explicit-only.
    Decided from the table-free text (Phase 75) - table markdown shouldn't
    influence prose-structure detection."""
    text_without_tables, _ = _split_out_tables(text)
    stripped = text_without_tables.strip()

    # A line is a markdown heading only if "#" starts it after stripping
    # leading whitespace - an incidental "#" mid-sentence doesn't count.
    heading_lines = [line for line in stripped.splitlines() if line.strip().startswith("#")]
    if heading_lines:
        logger.info(
            "chunking: auto-select rationale - %d markdown heading line(s) found -> 'markdown'",
            len(heading_lines),
        )
        return "markdown"

    lowered = stripped.lower()
    html_heading_tags_found = [tag for tag in ("<h1", "<h2", "<h3") if tag in lowered]
    if html_heading_tags_found:
        logger.info(
            "chunking: auto-select rationale - HTML heading tag(s) %s found -> 'html'",
            html_heading_tags_found,
        )
        return "html"

    character_count = len(stripped)
    if character_count <= WHOLE_DOCUMENT_MAX_LENGTH:
        logger.info(
            "chunking: auto-select rationale - %d character(s), at or under the %d-character "
            "whole-document threshold -> 'none'",
            character_count,
            WHOLE_DOCUMENT_MAX_LENGTH,
        )
        return "none"

    logger.info(
        "chunking: auto-select rationale - %d character(s), no markdown/HTML heading structure "
        "found, over the %d-character whole-document threshold -> 'recursive' (default)",
        character_count,
        WHOLE_DOCUMENT_MAX_LENGTH,
    )
    return "recursive"


def decide_chunk_size(text: str) -> int:
    """Auto-pick a chunk size when none was given - only grows past the default, never shrinks it.
    Tables no longer factor in (Phase 75): each table becomes its own whole
    chunk regardless of size (see chunk_text()), so there's no need to
    inflate chunk size for the rest of the document just because one table
    is large."""
    text_without_tables, _ = _split_out_tables(text)
    stripped = text_without_tables.strip()

    if len(stripped) > LARGE_DOCUMENT_MIN_LENGTH:
        chunk_size = LARGE_DOCUMENT_CHUNK_SIZE
        logger.info(
            "chunk_size: auto-select rationale - %d character(s) -> %d (default is %d)",
            len(stripped),
            chunk_size,
            DEFAULT_CHUNK_SIZE,
        )
        return chunk_size

    return DEFAULT_CHUNK_SIZE


def chunk_text(
    text: str,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text using the given strategy/chunk_size, or auto-select both if not given.
    Table blocks (Phase 75) are pulled out before splitting and appended as
    their own whole chunks afterward - a table can never be cut across two
    chunks, regardless of strategy or size. A document with no tables
    behaves exactly as before."""
    if chunking_strategy:
        strategy = chunking_strategy
        logger.info("chunking: explicit strategy=%s", strategy)
    else:
        strategy = decide_chunking_strategy(text)
        logger.info("chunking: auto-selected strategy=%s", strategy)

    if strategy not in CHUNKING_STRATEGIES:
        raise ValueError(f"Unknown chunking_strategy {strategy!r} - choose one of {list(CHUNKING_STRATEGIES)}")

    text_without_tables, table_blocks = _split_out_tables(text)

    chunk_function = CHUNKING_STRATEGIES[strategy]
    if not text_without_tables:
        prose_chunks = []
    else:
        # Phase 156: every strategy now takes chunk_size/chunk_overlap (as a
        # direct split target for fixed/recursive/document_structure, or as
        # a safety cap for semantic/markdown/html/none) - no more special
        # case for which 3 strategies "support" it.
        resolved_chunk_size = chunk_size if chunk_size is not None else decide_chunk_size(text)
        prose_chunks = chunk_function(text_without_tables, chunk_size=resolved_chunk_size, chunk_overlap=chunk_overlap)

    chunks = prose_chunks + table_blocks

    logger.info(
        "Split %d characters of text into %d chunks (strategy=%s, %d table block(s) kept whole)",
        len(text),
        len(chunks),
        strategy,
        len(table_blocks),
    )
    return chunks


def chunk_text_with_sections(
    text: str,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> tuple[list[str], list[str | None]]:
    """Phase 124 - like chunk_text(), but also returns a parallel list of
    section_ids (same length/order as the chunks). Only "document_structure"
    produces real section ids; every other strategy behaves exactly like
    chunk_text() and gets [None] * len(chunks) - zero behavior change for
    the other 6 strategies or chunk_text() itself."""
    if chunking_strategy != "document_structure":
        chunks = chunk_text(text, chunking_strategy, chunk_size, chunk_overlap)
        return chunks, [None] * len(chunks)

    text_without_tables, table_blocks = _split_out_tables(text)
    resolved_chunk_size = chunk_size if chunk_size is not None else decide_chunk_size(text)

    structured_chunks = chunk_by_document_structure(text_without_tables, resolved_chunk_size, chunk_overlap)
    chunks = [chunk["text"] for chunk in structured_chunks] + table_blocks
    section_ids: list[str | None] = [chunk["section_id"] for chunk in structured_chunks] + [None] * len(table_blocks)
    return chunks, section_ids
