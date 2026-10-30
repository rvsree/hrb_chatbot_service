"""Reranking (Phase 279) - a real gap found while checking: "no dedicated
re-ranking step exists anywhere" (confirmed via a project-wide grep before
this phase started, not assumed). similarity/mmr search both return chunks
in whatever order the vector store's own ANN search or MMR's diversity
algorithm produced - a weaker relevance signal than asking an LLM to look
at the query and every candidate chunk together, the same "ask one LLM
call, not one per chunk" cost discipline golden_dataset_harness.py's own
evaluate_retrieval_relevance() already established for exactly this kind
of judge call (precision/recall estimation) - this is that same mechanic,
reused for a different purpose: reordering BEFORE generation, not scoring
AFTER it. Deliberately not evaluate_retrieval_relevance() itself - that
function serves a different pipeline stage (post-hoc metrics) with a
different output shape (a relevance set, not a ranked order); reusing it
directly would couple two things this project's own "three libraries, one
per stage, don't consolidate without a reason" philosophy argues against."""

from langsmith import traceable

from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_pipeline.reranker")


def reranking_enabled() -> bool:
    """Same _is_enabled pattern as eval_threshold.py's own EVAL_*_ENABLED
    flags - a config-only kill switch (no redeploy needed) if the extra
    LLM call's cost/latency ever needs to be turned off."""
    return read_setting(None, "RAG_RERANK_ENABLED", "true").strip().lower() == "true"


@traceable(name="rerank_chunks")
async def rerank_chunks(query: str, chunks: list[dict], judge_model: str | None = None) -> list[dict]:
    """Reorders chunks by relevance to query, most relevant first - one LLM
    call for the whole batch, same cost discipline as every other judge
    call in this project. Fails safe: on any error (LLM call failure,
    malformed response), returns chunks in their ORIGINAL order unchanged -
    reranking must never be the reason a query fails or loses a chunk.
    Never drops a chunk either - every index in the input is guaranteed to
    appear exactly once in the output, even if the LLM's own response
    omitted or hallucinated one."""
    if not reranking_enabled() or len(chunks) <= 1:
        return chunks

    client = get_client_gateway().openai_chat()
    numbered_chunks = "\n\n".join(f"[{index + 1}] {chunk['text']}" for index, chunk in enumerate(chunks))
    prompt = f"""Below are chunks retrieved for a question. Rank them by how relevant each one is
to answering the question, most relevant first. Include every chunk number exactly
once, even chunks that aren't very relevant - put those near the end, never drop one.

QUESTION:
{query}

CHUNKS:
{numbered_chunks}

Respond with just the chunk numbers in ranked order, most relevant first, comma-separated.
Format:
Ranked: 3, 1, 2"""

    try:
        output = client.ask(prompt, temperature=0.0, model_name_override=judge_model)
        ranked_line = next((line for line in output.split("\n") if line.startswith("Ranked:")), "")
        numbers_text = ranked_line.split(":", 1)[1].strip() if ranked_line else ""
        raw_order = [int(n.strip()) for n in numbers_text.split(",") if n.strip().isdigit()]
        # Same hallucination guard as evaluate_retrieval_relevance() - a
        # free-text LLM response can repeat or invent an out-of-range
        # number. Clamp to the real range and dedupe, preserving the
        # LLM's own first-seen order.
        seen: set[int] = set()
        ranked_indices = []
        for index in raw_order:
            if 1 <= index <= len(chunks) and index not in seen:
                ranked_indices.append(index)
                seen.add(index)
        # Append any chunk the LLM's response omitted, in their original
        # order - never silently drop a retrieved chunk because the judge
        # forgot to mention it.
        for index in range(1, len(chunks) + 1):
            if index not in seen:
                ranked_indices.append(index)

        return [chunks[index - 1] for index in ranked_indices]
    except Exception as error:
        logger.warning("Reranking failed for query=%r, keeping original order: %s", query, error)
        return chunks
