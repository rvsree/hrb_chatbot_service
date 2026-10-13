"""Tests for Phase 136's ReAct loop - the LLM is faked (no real API call),
matching test_orchestration_agent.py's own established pattern. The real
behavior under test: ReadDocument only ever returns from the file_texts
dict passed in (no vector store, no MCP, nothing else it could call), and
SendEmailWithAnswer only fires when the agent actually calls it."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.hrb_chatbot.ai.agents.workflow_agents import adhoc_document_agent


@pytest.fixture(autouse=True)
def _fake_check_output_by_default(monkeypatch):
    # Phase 158 - check_output() (Phase 138's output guardrail) is a real
    # LLM call, separate from the agent's own _build_llm() this file's
    # docstring is about - every SendEmailWithAnswer test calls it, and
    # only one (test_send_email_tool_sends_the_output_guardrail_checked_
    # text_not_the_raw_text) actually cares what it does. Defaulting to a
    # passthrough here, overridden locally by that one test, keeps every
    # other test from needing a real OPENAI_API_KEY - a real gap CI caught
    # (passing locally only because of a real local key masking it).
    async def _passthrough_check_output(query, answer):
        return answer

    monkeypatch.setattr(adhoc_document_agent, "check_output", _passthrough_check_output)


class FakeResponse:
    def __init__(self, content="", tool_calls=None, model_name="gpt-4.1-mini-fake"):
        self.content = content
        self.tool_calls = tool_calls or []
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        self.model_name = model_name


class FakeLlm:
    def __init__(self, responses):
        self._responses = list(responses)
        self.model_name = "gpt-4.1-mini-fake"

    async def ainvoke(self, messages):
        return self._responses.pop(0)


def _patch_llm(monkeypatch, responses):
    monkeypatch.setattr(adhoc_document_agent, "_build_llm", lambda: FakeLlm(responses))


async def test_answers_without_a_tool_call_in_one_iteration(monkeypatch):
    _patch_llm(monkeypatch, [FakeResponse(content="Hi there!")])

    result = await adhoc_document_agent.run_agent("hello", {"a.pdf": "some text"}, {})

    assert result["answer"] == "Hi there!"
    assert result["files_used"] == []
    assert result["iterations"] == 1
    assert result["llm_call_count"] == 1


async def test_read_document_tool_returns_the_real_file_text(monkeypatch):
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(tool_calls=[{"name": "ReadDocument", "args": {"filename": "policy.pdf"}, "id": "call-1"}]),
            FakeResponse(content="16 weeks, per the document."),
        ],
    )

    result = await adhoc_document_agent.run_agent(
        "How much parental leave?", {"policy.pdf": "Parental leave is 16 weeks."}, {}
    )

    assert result["answer"] == "16 weeks, per the document."
    assert result["files_used"] == ["policy.pdf"]


async def test_read_document_for_an_unattached_filename_returns_an_error_to_the_agent(monkeypatch):
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(tool_calls=[{"name": "ReadDocument", "args": {"filename": "nope.pdf"}, "id": "call-1"}]),
            FakeResponse(content="I don't have access to that file."),
        ],
    )

    result = await adhoc_document_agent.run_agent("question", {"policy.pdf": "real text"}, {})

    assert result["files_used"] == []
    assert result["answer"] == "I don't have access to that file."


async def test_send_email_tool_sets_email_sent_to_on_success(monkeypatch):
    async def _fake_send_email_success(recipient, subject, body):
        return {"sent": True, "message": f"Email sent to {recipient}."}

    # send_email is synchronous in the real module - patch it as a plain function, not async.
    monkeypatch.setattr(adhoc_document_agent, "send_email", lambda recipient, subject, body, attachments=None, html_body=None: {"sent": True, "message": f"Email sent to {recipient}."})
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {"recipient_email": "someone@example.com", "answer": "The answer."},
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - I've emailed the answer."),
        ],
    )

    result = await adhoc_document_agent.run_agent("email me the answer", {"a.pdf": "text"}, {})

    assert result["email_sent_to"] == "someone@example.com"
    # Phase 161 - real evidence of the attempt, for the Explainability view.
    evidence = dict(result["email_evidence"])
    sent_at = evidence.pop("sent_at")
    assert evidence == {
        "recipient_email": "someone@example.com",
        "subject": "Your answer from HR Benefits Chat",
        "sent": True,
        "message": "Email sent to someone@example.com.",
        "attached_files": [],
    }
    assert sent_at.endswith("+00:00") or sent_at.endswith("Z")


async def test_send_email_tool_uses_the_agent_supplied_subject(monkeypatch):
    """Phase 141 - the subject used to be hardcoded ("Your answer from HR
    Benefits Chat") regardless of what the email was actually about. The
    agent now supplies its own subject as a tool argument."""
    sent_subjects = []

    def _capturing_send_email(recipient, subject, body, attachments=None, html_body=None):
        sent_subjects.append(subject)
        return {"sent": True, "message": f"Email sent to {recipient}."}

    monkeypatch.setattr(adhoc_document_agent, "send_email", _capturing_send_email)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {
                            "recipient_email": "someone@example.com",
                            "subject": "Your 401(k) employer match summary",
                            "answer": "The answer.",
                        },
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - I've emailed the answer."),
        ],
    )

    await adhoc_document_agent.run_agent("email me the answer", {"a.pdf": "text"}, {})

    assert sent_subjects == ["Your 401(k) employer match summary"]


async def test_send_email_tool_falls_back_to_a_generic_subject_if_the_agent_omits_one(monkeypatch):
    sent_subjects = []

    def _capturing_send_email(recipient, subject, body, attachments=None, html_body=None):
        sent_subjects.append(subject)
        return {"sent": True, "message": f"Email sent to {recipient}."}

    monkeypatch.setattr(adhoc_document_agent, "send_email", _capturing_send_email)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {"recipient_email": "someone@example.com", "answer": "The answer."},
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - I've emailed the answer."),
        ],
    )

    await adhoc_document_agent.run_agent("email me the answer", {"a.pdf": "text"}, {})

    assert sent_subjects == ["Your answer from HR Benefits Chat"]


async def test_tabular_format_instruction_is_added_for_a_summarize_style_question(monkeypatch):
    """Phase 141 - reuses response_format.py's shared keyword check (Phase
    122), same one genai-rag/single-agentic-rag/multi-agentic-rag already
    use - not a new convention for this pipeline."""
    captured_messages = []

    class CapturingLlm:
        model_name = "gpt-4.1-mini-fake"

        async def ainvoke(self, messages):
            captured_messages.extend(messages)
            return FakeResponse(content="done")

    monkeypatch.setattr(adhoc_document_agent, "_build_llm", lambda: CapturingLlm())

    await adhoc_document_agent.run_agent("Summarize this in a table", {"a.pdf": "text"}, {})

    system_prompt = captured_messages[0].content
    assert "markdown table" in system_prompt


async def test_tabular_format_instruction_is_not_added_for_an_ordinary_question(monkeypatch):
    captured_messages = []

    class CapturingLlm:
        model_name = "gpt-4.1-mini-fake"

        async def ainvoke(self, messages):
            captured_messages.extend(messages)
            return FakeResponse(content="done")

    monkeypatch.setattr(adhoc_document_agent, "_build_llm", lambda: CapturingLlm())

    await adhoc_document_agent.run_agent("What is the leave policy?", {"a.pdf": "text"}, {})

    system_prompt = captured_messages[0].content
    assert "markdown table" not in system_prompt


async def test_send_email_tool_sends_the_output_guardrail_checked_text_not_the_raw_text(monkeypatch):
    sent_bodies = []

    def _capturing_send_email(recipient, subject, body, attachments=None, html_body=None):
        sent_bodies.append(body)
        return {"sent": True, "message": f"Email sent to {recipient}."}

    async def _masking_check_output(query, answer):
        return answer.replace("555-12-3456", "<SSN>")

    monkeypatch.setattr(adhoc_document_agent, "send_email", _capturing_send_email)
    monkeypatch.setattr(adhoc_document_agent, "check_output", _masking_check_output)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {"recipient_email": "someone@example.com", "answer": "SSN on file: 555-12-3456"},
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - I've emailed the answer."),
        ],
    )

    result = await adhoc_document_agent.run_agent("email me the answer", {"a.pdf": "text"}, {})

    assert result["email_sent_to"] == "someone@example.com"
    assert sent_bodies == ["SSN on file: <SSN>"]


async def test_send_email_tool_failure_leaves_email_sent_to_none(monkeypatch):
    monkeypatch.setattr(
        adhoc_document_agent, "send_email", lambda recipient, subject, body, attachments=None, html_body=None: {"sent": False, "message": "sender not verified"}
    )
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {"recipient_email": "someone@example.com", "answer": "The answer."},
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="I couldn't send that email."),
        ],
    )

    result = await adhoc_document_agent.run_agent("email me the answer", {"a.pdf": "text"}, {})

    assert result["email_sent_to"] is None
    # Phase 161 - a failed attempt is still real evidence, not indistinguishable
    # from "no email asked for at all" (the gap this phase exists to close).
    evidence = dict(result["email_evidence"])
    evidence.pop("sent_at")
    assert evidence == {
        "recipient_email": "someone@example.com",
        "subject": "Your answer from HR Benefits Chat",
        "sent": False,
        "message": "sender not verified",
        "attached_files": [],
    }


async def test_no_email_requested_leaves_email_evidence_none(monkeypatch):
    _patch_llm(monkeypatch, [FakeResponse(content="Here's the summary.")])

    result = await adhoc_document_agent.run_agent("summarize this", {"a.pdf": "text"}, {})

    assert result["email_evidence"] is None


async def test_unknown_tool_name_does_not_crash_the_loop(monkeypatch):
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(tool_calls=[{"name": "SearchTheWeb", "args": {}, "id": "call-1"}]),
            FakeResponse(content="I can't do that."),
        ],
    )

    result = await adhoc_document_agent.run_agent("question", {"a.pdf": "text"}, {})

    assert result["answer"] == "I can't do that."


async def test_exhausting_max_iterations_returns_the_fallback_message(monkeypatch):
    responses = [
        FakeResponse(tool_calls=[{"name": "ReadDocument", "args": {"filename": "a.pdf"}, "id": f"call-{i}"}])
        for i in range(adhoc_document_agent.DEFAULT_MAX_ITERATIONS)
    ]
    _patch_llm(monkeypatch, responses)

    result = await adhoc_document_agent.run_agent("question", {"a.pdf": "text"}, {})

    assert "wasn't able to finish reasoning" in result["answer"]
    assert result["iterations"] == adhoc_document_agent.DEFAULT_MAX_ITERATIONS


async def test_search_web_tool_reuses_web_search_agent_and_tracks_the_query(monkeypatch):
    """Phase 145 - the new 3rd tool, reusing multi-agentic-rag's existing
    web_search_agent.py (the same Tavily integration, not a new one)."""
    captured_queries = []

    async def _fake_web_search(query):
        captured_queries.append(query)
        return f"Found: {query} is trending well in online reviews."

    monkeypatch.setattr(adhoc_document_agent.web_search_agent, "run", _fake_web_search)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[{"name": "SearchWeb", "args": {"query": "Acme Corp employee reviews"}, "id": "call-1"}]
            ),
            FakeResponse(content="Online reviews are generally positive."),
        ],
    )

    result = await adhoc_document_agent.run_agent("What do online reviews say about Acme Corp?", {"a.pdf": "text"}, {})

    assert captured_queries == ["Acme Corp employee reviews"]
    assert result["web_searches"] == ["Acme Corp employee reviews"]
    assert result["answer"] == "Online reviews are generally positive."


async def test_search_web_tool_failure_is_not_tracked_as_a_search_performed(monkeypatch):
    async def _fake_web_search_error(query):
        return "Error: web search failed (TAVILY_API_KEY not configured)."

    monkeypatch.setattr(adhoc_document_agent.web_search_agent, "run", _fake_web_search_error)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(tool_calls=[{"name": "SearchWeb", "args": {"query": "Acme Corp reviews"}, "id": "call-1"}]),
            FakeResponse(content="I couldn't search the web for that."),
        ],
    )

    result = await adhoc_document_agent.run_agent("What do online reviews say about Acme Corp?", {"a.pdf": "text"}, {})

    assert result["web_searches"] == []


# Phase 152 - attach_files threads the uploaded file(s)' raw bytes through
# to send_email()'s attachments argument.


async def test_attach_files_true_sends_every_uploaded_files_raw_bytes(monkeypatch):
    captured_attachments = []

    def _capturing_send_email(recipient, subject, body, attachments=None, html_body=None):
        captured_attachments.append(attachments)
        return {"sent": True, "message": f"Email sent to {recipient}."}

    monkeypatch.setattr(adhoc_document_agent, "send_email", _capturing_send_email)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {
                            "recipient_email": "someone@example.com",
                            "answer": "The answer.",
                            "attach_files": True,
                        },
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - I've emailed the answer with the file attached."),
        ],
    )

    result = await adhoc_document_agent.run_agent(
        "email me the answer with the file attached",
        {"a.pdf": "extracted text"},
        {"a.pdf": b"%PDF-1.4 raw bytes"},
    )

    assert captured_attachments == [[("a.pdf", b"%PDF-1.4 raw bytes")]]
    # Phase 161 - attached filenames surface as evidence too, not just raw bytes to SES.
    assert result["email_evidence"]["attached_files"] == ["a.pdf"]


async def test_attach_files_false_sends_no_attachments(monkeypatch):
    captured_attachments = []

    def _capturing_send_email(recipient, subject, body, attachments=None, html_body=None):
        captured_attachments.append(attachments)
        return {"sent": True, "message": f"Email sent to {recipient}."}

    monkeypatch.setattr(adhoc_document_agent, "send_email", _capturing_send_email)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {"recipient_email": "someone@example.com", "answer": "The answer."},
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - I've emailed the answer."),
        ],
    )

    await adhoc_document_agent.run_agent(
        "email me the answer", {"a.pdf": "extracted text"}, {"a.pdf": b"%PDF-1.4 raw bytes"}
    )

    assert captured_attachments == [None]


# Phase 157 - email_body_html is a separate, HTML-formatted version of the
# email, passed through to send_email()'s html_body argument and masked by
# check_output() same as the plain answer.


async def test_email_body_html_is_passed_through_to_send_email(monkeypatch):
    captured_html = []

    def _capturing_send_email(recipient, subject, body, attachments=None, html_body=None):
        captured_html.append(html_body)
        return {"sent": True, "message": f"Email sent to {recipient}."}

    monkeypatch.setattr(adhoc_document_agent, "send_email", _capturing_send_email)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {
                            "recipient_email": "someone@example.com",
                            "answer": "The answer.",
                            "email_body_html": "<p>Hi there,</p><table><tr><th>A</th></tr></table>",
                        },
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - I've emailed the answer."),
        ],
    )

    await adhoc_document_agent.run_agent("email me the answer", {"a.pdf": "text"}, {})

    assert captured_html == ["<p>Hi there,</p><table><tr><th>A</th></tr></table>"]


async def test_email_body_html_is_masked_by_the_output_guardrail(monkeypatch):
    captured_html = []

    def _capturing_send_email(recipient, subject, body, attachments=None, html_body=None):
        captured_html.append(html_body)
        return {"sent": True, "message": f"Email sent to {recipient}."}

    async def _masking_check_output(query, answer):
        return answer.replace("555-12-3456", "<SSN>")

    monkeypatch.setattr(adhoc_document_agent, "send_email", _capturing_send_email)
    monkeypatch.setattr(adhoc_document_agent, "check_output", _masking_check_output)
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {
                            "recipient_email": "someone@example.com",
                            "answer": "SSN on file: 555-12-3456",
                            "email_body_html": "<p>SSN on file: 555-12-3456</p>",
                        },
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - I've emailed the answer."),
        ],
    )

    await adhoc_document_agent.run_agent("email me the answer", {"a.pdf": "text"}, {})

    assert captured_html == ["<p>SSN on file: <SSN></p>"]


# Phase 157 - a tool-calling turn's real content gets lost once the loop
# moves on to a shorter follow-up turn (OpenAI allows a response to have
# both real content and tool_calls together) - the final chat answer must
# still be the full content, not the shorter remark that follows it.


async def test_chat_answer_is_the_full_emailed_answer_not_a_short_follow_up_remark(monkeypatch):
    monkeypatch.setattr(
        adhoc_document_agent, "send_email", lambda recipient, subject, body, attachments=None, html_body=None: {
            "sent": True,
            "message": f"Email sent to {recipient}.",
        },
    )
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                content="Here is the full tabular summary with every detail...",
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {
                            "recipient_email": "someone@example.com",
                            "answer": "Here is the full tabular summary with every detail...",
                            "email_body_html": "<table></table>",
                        },
                        "id": "call-1",
                    }
                ],
            ),
            FakeResponse(content="Done - I've emailed it to you. Let me know if you need anything else!"),
        ],
    )

    result = await adhoc_document_agent.run_agent("summarize and email it", {"a.pdf": "text"}, {})

    assert result["answer"] == "Here is the full tabular summary with every detail..."


# Phase 163 - chat_history threading. The key requirement: SendEmailWithAnswer
# must keep firing on a single-turn "summarize and email it" request whether
# chat_history is None, [], or populated - these tests check all three, not
# just that chat_history gets threaded into messages.


async def test_chat_history_is_threaded_into_messages_between_system_prompt_and_question(monkeypatch):
    captured_messages = []

    class _CapturingLlm:
        def __init__(self, response):
            self._response = response

        async def ainvoke(self, messages):
            captured_messages.append(messages)
            return self._response

    monkeypatch.setattr(adhoc_document_agent, "_build_llm", lambda: _CapturingLlm(FakeResponse(content="Here's the answer.")))

    history = [HumanMessage(content="What's the salary?"), AIMessage(content="$145,000 per year.")]
    await adhoc_document_agent.run_agent("And the start date?", {"a.pdf": "text"}, {}, chat_history=history)

    messages = captured_messages[0]
    assert isinstance(messages[0], SystemMessage)
    assert messages[1] is history[0]
    assert messages[2] is history[1]
    assert messages[3].content == "And the start date?"


async def test_send_email_tool_still_fires_with_no_chat_history_at_all(monkeypatch):
    """The user's own explicit requirement: a single-turn "summarize and
    email it" request must trigger SendEmailWithAnswer regardless of
    whether memory/history exists - this is the chat_history=None case,
    the most common one (a brand new session, no memory loaded yet)."""
    monkeypatch.setattr(
        adhoc_document_agent, "send_email", lambda recipient, subject, body, attachments=None, html_body=None: {"sent": True, "message": f"Email sent to {recipient}."}
    )
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {"recipient_email": "someone@example.com", "answer": "The summary.", "email_body_html": "<p>x</p>"},
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - emailed it."),
        ],
    )

    result = await adhoc_document_agent.run_agent(
        "Summarize this offer and email it to someone@example.com", {"a.pdf": "text"}, {}, chat_history=None
    )

    assert result["email_sent_to"] == "someone@example.com"
    assert result["email_evidence"]["sent"] is True


async def test_send_email_tool_still_fires_with_real_chat_history_present(monkeypatch):
    """Same requirement, the other direction: a populated chat_history must
    not suppress or interfere with the model's own SendEmailWithAnswer
    decision - memory is additive context, not a gate on this tool."""
    monkeypatch.setattr(
        adhoc_document_agent, "send_email", lambda recipient, subject, body, attachments=None, html_body=None: {"sent": True, "message": f"Email sent to {recipient}."}
    )
    _patch_llm(
        monkeypatch,
        [
            FakeResponse(
                tool_calls=[
                    {
                        "name": "SendEmailWithAnswer",
                        "args": {"recipient_email": "someone@example.com", "answer": "The summary.", "email_body_html": "<p>x</p>"},
                        "id": "call-1",
                    }
                ]
            ),
            FakeResponse(content="Done - emailed it."),
        ],
    )

    history = [HumanMessage(content="What's in this offer?"), AIMessage(content="A job offer from Accenture.")]
    result = await adhoc_document_agent.run_agent(
        "Now summarize it and email it to someone@example.com", {"a.pdf": "text"}, {}, chat_history=history
    )

    assert result["email_sent_to"] == "someone@example.com"
    assert result["email_evidence"]["sent"] is True


async def test_system_prompt_tells_the_model_not_to_resend_from_history_and_how_to_use_the_outcome_note(monkeypatch):
    """Regression test for a real bug a live 2-turn test caught before this
    shipped: a prior turn's own "...also send email..." phrasing, once
    sitting in chat_history, made the model re-attempt a send on a later,
    unrelated follow-up turn (even to the literal text of a placeholder
    from the original question) - and separately, a later "did you send
    it?" turn had no way to know an earlier email actually succeeded, so
    the model said "I have not sent any email yet" even when it had. Both
    fixes are prompt wording, which a fake-LLM unit test can only confirm
    was actually sent, not that a real model complies with it - that part
    was verified live (RAG-ROADMAP.md Phase 163), not asserted here."""
    captured_messages = []

    class _CapturingLlm:
        def __init__(self, response):
            self._response = response

        async def ainvoke(self, messages):
            captured_messages.append(messages)
            return self._response

    monkeypatch.setattr(adhoc_document_agent, "_build_llm", lambda: _CapturingLlm(FakeResponse(content="Yes, I sent it.")))

    history = [
        HumanMessage(content="Summarize this offer. also send email with the details to given id"),
        AIMessage(content="Here is the summary... [System note: an email was successfully sent to someone@example.com this turn.]"),
    ]
    await adhoc_document_agent.run_agent(
        "did you send the email, and what was the base salary?", {"a.pdf": "text"}, {}, chat_history=history
    )

    system_prompt = captured_messages[0][0].content
    assert "already handled" in system_prompt
    assert "must not be repeated now" in system_prompt
    assert "System note" in system_prompt
    assert "never quote the bracketed note itself verbatim" in system_prompt
