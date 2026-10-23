"""Request/response contracts for the RAG query API - see docs/agent-reference/endpoint-request-response-contracts.md."""

from pydantic import BaseModel, ConfigDict, Field

from src.hrb_chatbot.common.enums import LlmProvider, SearchStrategy, VectorDB
from src.hrb_chatbot.models.common import ToolCallInfo, UserProfile


class SearchOptions(BaseModel):
    top_k: int | None = Field(
        None, ge=1, le=20, description="How many chunks to retrieve and consider - defaults to RAG_DEFAULT_TOP_K."
    )
    vector_db: VectorDB | None = Field(None, description="Override ACTIVE_VECTOR_DB for this call.")
    search_strategy: SearchStrategy | None = Field(
        None,
        description="Which retrieval technique to use - 'similarity' is the default when omitted. "
        "'mmr' trades some relevance for more diverse, less redundant results. 'keyword' is plain "
        "BM25 lexical ranking. 'hybrid' merges 'keyword' and 'similarity' via Reciprocal Rank Fusion. "
        "'dynamic' (Phase 252) picks one of the above automatically per query - the response's own "
        "retrieval.search_strategy field reports which one actually ran.",
    )
    lambda_mult: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="'mmr' only - 1.0 is pure relevance, 0.0 is pure diversity. Defaults to 0.5 when omitted.",
    )
    use_multi_query: bool = Field(
        False,
        description="Rewrite the question into several phrasings, search with each, and merge the "
        "results - catches relevant chunks a single phrasing misses.",
    )
    use_self_query: bool = Field(
        False,
        description="Let an LLM parse the question itself into a structured metadata filter "
        "(doc_category/department/doc_description) before searching.",
    )
    llm_provider: LlmProvider | None = Field(
        None,
        description="Which provider powers use_multi_query's rewriting and use_self_query's "
        "filter-parsing - 'openai' is the default when omitted.",
    )
    enable_corrective_retry: bool = Field(
        False,
        description="Phase 226 - when the retrieved chunks' own live precision falls below "
        "eval_options.eval_score_threshold, retrieve once more with a doubled top_k before generating "
        "an answer. No-op without eval_score_threshold set - there's no 'low' to detect against.",
    )


class GenerationOptions(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str | None = Field(
        None,
        max_length=100,
        description="Override the LLM model used to generate the answer, e.g. 'gpt-4.1-mini'.",
    )
    temperature: float | None = Field(
        None, ge=0.0, le=2.0, description="How much randomness the model uses - defaults to RAG_DEFAULT_TEMPERATURE."
    )
    max_tokens: int | None = Field(None, ge=1, description="Upper limit on the generated answer's token count.")


class EvalOptions(BaseModel):
    """Phase 215 - shared across all 3 query requests (genai-rag/single-agentic-rag/
    multi-agentic-rag), since eval/judge scoring is common to all 3 (Phase 109/110)."""

    model_config = ConfigDict(protected_namespaces=())

    judge_model: str | None = Field(
        None,
        max_length=100,
        description="Override the LLM model used for eval judging (groundedness/completeness/retrieval "
        "relevance), e.g. 'gpt-4.1-mini'. Defaults to the same model genai-rag generation uses when omitted.",
    )
    eval_score_threshold: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="If any live-computed eval score (groundedness/completeness/retrieval precision - "
        "whichever are present) falls below this, the response is flagged via "
        "EvalScores.below_threshold/below_threshold_metrics. No check when omitted.",
    )


class ClassificationOptions(BaseModel):
    """Phase 243 - classification-tier model overrides. Only one field applies per
    endpoint (decompose_model: genai-rag only, planner_model: multi-agentic-rag only) -
    not shared the way EvalOptions is, since each pipeline has its own single
    classification step, not a shared one."""

    model_config = ConfigDict(protected_namespaces=())

    decompose_model: str | None = Field(
        None,
        max_length=100,
        description="genai-rag only - override the model used for query decomposition (Phase 130). "
        "Defaults to OPENAI_DECOMPOSE_MODEL, then gpt-4.1-nano.",
    )
    planner_model: str | None = Field(
        None,
        max_length=100,
        description="multi-agentic-rag only - override the model used for the Planner Agent's routing "
        "step (Phase 65). Defaults to OPENAI_PLANNER_MODEL, then gpt-4.1-nano.",
    )


class RagQueryRequest(BaseModel):
    user_profile: UserProfile | None = None
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The question to ask the knowledge base.",
    )
    search_options: SearchOptions | None = None
    generation_options: GenerationOptions | None = None
    eval_options: EvalOptions | None = None
    classification_options: ClassificationOptions | None = None
    guardrails_model: str | None = Field(
        None,
        max_length=100,
        description="Phase 244 - override the model running NeMo Guardrails' input/output safety checks. "
        "Validated against GUARDRAILS_SUPPORTED_MODELS - 422 if given but not listed. Applies identically "
        "to all 3 query endpoints (top-level field, not nested, since guardrails run on every mode).",
    )
    enable_conversation_memory: bool = Field(
        False, description="Carry conversation history across calls, server-side, keyed by conversation_id."
    )
    conversation_id: str | None = Field(
        None,
        description="Pass back the value from a prior response to continue that conversation. Ignored if "
        "enable_conversation_memory is false; a new one is generated if true and this is omitted.",
    )


class RetrievedChunk(BaseModel):
    """One chunk the retrieval step considered relevant to the query."""

    document_id: str = Field(..., description="Which uploaded document this chunk came from.")
    filename: str = Field(..., description="That document's original filename.")
    chunk_index: int = Field(..., description="This chunk's position within that document.")
    text: str = Field(..., description="The chunk's text, as stored at index time.")
    score: float | None = Field(None, description="The vector store's own similarity score, null for MMR results.")
    matched_by: list[str] | None = Field(
        None,
        description="Phase 221 - hybrid search only: which underlying list(s) found this chunk - "
        "'sparse' (BM25 keyword), 'dense' (vector similarity), or both. Null for every other search_strategy.",
    )


class AnswerInfo(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    answer: str = Field(..., description="The generated, grounded answer.")
    model_used: str = Field(..., description="Which chat model actually generated this answer.")


class RetrievalInfo(BaseModel):
    vector_db: str = Field(..., description="Which vector store this query actually ran against.")
    search_strategy: str = Field(..., description="Which retrieval technique actually ran: 'similarity' or 'mmr'.")
    applied_filter: dict | None = Field(
        None, description="The metadata filter Self-Query actually parsed out of the question, if any."
    )
    acl_denied_count: int = Field(
        0,
        description="Phase 232 - how many documents Document ACL (Phase 231) excluded from this answer's "
        "candidate pool. 0 for the common case (no restricted documents, or the caller's role bypasses the gate).",
    )
    sources: list[RetrievedChunk] = Field(..., description="The chunks the answer was actually grounded in.")


class LatencyInfo(BaseModel):
    total: float = Field(..., description="Total wall-clock time for this call, in milliseconds.")
    retrieval: float | None = Field(None, description="Time spent retrieving chunks, in milliseconds. Null on a cache hit.")
    generation: float | None = Field(None, description="Time spent generating the answer, in milliseconds. Null on a cache hit.")
    eval: float | None = Field(None, description="Time spent on live eval-judge scoring, in milliseconds. Null when no eval ran this call (cache hit, MCP, or no context).")
    decomposition: float | None = Field(
        None, description="Phase 130 - genai-rag only; time spent splitting the question into sub-questions. Null elsewhere."
    )


class TokenUsageInfo(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class EvalScores(BaseModel):
    """Phase 109 - live LLM-as-judge scores, same prompts/parsing as the
    offline golden-dataset harness (golden_dataset_harness.py), run
    synchronously per live response at the user's explicit request
    (accepted tradeoff: 2 extra judge LLM calls per live - not cached -
    generation). 0.0-1.0, not 0-10 - already normalized by the judge."""

    groundedness: float = Field(..., description="Is the answer supported by the retrieved context? 0.0-1.0.")
    groundedness_verdict: str = Field(..., description="GROUNDED (>=0.7), PARTIAL (>=0.4), or HALLUCINATED.")
    groundedness_explanation: str | None = Field(None, description="Phase 202 - the judge LLM's raw 'Score: X / Reasoning: ...' response, verbatim.")
    groundedness_prompt: str | None = Field(None, description="Phase 212 - the exact prompt sent to the groundedness judge.")
    completeness: float = Field(..., description="Does the answer fully address the question? 0.0-1.0.")
    completeness_verdict: str = Field(..., description="COMPLETE (>=0.7), PARTIAL (>=0.4), or INCOMPLETE.")
    completeness_explanation: str | None = Field(None, description="Phase 202 - the judge LLM's raw 'Score: X / Reasoning: ...' response, verbatim.")
    completeness_prompt: str | None = Field(None, description="Phase 212 - the exact prompt sent to the completeness judge.")
    retrieval_precision: float | None = Field(
        None, description="Phase 208 - live, computed-this-call: (chunks an LLM judge found relevant) / (chunks retrieved)."
    )
    retrieval_relevant_chunk_indices: list[int] = Field(
        default_factory=list, description="Phase 208 - 1-indexed positions (within this call's retrieved chunks) the judge marked relevant."
    )
    retrieval_precision_explanation: str | None = Field(
        None, description="Phase 208 - the judge LLM's raw 'Relevant: ... / Reasoning: ...' response, verbatim."
    )
    retrieval_precision_prompt: str | None = Field(None, description="Phase 212 - the exact prompt sent to the retrieval-relevance judge.")
    retrieval_recall_estimate: float | None = Field(
        None,
        description="Phase 219 - NOT true recall (that needs the total count of relevant documents that exist, "
        "still unknowable for an arbitrary live question). (chunks judged relevant within what was actually "
        "retrieved) / (chunks judged relevant across a wider exact-KNN candidate pool - see retrieval_recall_pool_size). "
        "Null when nothing in that pool was judged relevant (undefined, not fabricated as 0 or 1).",
    )
    retrieval_f1_estimate: float | None = Field(
        None, description="Phase 219 - harmonic mean of retrieval_precision and retrieval_recall_estimate. Same estimate caveat as that field."
    )
    retrieval_recall_pool_size: int | None = Field(
        None, description="Phase 219 - how many candidate chunks retrieval_recall_estimate was computed against (capped at 20)."
    )
    retrieval_recall_relevant_count: int | None = Field(
        None,
        description="Phase 225 - the real denominator of retrieval_recall_estimate: how many chunks the judge "
        "marked relevant across the whole wider candidate pool (retrieval_recall_pool_size chunks), before "
        "scoping down to just the originally-retrieved subset (retrieval_relevant_chunk_indices).",
    )
    retrieval_retry_attempted: bool = Field(
        False,
        description="Phase 226 - true when search_options.enable_corrective_retry was on AND the first "
        "retrieval's own precision fell below eval_score_threshold, so retrieval ran a second time (doubled "
        "top_k) before this answer was generated. Always false when the feature was off, threshold wasn't "
        "set, or the first retrieval already passed.",
    )
    answer_relevancy: float | None = Field(
        None, description="Phase 250 - does the answer address what was actually asked (distinct from completeness's full-coverage check)? 0.0-1.0. Null unless EVAL_ANSWER_RELEVANCY_ENABLED=true (defaults false - a brand-new metric, opt-in not opt-out)."
    )
    answer_relevancy_verdict: str | None = Field(None, description="Phase 250 - RELEVANT (>=0.7), PARTIAL (>=0.4), or IRRELEVANT. Null when not run.")
    answer_relevancy_explanation: str | None = Field(None, description="Phase 250 - the judge's reasoning for the answer_relevancy score.")
    answer_relevancy_prompt: str | None = Field(None, description="Phase 250 - DeepEval's own verbose_logs for this judge call.")
    judge_model_used: str | None = Field(
        None, description="Phase 215 - the real model every judge call this turn actually used (the override if given, else the default) - verifiable, not just trusted."
    )
    below_threshold: bool = Field(
        False, description="Phase 215 - true if any live-computed score (groundedness/completeness/retrieval_precision, whichever are present) fell below the request's eval_options.eval_score_threshold. Always false when no threshold was given."
    )
    below_threshold_metrics: list[str] = Field(
        default_factory=list, description="Phase 215 - which metric name(s) triggered below_threshold, e.g. ['completeness']."
    )


class ChatHistoryMessage(BaseModel):
    role: str = Field(..., description="'human' or 'ai'.")
    content: str


class McpToolCallDetail(BaseModel):
    """Phase 132 - the raw MCP call, not just the summary ToolCallInfo already carries."""

    tool_name: str
    arguments: dict
    raw_result: list[str] = Field(..., description="The MCP tool's raw text blocks, before being joined into the answer.")


class LlmContextTurn(BaseModel):
    """Phase 132 - one real LLM call's actual rendered prompt, not a re-derived guess -
    captured from the exact same inputs the real chain.invoke() call used."""

    label: str = Field(..., description="e.g. 'answer' (single question) or the sub-question text (decomposed).")
    latency_ms: float | None = Field(None, description="Phase 205 - wall-clock time of this one real LLM call, not the whole request.")
    system_prompt: str | None = None
    human_message: str | None = None
    chat_history: list[ChatHistoryMessage] = Field(default_factory=list)
    response: str | None = Field(None, description="The raw answer text this turn's LLM call returned.")


class LlmContextInfo(BaseModel):
    """Phase 132 (genai-rag), extended Phase 160 to single/multi-agentic-rag -
    null only on a cache hit, when nothing was actually sent that call."""

    turns: list[LlmContextTurn] = Field(default_factory=list)
    mcp_tool_calls: list[McpToolCallDetail] = Field(default_factory=list)


class ActivatedRailInfo(BaseModel):
    """Phase 229 - one configured NeMo Guardrails flow that actually ran
    for this check, with NeMo's own real decision log - live-verified to
    include every configured rail, not just the one that blocked/modified
    something, so a clean pass is still demonstrable, not just asserted."""

    name: str = Field(..., description="Which configured flow ran, e.g. 'self check input', 'mask sensitive data on input'.")
    decisions: list[str] = Field(default_factory=list, description="NeMo's own real sequence of actions this rail took, e.g. ['execute self_check_input'].")
    stop: bool = Field(False, description="True if this rail halted further processing - this is what makes a check 'blocked'.")


class GuardrailCheckStatus(BaseModel):
    """Phase 224 - one guardrail check's real outcome. Before this, a
    MODIFIED (PII masked) result was indistinguishable from an untouched
    PASS to every caller, and a BLOCKED output silently swapped in a safe
    fallback answer with zero signal reaching anyone."""

    status: str = Field(..., description="'pass', 'modified' (NeMo masked something, e.g. PII), or 'blocked' (output check only - an input block raises a 422 before any response is built, so it never reaches here).")
    rail: str | None = Field(None, description="Which NeMo Guardrails rail fired. Null on a clean pass, and - confirmed against NeMo's own check_async() logic - also null on a 'modified' result (NeMo itself never attributes a MODIFIED outcome to one specific rail name); see activated_rails for the real per-rail detail.")
    activated_rails: list[ActivatedRailInfo] = Field(
        default_factory=list,
        description="Phase 229 - every configured rail that actually ran for this check, in order, with NeMo's own real decision log - not just the one rail that happened to matter.",
    )


class GuardrailInfo(BaseModel):
    """Phase 224 - both of NeMo Guardrails' checks for this answer."""

    input: GuardrailCheckStatus
    output: GuardrailCheckStatus


class ExplainabilityInfo(BaseModel):
    """Phase 107/109 - real latency/token/cache-vs-live/eval numbers,
    genai-rag only. Dollar cost is deliberately excluded (see BACKLOG.md)."""

    request_id: str = Field(..., description="Phase 201 - a UUID4 identifying this HTTP request/response pair, present on every call including cache hits. Correlates this response with backend logs, the request_metrics table, and (when LangSmith tracing is on) that call's trace metadata.")
    served_from_cache: bool = Field(..., description="True if this answer came from the answer cache, not a live retrieval+generation call.")
    llm_call_count: int = Field(..., description="How many LLM calls this request made - 0 on a cache hit or MCP fast-path, 1 otherwise. Excludes eval-judge calls.")
    latency_ms: LatencyInfo
    token_usage: TokenUsageInfo | None = Field(None, description="Null on a cache hit, MCP fast-path, or a no-context answer that never called the LLM.")
    llm_context: LlmContextInfo | None = Field(
        None, description="Phase 132 (genai-rag), extended Phase 160 to single/multi-agentic-rag; null only on a cache hit (nothing was actually sent this call)."
    )
    routed_to: str | None = Field(None, description="The MCP tool name if this answer was dynamically routed there instead of RAG (Phase 49/108). Null otherwise.")
    eval_scores: EvalScores | None = Field(None, description="Null for an MCP answer or a no-context answer (nothing to check groundedness against). Reused as-is on a cache hit - same answer, same score, not re-judged.")
    temperature: float | None = Field(
        None, description="Phase 127 - genai-rag only; null for single/multi-agentic-rag, which hardcode temperature=0, not user-configurable."
    )
    guardrails: GuardrailInfo = Field(..., description="Phase 224 - real input/output guardrail status for this answer. Reused as-is on a cache hit, same reasoning as eval_scores.")
    decompose_model_used: str | None = Field(
        None, description="Phase 243 - which model ran genai-rag's query decomposition (override if given, else the real default). Null for single-/multi-agentic-rag, or on a cache hit (that step didn't run)."
    )
    planner_model_used: str | None = Field(
        None, description="Phase 243 - which model ran multi-agentic-rag's Planner routing step (override if given, else the real default). Null for genai-rag/single-agentic-rag, or on a cache hit."
    )
    guardrails_model_used: str | None = Field(
        None, description="Phase 244 - which model ran the input/output guardrail checks (override if given, else the real default). Always present for a real call, unlike decompose_model_used/planner_model_used - guardrails run on every mode. Reused as-is on a cache hit, same reasoning as eval_scores."
    )


class RagQueryResponse(BaseModel):
    """What POST /query returns."""

    query: str = Field(..., description="The question that was asked.")
    answer_info: AnswerInfo
    retrieval_info: RetrievalInfo
    explainability_info: ExplainabilityInfo
    tools_used: list[ToolCallInfo] = Field(
        default_factory=list,
        description="Phase 126 - empty on a normal RAG answer, one entry when MCP-routed (explainability_info.routed_to).",
    )
    conversation_id: str | None = Field(
        None,
        description="Echoed/generated when enable_conversation_memory was true - pass it back on the next "
        "call to continue this conversation. Null when memory wasn't enabled.",
    )
