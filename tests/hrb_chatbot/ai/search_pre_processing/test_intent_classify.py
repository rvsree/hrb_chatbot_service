"""Tests for the keyword-based intent classifier (Phase 277)."""

from src.hrb_chatbot.ai.search_pre_processing.intent_classify import (
    INTENT_BENEFITS_FAQ,
    INTENT_LEAVE_BALANCE,
    INTENT_LEAVE_HISTORY,
    INTENT_LEAVE_REQUEST,
    classify_query_intent,
)


def test_leave_balance_keyword_is_classified():
    assert classify_query_intent("What's my PTO balance?") == INTENT_LEAVE_BALANCE


def test_leave_history_keyword_is_classified():
    assert classify_query_intent("Show my leave history for this year") == INTENT_LEAVE_HISTORY


def test_leave_request_keyword_is_classified():
    assert classify_query_intent("I want to request leave for next month") == INTENT_LEAVE_REQUEST


def test_benefits_question_falls_back_to_benefits_faq():
    assert classify_query_intent("What is the dental plan?") == INTENT_BENEFITS_FAQ


def test_classification_is_case_insensitive():
    assert classify_query_intent("WHAT IS MY PTO BALANCE") == INTENT_LEAVE_BALANCE
