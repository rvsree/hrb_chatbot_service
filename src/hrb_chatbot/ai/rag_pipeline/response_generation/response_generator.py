"""Generates a grounded answer from retrieved chunks - a real LCEL chain, not a hand-rolled ask() call."""

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda

from src.hrb_chatbot.ai.pre_processing.context_builder import build_context_from_chunks
from src.hrb_chatbot.ai.rag_core.response_format import TABULAR_FORMAT_INSTRUCTION, should_use_tabular_format
from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway
from src.hrb_chatbot.common.clients.llm_client.langchain_chat_model import GatewayChatModel
from src.hrb_chatbot.common.enums import LlmProvider
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_pipeline.response_generator")

NO_CONTEXT_ANSWER = "I don't have any information about that in the knowledge base."

# Four few-shot examples, real KB text - see RAG-ROADMAP.md Phase 48 for why.
# No {{ }} below - plain str.format() would choke on literal braces.
SYSTEM_PROMPT_TEMPLATE = """You are the HR benefits assistant for JPMC employees. Use ONLY the context below to answer - if the answer isn't in it, say you don't know rather than guessing. Never invent information not present in the context. Always cite the source document by name after each fact.

Example 1 - direct fact lookup:
Context:
[JPMC Empower 401(k) Savings Plan.txt] Automatic enrollment at 5% contribution rate with annual auto-escalation up to 10%. Employer matching contributions of up to 5% (dollar-for-dollar) after one year of service. Immediate eligibility to participate with no waiting period.

Question: When can I start contributing to my 401(k), and does JPMC match?
Answer: You're eligible immediately, with no waiting period - you're auto-enrolled at a 5% contribution rate that auto-escalates to 10% over time. JPMorgan Chase matches up to 5% dollar-for-dollar, but only after one year of service [JPMC Empower 401(k) Savings Plan.txt].

Example 2 - eligibility/rule-based answer:
Context:
[JPMC Paid TimeOff.txt] To qualify for Parental Leave, employees must be actively employed on a U.S. payroll, regularly scheduled to work 20 or more hours per week, and have benefits-eligible status. New hires are eligible once they meet benefits eligibility.

Question: I just started - am I eligible for parental leave right away?
Answer: Only once you meet benefits-eligible status (regularly scheduled 20+ hours/week, not temporary/seasonal/contingent) - there's no separate waiting period beyond that [JPMC Paid TimeOff.txt].

Example 3 - tiered/multi-value answer:
Context:
[JPMC Guild Tuition Assistance.txt] 100% tuition coverage for select undergraduate and master's degree programs. Up to $7,500 annually for other graduate programs and certificates. Up to $5,250 annually for other undergraduate programs.

Question: How much tuition assistance do I get for a certificate program?
Answer: Up to $7,500 per year, unless it's one of the select degree programs covered at 100% - certificates fall under the graduate/certificate tier, not the fully-covered tier [JPMC Guild Tuition Assistance.txt].

Example 4 - refusal when the context doesn't cover it:
Context:
[JPMC Healthcare Benefits.txt] Medical plans: Aetna, Cigna Healthcare, UnitedHealthcare, Centivo. Dental plans: MetLife, Delta Dental. Vision plan: VSP.

Question: Does JPMC offer a monthly gym membership stipend?
Answer: I don't have that information in the available documents - the healthcare benefits context covers medical, dental, and vision plans, but says nothing about a gym stipend.

Now answer using only the context below:

Context:
{context}

{tabular_instruction}"""

RAG_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT_TEMPLATE),
        # Phase 58: prior conversation turns, if any - empty when
        # conversation memory isn't enabled, unchanged behavior then.
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{question}"),
    ]
)

# Phase 87: a separate, smaller prompt for the case retrieval found
# nothing but real conversation history exists - e.g. "what did I just
# ask you?". Deliberately NOT the same prompt as RAG_PROMPT above: that
# one's few-shot examples are all about citing fresh document context,
# which doesn't exist here. This one is scoped tightly to the prior
# conversation only, so it can't drift into inventing new HR facts.
CONVERSATIONAL_FALLBACK_PROMPT_TEMPLATE = """You are the HR benefits assistant for JPMC employees, continuing an existing conversation. No knowledge-base documents matched this specific question, so answer using ONLY the prior conversation below - summarize or refer back to what was already said. Never introduce a new HR policy fact that isn't already in the conversation history. If the prior conversation doesn't help either, say you don't have that information."""

CONVERSATIONAL_FALLBACK_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", CONVERSATIONAL_FALLBACK_PROMPT_TEMPLATE),
        MessagesPlaceholder("chat_history"),
        ("human", "{question}"),
    ]
)


def _to_result(message: AIMessage) -> dict:
    # GatewayChatModel sets response_metadata["model"]/["token_usage"] -
    # StrOutputParser() alone would discard both.
    return {
        "answer": message.content,
        "model_used": message.response_metadata.get("model", "unknown"),
        "token_usage": message.response_metadata.get("token_usage"),
    }


def _render_llm_context_turn(label: str, prompt_template: ChatPromptTemplate, inputs: dict) -> dict:
    """Phase 132 - renders the exact messages that will be sent to the LLM,
    from the same inputs the real chain.invoke() call uses right after this -
    a plain dict, same layering as the rest of this function's own return
    shape (Pydantic wrapping happens at the route layer, not here)."""
    messages = prompt_template.format_messages(**inputs)

    system_prompt = None
    chat_history = []
    human_message = None
    for index, message in enumerate(messages):
        is_last = index == len(messages) - 1
        if message.type == "system":
            system_prompt = message.content
        elif is_last:
            human_message = message.content
        else:
            chat_history.append({"role": message.type, "content": message.content})

    return {
        "label": label,
        "system_prompt": system_prompt,
        "human_message": human_message,
        "chat_history": chat_history,
        "response": None,  # filled in by the caller once the real LLM call returns
    }


def generate_answer(
    query: str,
    chunks: list[dict],
    model_name: str | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    chat_history: list[BaseMessage] | None = None,
) -> dict:
    """Returns {"answer": str, "model_used": str} - chat_history is empty/omitted when memory isn't enabled."""
    if not chunks:
        if chat_history:
            # Phase 87: retrieval found nothing, but there's real prior
            # conversation - a genuine follow-up/meta question (e.g. "what
            # did I just ask?"), not necessarily a dead end. Answer from
            # history alone instead of the free canned response.
            logger.info(
                "No chunks retrieved for %r but chat_history has %d turn(s) - answering from conversation memory only",
                query,
                len(chat_history),
            )
            llm = GatewayChatModel(
                provider=LlmProvider.OPENAI,
                temperature=temperature,
                model_name_override=model_name,
                max_tokens=max_tokens,
            )
            chain = CONVERSATIONAL_FALLBACK_PROMPT | llm | RunnableLambda(_to_result)
            fallback_inputs = {"question": query, "chat_history": chat_history}
            result = chain.invoke(fallback_inputs)
            logger.info("Generated a %d-character answer from conversation history only (0 chunks)", len(result["answer"]))
            llm_context_turn = _render_llm_context_turn("answer", CONVERSATIONAL_FALLBACK_PROMPT, fallback_inputs)
            llm_context_turn["response"] = result["answer"]
            result["llm_context_turn"] = llm_context_turn
            return result

        logger.info("No chunks retrieved for %r - returning the no-context answer, not calling the LLM", query)
        return {
            "answer": NO_CONTEXT_ANSWER,
            "model_used": model_name or get_client_gateway().openai_chat().model,
            "token_usage": None,
            "llm_context_turn": None,  # no LLM call happened - nothing was sent
        }

    llm = GatewayChatModel(
        provider=LlmProvider.OPENAI,
        temperature=temperature,
        model_name_override=model_name,
        max_tokens=max_tokens,
    )
    chain = RAG_PROMPT | llm | RunnableLambda(_to_result)

    context = build_context_from_chunks(chunks)
    tabular_instruction = TABULAR_FORMAT_INSTRUCTION if should_use_tabular_format(query) else ""
    rag_inputs = {"context": context, "question": query, "chat_history": chat_history or [], "tabular_instruction": tabular_instruction}
    result = chain.invoke(rag_inputs)

    logger.info("Generated a %d-character answer from %d chunk(s)", len(result["answer"]), len(chunks))
    llm_context_turn = _render_llm_context_turn("answer", RAG_PROMPT, rag_inputs)
    llm_context_turn["response"] = result["answer"]
    result["llm_context_turn"] = llm_context_turn
    return result
