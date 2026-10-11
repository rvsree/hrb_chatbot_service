"""Tests for generate_answer() (ai/rag_pipeline/response_generation/
response_generator.py) - a real LCEL chain (ChatPromptTemplate |
GatewayChatModel | result-mapper). Covers: no-chunks short-circuits
without calling the LLM, the grounding instructions and filenames
actually reach the prompt, and model_name is threaded through to
GatewayChatModel. GatewayChatModel is faked the same way
test_retriever.py already fakes it (a BaseChatModel subclass) - no real
network call."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.messages.ai import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from src.hrb_chatbot.ai.rag_pipeline.response_generation import response_generator

SAMPLE_CHUNKS = [
    {"document_id": "doc-1", "filename": "policy.pdf", "chunk_index": 0, "text": "Leave is 16 weeks.", "score": 0.9}
]


class _FakeGatewayChatModel(BaseChatModel):
    """Stands in for GatewayChatModel - records every prompt it was
    invoked with and returns a canned answer, tagged with whichever
    model it was "built" with (matching response_metadata["model"])."""

    response_text: str = "16 weeks of parental leave."
    model_name_override: str | None = None
    calls: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-gateway"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        generation = ChatGeneration(
            message=AIMessage(
                content=self.response_text,
                response_metadata={"model": self.model_name_override or "gpt-4.1-mini"},
            )
        )
        return ChatResult(generations=[generation])


def test_no_chunks_returns_the_no_context_answer_without_calling_the_llm(monkeypatch):
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    result = response_generator.generate_answer("any question", chunks=[])

    assert result["answer"] == response_generator.NO_CONTEXT_ANSWER
    assert fake_llm.calls == []  # never called - no chunks means nothing to ground on


def test_no_chunks_but_chat_history_answers_from_history_not_the_canned_response(monkeypatch):
    # Phase 87: the real bug this covers - a follow-up question that
    # retrieval can't match on its own must still use conversation memory,
    # not silently fall back to the free no-context answer.
    fake_llm = _FakeGatewayChatModel(response_text="You asked about parental leave a moment ago.")
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)
    history = [HumanMessage(content="How much parental leave do I get?"), AIMessage(content="16 weeks.")]

    result = response_generator.generate_answer("What did I just ask you about?", chunks=[], chat_history=history)

    assert result["answer"] == "You asked about parental leave a moment ago."
    assert len(fake_llm.calls) == 1  # unlike the no-history case, the LLM IS called here


def test_no_chunks_and_no_chat_history_still_returns_the_canned_answer(monkeypatch):
    # Unchanged behavior: genuinely nothing to work with (no retrieval, no history).
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    result = response_generator.generate_answer("any question", chunks=[], chat_history=[])

    assert result["answer"] == response_generator.NO_CONTEXT_ANSWER
    assert fake_llm.calls == []


def test_conversational_fallback_prompt_is_scoped_to_history_only_not_the_rag_examples(monkeypatch):
    # Regression: must NOT use RAG_PROMPT's context-citation few-shot
    # examples when there are no chunks - that prompt assumes fresh
    # document context exists, which it doesn't here.
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)
    history = [HumanMessage(content="What's the tuition cap?"), AIMessage(content="$5,250/year.")]

    response_generator.generate_answer("Can you repeat that?", chunks=[], chat_history=history)

    system_message = fake_llm.calls[0][0]
    assert "Example 1" not in system_message.content
    assert "prior conversation" in system_message.content


def test_generate_answer_returns_the_model_that_actually_answered(monkeypatch):
    fake_llm = _FakeGatewayChatModel(response_text="16 weeks of parental leave.")
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    result = response_generator.generate_answer("How much leave?", SAMPLE_CHUNKS)

    assert result["answer"] == "16 weeks of parental leave."
    assert result["model_used"] == "gpt-4.1-mini"
    assert len(fake_llm.calls) == 1


def test_context_cites_filename_and_chunk_index(monkeypatch):
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    response_generator.generate_answer("How much leave?", SAMPLE_CHUNKS)

    system_message = fake_llm.calls[0][0]
    assert "policy.pdf" in system_message.content
    assert "chunk 0" in system_message.content
    assert "Leave is 16 weeks." in system_message.content


def test_system_message_carries_the_grounding_instruction(monkeypatch):
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    response_generator.generate_answer("How much leave?", SAMPLE_CHUNKS)

    system_message, human_message = fake_llm.calls[0]
    assert "ONLY the context" in system_message.content
    assert "say you don't know" in system_message.content
    assert human_message.content == "How much leave?"


def test_system_message_carries_few_shot_examples(monkeypatch):
    # Regression: all 4 examples, including the refusal one, must reach the model.
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    response_generator.generate_answer("How much leave?", SAMPLE_CHUNKS)

    system_message, _ = fake_llm.calls[0]
    assert "Example 1" in system_message.content
    assert "Example 2" in system_message.content
    assert "Example 3" in system_message.content
    assert "Example 4" in system_message.content
    assert "I don't have that information in the available documents" in system_message.content


def test_model_name_override_is_passed_to_gateway_chat_model(monkeypatch):
    captured_kwargs = {}

    def fake_gateway_chat_model(**kwargs):
        captured_kwargs.update(kwargs)
        return _FakeGatewayChatModel(
            model_name_override=kwargs.get("model_name_override"), response_text="overridden-model answer"
        )

    monkeypatch.setattr(response_generator, "GatewayChatModel", fake_gateway_chat_model)

    result = response_generator.generate_answer("How much leave?", SAMPLE_CHUNKS, model_name="gpt-4.1-nano")

    assert captured_kwargs["model_name_override"] == "gpt-4.1-nano"
    assert result["model_used"] == "gpt-4.1-nano"
    assert result["answer"] == "overridden-model answer"


def test_tabular_instruction_added_when_query_says_summarize(monkeypatch):
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    response_generator.generate_answer("Summarize my benefits", SAMPLE_CHUNKS)

    system_message, _ = fake_llm.calls[0]
    assert "markdown table" in system_message.content


def test_tabular_instruction_absent_for_a_plain_query(monkeypatch):
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    response_generator.generate_answer("How much leave?", SAMPLE_CHUNKS)

    system_message, _ = fake_llm.calls[0]
    assert "markdown table" not in system_message.content


# --- Phase 132: llm_context_turn - the real rendered prompt, captured for Explainability ---


def test_llm_context_turn_is_none_when_no_llm_call_happened(monkeypatch):
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    result = response_generator.generate_answer("any question", chunks=[])

    assert result["llm_context_turn"] is None


def test_llm_context_turn_captures_the_real_rendered_prompt(monkeypatch):
    fake_llm = _FakeGatewayChatModel(response_text="16 weeks of parental leave.")
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)

    result = response_generator.generate_answer("How much leave?", SAMPLE_CHUNKS)

    turn = result["llm_context_turn"]
    assert turn["label"] == "answer"
    assert "ONLY the context" in turn["system_prompt"]
    assert "policy.pdf" in turn["system_prompt"]
    assert turn["human_message"] == "How much leave?"
    assert turn["chat_history"] == []
    assert turn["response"] == "16 weeks of parental leave."


def test_llm_context_turn_includes_chat_history_as_role_content_pairs(monkeypatch):
    fake_llm = _FakeGatewayChatModel()
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)
    history = [HumanMessage(content="What's the tuition cap?"), AIMessage(content="$5,250/year.")]

    result = response_generator.generate_answer("How much leave?", SAMPLE_CHUNKS, chat_history=history)

    assert result["llm_context_turn"]["chat_history"] == [
        {"role": "human", "content": "What's the tuition cap?"},
        {"role": "ai", "content": "$5,250/year."},
    ]


def test_llm_context_turn_captured_on_the_conversational_fallback_path_too(monkeypatch):
    fake_llm = _FakeGatewayChatModel(response_text="You asked about parental leave a moment ago.")
    monkeypatch.setattr(response_generator, "GatewayChatModel", lambda **kwargs: fake_llm)
    history = [HumanMessage(content="How much parental leave do I get?"), AIMessage(content="16 weeks.")]

    result = response_generator.generate_answer("What did I just ask you about?", chunks=[], chat_history=history)

    turn = result["llm_context_turn"]
    assert turn is not None
    assert turn["human_message"] == "What did I just ask you about?"
    assert turn["response"] == "You asked about parental leave a moment ago."
    assert "prior conversation" in turn["system_prompt"]
