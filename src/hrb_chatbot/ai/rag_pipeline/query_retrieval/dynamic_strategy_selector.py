"""Phase 252 - resolves "dynamic" into one of the real SEARCH_STRATEGIES keys,
once per query, before retrieval runs. Heuristic, not an LLM call - see
RAG-ROADMAP.md Phase 252's own spec for why a paid classifier call wasn't
reused here. Its own file/class, not folded into retriever.py's dispatch,
per the user's own "logically segregate" instruction - true even though the
logic itself is a handful of simple rules."""

import re

# A short query, or one dominated by acronyms/numbers/codes, is more likely
# to hinge on an exact term a semantic embedding can blur past ("401k",
# "FMLA", "COBRA") - lexical matching (BM25) matters more than meaning here.
_ACRONYM_OR_CODE_PATTERN = re.compile(r"\b([A-Z]{2,}|\d+[A-Za-z]*)\b")
SHORT_QUERY_WORD_COUNT = 4

# Phrasing that asks for a broad sweep rather than one precise fact -
# diversity (MMR) avoids returning several near-duplicate chunks covering
# the same single point.
_BROAD_QUERY_PHRASES = ("tell me about", "what are my options", "overview of", "everything about", "all about")


class DynamicStrategySelector:
    """One public method, `select(query)` - deliberately a class (not a bare
    function) so this stays a single, obvious extension point if the
    heuristic ever needs per-call state (e.g. a cached corpus stat) later,
    without changing every call site's shape."""

    def select(self, query: str) -> str:
        words = query.split()
        acronym_or_code_hits = len(_ACRONYM_OR_CODE_PATTERN.findall(query))
        lowered = query.lower()

        if any(phrase in lowered for phrase in _BROAD_QUERY_PHRASES):
            return "mmr"

        if len(words) <= SHORT_QUERY_WORD_COUNT and acronym_or_code_hits > 0:
            return "keyword"

        if acronym_or_code_hits > 0:
            # Specific term(s) present, but in a longer, natural-language
            # question - neither pure semantic nor pure lexical search is
            # clearly better, so combine both via the existing hybrid strategy.
            return "hybrid"

        return "similarity"


def resolve_dynamic_strategy(query: str) -> str:
    """Module-level convenience wrapper - the one real call site
    (pipeline.py) doesn't need to construct/hold a DynamicStrategySelector
    instance itself."""
    return DynamicStrategySelector().select(query)
