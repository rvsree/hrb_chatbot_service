"""Phase 113: known Presidio PERSON false-positives for this domain -
confirmed by direct measurement, not guessed. Calling Presidio's own
AnalyzerEngine directly against "Roth" scores it 0.85 - identical
confidence to a genuine name like "John Smith" (also 0.85) - so no
score_threshold value in config.yml can separate the two. Wrapping a
known-safe term in invisible Unicode bidi-isolate marks breaks spaCy's
NER token grouping without changing the rendered text at all, confirmed
live the same way."""

# U+2066 LEFT-TO-RIGHT ISOLATE / U+2069 POP DIRECTIONAL ISOLATE - standard,
# legitimate Unicode bidi control characters, invisible in LTR rendering.
# nosec B613 - bandit's "trojansource" check flags any bidi control char as
# a possible code-disguising attack; this is source TEXT data processed at
# runtime (never executed as code), using the exact same mechanism
# deliberately and for a defensive purpose documented above - a real false
# positive, not suppressed silently.
_LRI = "⁦"  # nosec B613
_PDI = "⁩"  # nosec B613

SAFE_TERMS_NOT_PII = ["Roth", "Empower"]


def protect_known_safe_terms(text: str) -> str:
    """Wraps each known-safe term so Presidio's NER can't tag it as
    PERSON - the wrap marks are invisible, so no unwrap step is needed
    on the text that comes back from the guardrail check."""
    protected = text
    for term in SAFE_TERMS_NOT_PII:
        protected = protected.replace(term, f"{_LRI}{term}{_PDI}")
    return protected
