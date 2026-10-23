"""Tests for Phase 248's context_assembly.py - assemble_context() bundles
STM (via conversation_memory, Phase 247's cache-aside path), the latest
feedback signal, and intent classification (mode_router, Phase 240) into one
RequestContext. All 3 sources are faked - no real Redis/Postgres/LLM call."""

from langchain_core.messages import AIMessage, HumanMessage

from src.hrb_chatbot.ai.search_pre_processing import context_assembly, conversation_memory
from tests.conftest import FakeDBGateway, FakeFeedbackStore

EMPLOYEE_USER_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}


def _patch_gateway(monkeypatch, feedback_store=None):
    gateway = FakeDBGateway(feedback_store=feedback_store or FakeFeedbackStore())
    monkeypatch.setattr(context_assembly, "get_db_gateway", lambda: gateway)
    monkeypatch.setattr(conversation_memory, "get_db_gateway", lambda: gateway)
    return gateway


def _patch_classify(monkeypatch, mode="single"):
    async def _fake_classify(query, router_model=None):
        return mode

    monkeypatch.setattr(context_assembly, "classify_query_complexity", _fake_classify)


async def test_no_conversation_id_means_empty_stm_and_no_feedback(monkeypatch):
    _patch_gateway(monkeypatch)
    _patch_classify(monkeypatch)

    context = await context_assembly.assemble_context(EMPLOYEE_USER_PROFILE, None, "What is the pto policy?")

    assert context.stm == []
    assert context.feedback is None
    assert context.classification == "single"
    assert context.user_profile == EMPLOYEE_USER_PROFILE
    assert context.query == "What is the pto policy?"


async def test_an_existing_conversation_assembles_its_stm(monkeypatch):
    gateway = _patch_gateway(monkeypatch)
    _patch_classify(monkeypatch)
    await conversation_memory.save_turn("conv-1", "EMP052", "what is the pto policy?", "15 days a year.")

    context = await context_assembly.assemble_context(EMPLOYEE_USER_PROFILE, "conv-1", "and the sick leave policy?")

    assert context.stm == [
        HumanMessage(content="what is the pto policy?"),
        AIMessage(content="15 days a year."),
    ]


async def test_the_latest_feedback_for_this_conversation_is_surfaced(monkeypatch):
    feedback_store = FakeFeedbackStore()
    _patch_gateway(monkeypatch, feedback_store=feedback_store)
    _patch_classify(monkeypatch)
    await feedback_store.save_feedback("EMP052", "conv-1", "msg-1", "down", ["wrong"], None, "q1", "a1")
    await feedback_store.save_feedback("EMP052", "conv-1", "msg-2", "up", [], None, "q2", "a2")

    context = await context_assembly.assemble_context(EMPLOYEE_USER_PROFILE, "conv-1", "a third question")

    assert context.feedback["vote"] == "up"  # the most recently saved entry, not the first


async def test_feedback_from_a_different_conversation_is_not_surfaced(monkeypatch):
    feedback_store = FakeFeedbackStore()
    _patch_gateway(monkeypatch, feedback_store=feedback_store)
    _patch_classify(monkeypatch)
    await feedback_store.save_feedback("EMP052", "conv-other", "msg-1", "down", ["wrong"], None, "q1", "a1")

    context = await context_assembly.assemble_context(EMPLOYEE_USER_PROFILE, "conv-1", "a question")

    assert context.feedback is None


async def test_classification_comes_from_the_router(monkeypatch):
    _patch_gateway(monkeypatch)
    _patch_classify(monkeypatch, mode="multi")

    context = await context_assembly.assemble_context(EMPLOYEE_USER_PROFILE, None, "a multi-domain question")

    assert context.classification == "multi"
