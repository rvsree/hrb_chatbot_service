"""Vector KB Agent is a thin wrapper - confirms it forwards to the real tool unchanged."""

from src.hrb_chatbot.ai.agents.domain_agents import vector_kb_agent


async def test_run_forwards_focus_to_search_knowledge_base(monkeypatch):
    captured = {}

    async def _fake_search(query, search_strategy=None, role=None, department=None):
        captured["query"] = query
        captured["search_strategy"] = search_strategy
        return "fake KB result"

    monkeypatch.setattr(vector_kb_agent, "search_knowledge_base", _fake_search)

    result = await vector_kb_agent.run("what is the 401k match?")

    assert result == "fake KB result"
    assert captured["query"] == "what is the 401k match?"
    assert captured["search_strategy"] is None


async def test_run_forwards_search_strategy_to_search_knowledge_base(monkeypatch):
    """Phase 228 - the only lever multi-agentic-rag has to influence
    retrieval strategy at all (unlike single-agentic-rag, there's no
    agent-level per-call choice here)."""
    captured = {}

    async def _fake_search(query, search_strategy=None, role=None, department=None):
        captured["search_strategy"] = search_strategy
        return "fake KB result"

    monkeypatch.setattr(vector_kb_agent, "search_knowledge_base", _fake_search)

    await vector_kb_agent.run("what is the 401k match?", search_strategy="mmr")

    assert captured["search_strategy"] == "mmr"
