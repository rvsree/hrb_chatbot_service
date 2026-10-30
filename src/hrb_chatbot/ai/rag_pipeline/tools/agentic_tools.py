"""The 3 tools single-agentic-rag's agent can call - each wraps something
that already exists, never raises. Phase 115: every tool now returns
(text, chunks) - text for the LLM to read, chunks (RetrievedChunk-shaped
dicts, [] for the two non-retrieval tools) for the real citations list -
not a side-channel, a uniform contract across all three."""

from langsmith import traceable

from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.retriever import retrieve_chunks
from src.hrb_chatbot.ai.rag_pipeline.tools.mcp_tools import get_leave_balance, get_leave_history
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_pipeline.tools.agentic_tools")


async def search_knowledge_base(
    query: str, search_strategy: str | None = None, role: str | None = None, department: str | None = None
) -> tuple[str, list[dict]]:
    """The RAG tool - primary for "how do I"/policy questions; search_strategy
    lets the agent pick "mmr". role/department (Phase 231, Document ACL) are
    the caller's own enforced identity - never exposed in
    AGENTIC_TOOL_DEFINITIONS's tool schema, so the agent's own LLM can
    never choose or override them, unlike search_strategy."""
    if not query or not query.strip():
        return "Error: please provide a question to search for.", []

    resolved_strategy = search_strategy if search_strategy in ("similarity", "mmr") else "similarity"

    try:
        chunks, _ = await retrieve_chunks(
            query, top_k=3, search_strategy=resolved_strategy, role=role, department=department
        )
    except Exception as error:
        logger.warning("search_knowledge_base failed for %r: %s", query, error)
        return f"Error: knowledge base search failed ({error}).", []

    if not chunks:
        return "No relevant knowledge base documents found.", []

    output = "Found relevant knowledge base content:\n\n"
    for i, chunk in enumerate(chunks, 1):
        output += f"--- Source {i} ({chunk['filename']}) ---\n{chunk['text']}\n\n"
    return output, chunks


@traceable(name="get_leave_balance_tool")
async def get_leave_balance_tool(employee_id: str) -> tuple[str, list[dict]]:
    """Wraps Phase 49's real MCP call - same live, OAuth2-secured call.
    Phase 269 - @traceable: the real MCP call this makes is plain httpx,
    not LangChain-native, so without this it was invisible as its own
    span in LangSmith - only the calling agent's own opaque node timing
    showed, with no visibility into the real tool call/its real input-output."""
    if not employee_id or not employee_id.strip():
        return "Error: please provide an employee ID.", []

    try:
        result = await get_leave_balance(employee_id.strip())
    except Exception as error:
        # exc_info=True (not plain %s) because anyio TaskGroup failures
        # arrive as an ExceptionGroup whose str() is just "unhandled
        # errors in a TaskGroup (N sub-exception)" - the real cause only
        # shows up in the full traceback.
        logger.warning("get_leave_balance_tool failed for %r: %s", employee_id, error, exc_info=True)
        return f"Error: leave balance lookup failed ({error}).", []

    return "\n".join(result["content"]), []


@traceable(name="get_leave_history_tool")
async def get_leave_history_tool(employee_id: str) -> tuple[str, list[dict]]:
    """Wraps Phase 49's real MCP call - same live, OAuth2-secured call.
    Phase 269 - @traceable, same reasoning as get_leave_balance_tool above."""
    if not employee_id or not employee_id.strip():
        return "Error: please provide an employee ID.", []

    try:
        result = await get_leave_history(employee_id.strip())
    except Exception as error:
        logger.warning("get_leave_history_tool failed for %r: %s", employee_id, error, exc_info=True)
        return f"Error: leave history lookup failed ({error}).", []

    return "\n".join(result["content"]), []


# Tool definitions the agent's LLM sees - clear, specific descriptions improve tool selection.
AGENTIC_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "SearchKnowledgeBase",
            "description": (
                "Search Amazing Bank HR benefits policy documents (401k, healthcare, tuition, leave policies). "
                "Use this for 'how do I' or 'what is the policy on' questions. "
                "This is the PRIMARY tool for policy/benefits questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {"type": "string", "description": "The question to search for."},
                    "search_strategy": {
                        "type": "string",
                        "enum": ["similarity", "mmr"],
                        "description": (
                            "Optional, defaults to 'similarity'. Use 'similarity' for a narrow, specific "
                            "question (e.g. 'how many weeks of parental leave'). Use 'mmr' for a broad "
                            "question that likely spans several different topics/documents "
                            "(e.g. 'what benefits programs are available') - it trades a little relevance "
                            "for more varied coverage."
                        ),
                    },
                },
                "required": ["input"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "GetLeaveBalance",
            "description": (
                "Get the caller's own current leave balance (PTO/sick days available). "
                "Use this for 'what's my balance' or 'how many days do I have left' questions. "
                "No input needed - always uses the caller's own employee_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {"input": {"type": "string", "description": "Not used - pass an empty string."}},
                "required": ["input"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "GetLeaveHistory",
            "description": (
                "Get the caller's own past leave requests. "
                "Use this for 'what leave have I taken' or 'show my leave history' questions. "
                "No input needed - always uses the caller's own employee_id."
            ),
            "parameters": {
                "type": "object",
                "properties": {"input": {"type": "string", "description": "Not used - pass an empty string."}},
                "required": ["input"],
            },
        },
    },
]
