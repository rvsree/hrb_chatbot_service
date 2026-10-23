"""Context Builder (Phase 72) - assembles retrieved material into one
prompt-ready string, reused by genai-rag and multi-agentic-rag's Reviewer
Agent. Post-retrieval assembly only - query decomposition is a separate,
pre-retrieval step (see query_decompose.py), not folded in here."""


def build_context_from_chunks(chunks: list[dict]) -> str:
    """genai-rag's context shape - one block per retrieved chunk, labeled
    with its source filename so the model's answer can cite it."""
    blocks = [f"[{chunk['filename']}, chunk {chunk['chunk_index']}]\n{chunk['text']}" for chunk in chunks]
    return "\n\n".join(blocks)


def build_context_from_agent_results(agent_results: list[dict]) -> str:
    """multi-agentic-rag's context shape - one block per domain agent's
    result, labeled with which agent produced it."""
    blocks = [f"[{result['agent']}] {result['result']}" for result in agent_results]
    return "\n\n".join(blocks)
