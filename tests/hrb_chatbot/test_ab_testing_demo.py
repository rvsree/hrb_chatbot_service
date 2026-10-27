"""A simulated A/B test - a REFERENCE PATTERN, not real evaluation
infrastructure (that's Phase 8, not built yet - see docs/agent-reference/RAG-ROADMAP.md).
Demonstrates the shape of a comparison - run config A, run config B,
compare one concrete metric - using only chunking, since it needs no
network call. See docs/agent-reference/TESTING-GUIDE.md for the full walkthrough."""

from src.hrb_chatbot.ai.doc_processing.chunking.text_chunker import chunk_text

# Long enough that chunk_size actually changes how many pieces it splits
# into - short strings wouldn't exercise the comparison meaningfully.
SAMPLE_POLICY_TEXT = (
    "Amazing Bank provides 16 weeks of fully paid parental leave to all "
    "eligible employees for the birth or placement of a child for adoption. "
    "This gender-neutral policy applies equally to all parents regardless "
    "of gender, marital status, or caregiver role. Employees must be "
    "actively employed on a U.S. payroll and regularly scheduled to work "
    "20 or more hours per week to qualify. New hires are eligible "
    "immediately upon meeting benefits eligibility requirements. "
) * 5


def test_ab_comparison_smaller_chunk_size_produces_more_chunks():
    """Configuration A (chunk_size=300) vs. B (chunk_size=1000), same
    input, one concrete metric (chunk count) compared between them."""
    configuration_a_chunk_size = 300
    configuration_b_chunk_size = 1000

    chunks_a = chunk_text(SAMPLE_POLICY_TEXT, chunk_size=configuration_a_chunk_size, chunk_overlap=30)
    chunks_b = chunk_text(SAMPLE_POLICY_TEXT, chunk_size=configuration_b_chunk_size, chunk_overlap=100)

    # The checkable claim: smaller chunk_size produces at least as many
    # chunks as larger chunk_size, not a vague "chunking works" assertion.
    assert len(chunks_a) >= len(chunks_b)


def test_ab_comparison_report_shape():
    """Demonstrates building a comparison report dict - the shape a real
    A/B result should take, easy to log/store/diff against a previous run."""
    configurations = {
        "small_chunks": {"chunk_size": 300, "chunk_overlap": 30},
        "large_chunks": {"chunk_size": 1000, "chunk_overlap": 100},
    }

    report = {}
    for name, config in configurations.items():
        chunks = chunk_text(SAMPLE_POLICY_TEXT, **config)

        total_length = 0
        for chunk in chunks:
            total_length += len(chunk)

        report[name] = {
            "chunk_count": len(chunks),
            "average_chunk_length": total_length / len(chunks),
        }

    assert report["small_chunks"]["chunk_count"] > report["large_chunks"]["chunk_count"]
    assert report["small_chunks"]["average_chunk_length"] < report["large_chunks"]["average_chunk_length"]
