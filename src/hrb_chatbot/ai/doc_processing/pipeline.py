"""Orchestrates turning one stored PDF into indexed, searchable chunks."""

from src.hrb_chatbot.ai.doc_processing.chunking.text_chunker import (
    CHUNKING_STRATEGIES,
    DEFAULT_CHUNK_OVERLAP,
    chunk_text,
    chunk_text_with_sections,
    decide_chunk_size,
    decide_chunking_strategy,
    extract_text_from_pdf,
)
from src.hrb_chatbot.ai.doc_processing.embedding.embedding_generator import generate_embeddings
from src.hrb_chatbot.ai.doc_processing.indexing.vector_indexer import apply_extracted_chunk_metadata, write_chunks
from src.hrb_chatbot.ai.doc_processing.metadata_extraction.document_metadata_extractor import (
    EMPTY_RESULT,
    extract_document_metadata,
)
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.llm_client.openai_client import OpenAIEmbeddingClient
from src.hrb_chatbot.common.config.settings import get_active_vector_db, read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("doc_processing.pipeline")


def chunk_document(
    text: str,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[str]:
    """Split already-extracted text into chunks, using chunking_strategy/
    chunk_size if given, or auto-selecting both if not - see text_chunker.chunk_text()."""
    if chunk_overlap is None:
        resolved_overlap = DEFAULT_CHUNK_OVERLAP
    else:
        resolved_overlap = chunk_overlap

    return chunk_text(
        text,
        chunking_strategy=chunking_strategy,
        chunk_size=chunk_size,
        chunk_overlap=resolved_overlap,
    )


async def index_document(
    document_id: str,
    file_path: str,
    vector_db: str | None = None,
    chunking_strategy: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    embedding_model: str | None = None,
    document_metadata_override: dict | None = None,
) -> dict:
    if chunking_strategy and chunking_strategy not in CHUNKING_STRATEGIES:
        raise ValueError(
            f"Unknown chunking_strategy {chunking_strategy!r} - choose one of {list(CHUNKING_STRATEGIES)}"
        )

    resolved_vector_db = get_active_vector_db(vector_db)
    resolved_embedding_model = embedding_model or read_setting(
        None, "OPENAI_EMBED_MODEL", OpenAIEmbeddingClient.DEFAULT_MODEL
    )

    if chunk_overlap is None:
        resolved_chunk_overlap = DEFAULT_CHUNK_OVERLAP
    else:
        resolved_chunk_overlap = chunk_overlap

    logger.info(
        "Indexing document %s from %s (vector_db=%s, chunking_strategy=%s, embedding_model=%s, "
        "chunk_size=%s, chunk_overlap=%s)",
        document_id,
        file_path,
        resolved_vector_db,
        chunking_strategy or "auto",
        resolved_embedding_model,
        chunk_size or "auto",
        resolved_chunk_overlap,
    )

    # Phase 100: both the sync upload path and the async Lambda path call
    # this one function - setting status here gives both the same granular
    # progress for free, instead of duplicating these calls in each caller.
    # Phase 134: "parsing" (PDF text extraction) split out from "chunking" -
    # these used to share one status, set before extraction even started.
    await get_db_gateway().metadata_store().update_status(document_id, "parsing")

    text = extract_text_from_pdf(file_path)
    # Computed here (possibly again) only so the response can report what
    # actually ran - decide_chunking_strategy()/decide_chunk_size() are pure, so this always agrees.
    resolved_chunking_strategy = chunking_strategy or decide_chunking_strategy(text)
    resolved_chunk_size = chunk_size or decide_chunk_size(text)

    await get_db_gateway().metadata_store().update_status(document_id, "chunking")
    # Phase 124 - section_ids is [None] * len(chunks) for every strategy
    # except "document_structure"; write_chunks() stores it as the new
    # per-chunk section_id metadata, omitted entirely when None.
    chunks, section_ids = chunk_text_with_sections(
        text,
        chunking_strategy=chunking_strategy,
        chunk_size=resolved_chunk_size,
        chunk_overlap=resolved_chunk_overlap,
    )

    await get_db_gateway().metadata_store().update_status(document_id, "embedding")
    # Module 1's own explicit step (Phase 44) - embeddings are computed here,
    # not inside write_chunks(), and attached directly to each chunk's node.
    embeddings = await generate_embeddings(chunks, embedding_model=resolved_embedding_model)

    # Phase 134: the actual vector-store write - its own stage, distinct
    # from "embedding" (computing the vectors) and "indexed" (done).
    await get_db_gateway().metadata_store().update_status(document_id, "indexing")
    result = await write_chunks(
        document_id,
        chunks,
        embeddings,
        vector_db=resolved_vector_db,
        embedding_model=resolved_embedding_model,
        chunking_strategy=resolved_chunking_strategy,
        chunk_size=resolved_chunk_size,
        chunk_overlap=resolved_chunk_overlap,
        section_ids=section_ids,
    )

    logger.info(
        "Document %s: %s (%d chunks indexed, %d stale chunks removed)",
        document_id,
        result["action"],
        result["chunks_indexed"],
        result["chunks_removed"],
    )

    # Extracted once, on first index only - not repeated/re-billed on a
    # re-index. Best-effort: a failure here is logged, never fails the index.
    document_metadata = dict(EMPTY_RESULT)
    if result["action"] == "insert":
        try:
            document_metadata = extract_document_metadata(text)
            # Whatever the caller sent overrides the extraction guess; a field left null keeps extraction's value.
            if document_metadata_override:
                for key, value in document_metadata_override.items():
                    if value is not None:
                        document_metadata[key] = value

            await get_db_gateway().metadata_store().record_document_metadata(document_id, **document_metadata)
            # Not known yet when write_chunks() wrote the chunks above -
            # patch them now (a re-index already knows them by write time).
            await apply_extracted_chunk_metadata(
                document_id,
                result["chunk_ids"],
                resolved_vector_db,
                doc_category=document_metadata["doc_category"],
                department=document_metadata["department"],
                doc_description=document_metadata["doc_description"],
            )
        except Exception as error:
            logger.warning(
                "Document metadata extraction/recording failed for %s: %s: %s",
                document_id,
                type(error).__name__,
                error,
            )

    return {
        "document_id": document_id,
        "vector_db": resolved_vector_db,
        "chunking_strategy": resolved_chunking_strategy,
        "embedding_model": resolved_embedding_model,
        "chunk_size": resolved_chunk_size,
        "chunk_overlap": resolved_chunk_overlap,
        "document_metadata": document_metadata,
        **result,
    }
