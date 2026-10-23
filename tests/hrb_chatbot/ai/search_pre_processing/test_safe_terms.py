"""Phase 113: protect_known_safe_terms() wraps known false-positive terms
invisibly - confirmed live against a real Presidio AnalyzerEngine call
that this breaks NER tagging without changing the visible text."""

from src.hrb_chatbot.ai.search_pre_processing.safe_terms import SAFE_TERMS_NOT_PII, protect_known_safe_terms


def test_known_safe_term_is_wrapped():
    protected = protect_known_safe_terms("You can make Roth contributions.")
    assert protected != "You can make Roth contributions."
    assert "Roth" in protected  # the visible characters are untouched


def test_wrapping_is_invisible_when_isolate_marks_are_stripped():
    protected = protect_known_safe_terms("You can make Roth contributions.")
    visible = protected.replace("⁦", "").replace("⁩", "")
    assert visible == "You can make Roth contributions."


def test_text_with_no_safe_terms_is_unchanged():
    text = "What is the dental plan deductible?"
    assert protect_known_safe_terms(text) == text


def test_every_safe_term_gets_wrapped():
    text = " ".join(SAFE_TERMS_NOT_PII)
    protected = protect_known_safe_terms(text)
    for term in SAFE_TERMS_NOT_PII:
        assert f"⁦{term}⁩" in protected
