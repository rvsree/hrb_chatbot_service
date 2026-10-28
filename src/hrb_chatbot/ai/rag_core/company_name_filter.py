"""Deterministic real-company-name check - the backstop the LLM-based NeMo
self_check_input/self_check_output rails proved (Phase 257) they can't be
alone. No LLM call, no classifier judgment - a plain regex, so it can never
be talked out of catching a match the way an LLM-judged rail can."""

import re

# Word-boundary anchored so "chase" never matches inside "purchase" - \b
# requires a non-word character on both sides, and the "r" immediately
# before "chase" in "purchase" is itself a word character, so the boundary
# never fires there. Verified against this exact false positive.
_COMPANY_NAME_PATTERN = re.compile(
    r"""
    \bj\.?\s*p\.?\s*morgan\b     # JPMorgan, JP Morgan, J.P. Morgan, J P Morgan
    | \bjpmorganchase\b          # JPMorganChase (no space)
    | \bjpmc\b                   # JPMC
    | \bjpm\b                    # JPM (standalone ticker-style abbreviation)
    | \bmorgan\s*chase\b         # Morgan Chase / MorganChase (without a JP prefix)
    | \bchase\b                  # bare Chase / Chase Bank / Chase.com
    """,
    re.IGNORECASE | re.VERBOSE,
)


def contains_real_company_reference(text: str) -> bool:
    """True if text names the real former-employer company in any form the
    pattern above covers. Used as an early-exit check on user input and as
    the final gate on a generated answer, before either reaches the caller."""
    return bool(_COMPANY_NAME_PATTERN.search(text or ""))
