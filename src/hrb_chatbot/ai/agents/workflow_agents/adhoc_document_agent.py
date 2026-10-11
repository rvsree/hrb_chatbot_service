"""Phase 136 - the Chat GenAI Workflow's own ReAct tool-calling loop.
Deliberately separate from orchestration_agent.py (single-agentic-rag):
originally scoped to exactly 2 tools, neither touching a vector store,
MCP, or the web - LLM calls and the attached files' own text only. Phase
145 added a 3rd tool, SearchWeb, reusing multi-agentic-rag's existing
web_search_agent.py (the same Tavily integration, not a new one) per
explicit user request - still no vector store or MCP access, by design.
See docs/dev-reference/genai_chat_workflow.md for the original design."""

import asyncio
import time
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.agents.domain_agents import web_search_agent
from src.hrb_chatbot.ai.rag_core.response_format import TABULAR_FORMAT_INSTRUCTION, should_use_tabular_format
from src.hrb_chatbot.ai.rag_pipeline.response_generation.guardrails_output import check_output
from src.hrb_chatbot.common.clients.email_client.ses_client import send_email
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("agents.adhoc_document_agent")

DEFAULT_MAX_ITERATIONS = 5

SYSTEM_PROMPT_TEMPLATE = """You are answering a question about documents the user just attached directly to this chat - not the HR knowledge base.

Attached files: {filenames}

Use the ReadDocument tool to read a file's content before answering - never
guess at what a file contains. Answer only from what you actually read in
the attached files; if the files don't contain the answer, say so plainly
rather than inventing one. If the question also asks about something
outside the attached files - current/public information, online reviews,
market comparisons, or anything the documents themselves wouldn't contain -
use the SearchWeb tool for that part, and say in your answer which parts
came from the attached file(s) versus the web. If the user asked you to
email the answer to someone, call SendEmailWithAnswer after you've written
your final answer, with that answer as the plain-text "answer" argument
and a short, specific subject line that reflects what the email is
actually about (not a generic "Your answer" - name the real topic, e.g.
"Your 401(k) employer match summary"). Also write email_body_html: a
complete, professional HTML email - start with one brief greeting/intro
sentence (e.g. "Here's the summary you asked for:"), then the content.
Any tabular data in email_body_html must be a real HTML <table>, never
markdown pipe syntax - give header cells (<th>) an inline
style="background-color:#2f6f4f;color:#ffffff;font-weight:bold" and give
every <td>/<th> a visible border (e.g.
style="border:1px solid #ccc;padding:6px"), since an email client won't
load an external stylesheet. email_body_html is a separate, differently-
formatted version of the same content for the email - it is not shown in
the chat, so keep your plain-text "answer" as you'd normally write it. If
the user also asked to attach, include, or send the actual file(s) (not
just a summary of them), set attach_files to true - the original
uploaded file(s) will be attached to the email exactly as uploaded."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "ReadDocument",
            "description": "Read one attached file's extracted text content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Exact filename of the attached file to read."},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "SearchWeb",
            "description": "Search the public web for current/external information the attached files wouldn't contain - e.g. recent news, public reviews, or market comparisons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The web search query."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "SendEmailWithAnswer",
            "description": "Email the final answer to someone - only call this if the user explicitly asked for the answer to be emailed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_email": {"type": "string", "description": "The email address to send the answer to."},
                    "subject": {
                        "type": "string",
                        "description": "A short, specific email subject naming the real topic - not a generic placeholder.",
                    },
                    "answer": {"type": "string", "description": "The final answer text, plain - same as you'd normally write in chat."},
                    "email_body_html": {
                        "type": "string",
                        "description": "A complete, professional HTML email: brief greeting/intro, then the content. Any table must be real HTML <table> markup with a styled, bordered header row - never markdown pipe syntax.",
                    },
                    "attach_files": {
                        "type": "boolean",
                        "description": "True if the user asked for the actual uploaded file(s) attached, not just a text summary.",
                    },
                },
                "required": ["recipient_email", "subject", "answer", "email_body_html"],
            },
        },
    },
]


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


def _build_llm():
    return build_agent_llm().bind(tools=TOOL_DEFINITIONS)


async def run_agent(question: str, file_texts: dict[str, str], file_bytes: dict[str, bytes]) -> dict:
    """file_texts: {filename: extracted_text}, file_bytes: {filename: raw
    uploaded bytes} - the same files, kept in two forms since ReadDocument
    needs text and SendEmailWithAnswer's attach_files (Phase 152) needs the
    original bytes to attach exactly as uploaded. Returns
    {answer, files_used, web_searches, email_sent_to, email_evidence,
    model_used, iterations, llm_call_count, token_usage, latency_ms}.
    email_evidence (Phase 161) is set whenever SendEmailWithAnswer was
    called, sent or failed - None only if it was never called at all.
    Still never
    touches a vector store or MCP - ReadDocument only ever reads from
    file_texts, nothing else exists for it to call. SearchWeb (Phase 145)
    is the one deliberate exception to "no external access", reusing
    multi-agentic-rag's existing Tavily integration."""
    started_at = time.perf_counter()
    llm = _build_llm()

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(filenames=", ".join(file_texts.keys()))
    # Phase 141: same shared keyword check genai-rag/single-agentic-rag/
    # multi-agentic-rag's Reviewer Agent already use (response_format.py,
    # Phase 122) - not a new convention invented for this pipeline, so a
    # "summarize this as a table" question gets the same markdown-table
    # treatment here as everywhere else, in the chat answer. Phase 157: the
    # emailed copy is now a separately-written HTML version
    # (email_body_html), not a reuse of this plain answer text.
    if should_use_tabular_format(question):
        system_prompt = f"{system_prompt}\n\n{TABULAR_FORMAT_INSTRUCTION}"
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=question)]

    files_used: list[str] = []
    web_searches: list[str] = []
    email_sent_to: str | None = None
    # Phase 161 - real evidence of the SendEmailWithAnswer attempt, sent or
    # failed, for the Explainability view - None only if the tool was never called.
    email_evidence: dict | None = None
    # Phase 157: a response that both writes real content AND calls a tool
    # (OpenAI allows both on one turn) only has that content appended to
    # message history here, not returned - only the *next* turn's response
    # becomes the final answer, and that next turn is often just a short
    # wrap-up ("I've emailed it") once the model already said the real
    # content a turn earlier. SendEmailWithAnswer's own "answer" argument is
    # already explicitly "the final answer" per the system prompt, so it's
    # reused as the chat answer too when set, instead of trusting whatever
    # short remark follows - fixes the chat window going blank after a
    # query that also sends an email.
    last_emailed_answer_text: str | None = None
    total_prompt_tokens = 0
    total_completion_tokens = 0
    llm_call_count = 0

    def _token_usage() -> dict | None:
        if llm_call_count == 0:
            return None
        return {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        }

    for i in range(DEFAULT_MAX_ITERATIONS):
        with log_backend_call(logger, "adhoc_document_agent", "ainvoke", iteration=i + 1):
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=AGENT_LLM_TIMEOUT_SECONDS)
        llm_call_count += 1

        if response.usage_metadata:
            total_prompt_tokens += response.usage_metadata["input_tokens"]
            total_completion_tokens += response.usage_metadata["output_tokens"]

        messages.append(response)

        if not response.tool_calls:
            return {
                "answer": last_emailed_answer_text if last_emailed_answer_text is not None else response.content,
                "files_used": files_used,
                "web_searches": web_searches,
                "email_sent_to": email_sent_to,
                "email_evidence": email_evidence,
                "model_used": getattr(llm, "model_name", None) or "unknown",
                "iterations": i + 1,
                "llm_call_count": llm_call_count,
                "token_usage": _token_usage(),
                "latency_ms": {"total": _elapsed_ms(started_at)},
            }

        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]

            if tool_name == "ReadDocument":
                filename = tool_args.get("filename", "")
                if filename in file_texts:
                    tool_output = file_texts[filename]
                    if filename not in files_used:
                        files_used.append(filename)
                else:
                    tool_output = f"Error: no attached file named {filename!r}. Attached files: {', '.join(file_texts.keys())}."
            elif tool_name == "SearchWeb":
                query = tool_args.get("query", "")
                # Phase 145: the exact same call web_search_agent.py (multi-
                # agentic-rag's domain agent) already makes - reusing that
                # Tavily integration, not building a second one.
                tool_output = await web_search_agent.run(query)
                if query and not tool_output.startswith("Error:"):
                    web_searches.append(query)
            elif tool_name == "SendEmailWithAnswer":
                recipient = tool_args.get("recipient_email", "")
                subject = tool_args.get("subject") or "Your answer from HR Benefits Chat"
                answer_text = tool_args.get("answer", "")
                html_body_text = tool_args.get("email_body_html", "")
                # Phase 138: the route's own check_output() only runs on the
                # final HTTP response, after run_agent() returns - too late
                # to stop this tool from already having emailed raw,
                # unmasked text. Run the same output rail here, before the
                # email actually goes out. Phase 157: email_body_html is a
                # second, separately-written piece of text the model
                # produces - masking must cover it too, not just the plain
                # "answer".
                safe_answer_text = await check_output(question, answer_text)
                safe_html_body = await check_output(question, html_body_text) if html_body_text else None
                last_emailed_answer_text = safe_answer_text
                # Phase 152: attach every uploaded file when asked, not just
                # the ones ReadDocument happened to be called on - "attach
                # the file(s)" means what was uploaded, not what was read.
                attachments = list(file_bytes.items()) if tool_args.get("attach_files") else None
                # Phase 161: captured right before the send, since the attempt
                # itself - not whatever time check_output()/send_email() take -
                # is what "when was this sent" should reflect.
                sent_at = datetime.now(UTC).isoformat()
                result = send_email(
                    recipient, subject, safe_answer_text, attachments=attachments, html_body=safe_html_body
                )
                tool_output = result["message"]
                if result["sent"]:
                    email_sent_to = recipient
                email_evidence = {
                    "recipient_email": recipient,
                    "subject": subject,
                    "sent": result["sent"],
                    "message": result["message"],
                    "attached_files": [filename for filename, _ in attachments] if attachments else [],
                    "sent_at": sent_at,
                }
            else:
                tool_output = f"Error: unknown tool {tool_name!r}"

            logger.info("Agent called tool=%s args=%r", tool_name, {k: v for k, v in tool_args.items() if k != "answer"})
            messages.append(ToolMessage(content=tool_output, tool_call_id=tool_call["id"]))

    return {
        "answer": "I wasn't able to finish reasoning about this within the allowed number of steps. Please rephrase or ask a more specific question.",
        "files_used": files_used,
        "web_searches": web_searches,
        "email_sent_to": email_sent_to,
        "email_evidence": email_evidence,
        "model_used": getattr(llm, "model_name", None) or "unknown",
        "iterations": DEFAULT_MAX_ITERATIONS,
        "llm_call_count": llm_call_count,
        "token_usage": _token_usage(),
        "latency_ms": {"total": _elapsed_ms(started_at)},
    }
