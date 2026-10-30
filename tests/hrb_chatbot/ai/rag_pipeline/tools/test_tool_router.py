"""Tests for the Dynamic Tool Router (Phase 277) - validates a proposed
tool call's arguments against AGENTIC_TOOL_DEFINITIONS's own real schema,
the same one the LLM itself was given."""

from src.hrb_chatbot.ai.rag_pipeline.tools.tool_router import validate_tool_call


def test_unknown_tool_name_is_rejected():
    assert validate_tool_call("NotARealTool", {"input": "x"}) == "unknown tool 'NotARealTool'"


def test_non_dict_args_is_rejected():
    error = validate_tool_call("SearchKnowledgeBase", "not a dict")
    assert error == "arguments must be a JSON object, got str"


def test_search_knowledge_base_missing_input_is_rejected():
    error = validate_tool_call("SearchKnowledgeBase", {})
    assert error == "missing required field 'input'"


def test_search_knowledge_base_empty_string_input_is_rejected():
    error = validate_tool_call("SearchKnowledgeBase", {"input": ""})
    assert error == "missing required field 'input'"


def test_search_knowledge_base_valid_call_passes():
    assert validate_tool_call("SearchKnowledgeBase", {"input": "what is the dental plan?"}) is None


def test_search_knowledge_base_invalid_enum_value_is_rejected():
    error = validate_tool_call(
        "SearchKnowledgeBase", {"input": "x", "search_strategy": "not_a_real_strategy"}
    )
    assert error == "field 'search_strategy' must be one of ['similarity', 'mmr'], got 'not_a_real_strategy'"


def test_search_knowledge_base_valid_enum_value_passes():
    assert validate_tool_call("SearchKnowledgeBase", {"input": "x", "search_strategy": "mmr"}) is None


def test_get_leave_balance_with_no_args_passes():
    """Phase 277 - GetLeaveBalance's own TOOL_FUNCTIONS implementation never
    reads args at all (always uses the caller's own employee_id) - the
    schema's own "input" field is deliberately not required, matching that
    real behavior (fixed from an actual mismatch found while building this)."""
    assert validate_tool_call("GetLeaveBalance", {}) is None


def test_get_leave_history_with_no_args_passes():
    assert validate_tool_call("GetLeaveHistory", {}) is None
