"""Context Builder (Phase 72) - pure string assembly, moved from
response_generator.py/reviewer_agent.py, same shape as before."""

from src.hrb_chatbot.ai.search_pre_processing.context_builder import (
    build_context_from_agent_results,
    build_context_from_chunks,
)


def test_build_context_from_chunks_labels_each_block_with_filename_and_index():
    chunks = [
        {"filename": "401k.pdf", "chunk_index": 1, "text": "100% match up to 5%."},
        {"filename": "tuition.pdf", "chunk_index": 0, "text": "$7,500 per year."},
    ]

    context = build_context_from_chunks(chunks)

    assert "[401k.pdf, chunk 1]\n100% match up to 5%." in context
    assert "[tuition.pdf, chunk 0]\n$7,500 per year." in context


def test_build_context_from_agent_results_labels_each_block_with_agent_name():
    agent_results = [
        {"agent": "vector_kb_agent", "focus": "parental leave", "result": "16 weeks paid."},
        {"agent": "lms_ops_agent", "focus": "my balance", "result": "10 days available."},
    ]

    context = build_context_from_agent_results(agent_results)

    assert "[vector_kb_agent] 16 weeks paid." in context
    assert "[lms_ops_agent] 10 days available." in context
