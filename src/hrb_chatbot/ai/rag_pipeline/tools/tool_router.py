"""Dynamic Tool Router (Phase 277) - validates a proposed tool call's
arguments against that tool's own JSON schema (AGENTIC_TOOL_DEFINITIONS,
the exact schema the LLM itself was given - not a second, duplicate
definition that could drift from it) BEFORE the tool function ever runs.
Today's orchestration_agent.py loop called every tool unconditionally,
tolerating a missing/malformed argument silently via dict.get() defaults -
this catches it explicitly and turns it into a structured, retry-worthy
error message instead, closing the loop back into the agent's own ReAct
loop (see run_agent()'s own self-correction comment)."""

from src.hrb_chatbot.ai.rag_pipeline.tools.agentic_tools import AGENTIC_TOOL_DEFINITIONS

_SCHEMAS_BY_TOOL_NAME = {
    definition["function"]["name"]: definition["function"]["parameters"] for definition in AGENTIC_TOOL_DEFINITIONS
}


def validate_tool_call(tool_name: str, tool_args: dict) -> str | None:
    """Returns a human-readable validation error, or None if tool_args
    satisfies that tool's own schema (required fields present, enum
    fields hold one of their allowed values). Only checks what the real
    schema actually declares - never invents a stricter rule the tool
    definition itself doesn't have."""
    schema = _SCHEMAS_BY_TOOL_NAME.get(tool_name)
    if schema is None:
        return f"unknown tool {tool_name!r}"

    if not isinstance(tool_args, dict):
        return f"arguments must be a JSON object, got {type(tool_args).__name__}"

    properties = schema.get("properties", {})
    for required_field in schema.get("required", []):
        if required_field not in tool_args or tool_args[required_field] in (None, ""):
            return f"missing required field {required_field!r}"

    for field_name, value in tool_args.items():
        field_schema = properties.get(field_name)
        if field_schema is None:
            continue
        allowed_values = field_schema.get("enum")
        if allowed_values is not None and value not in allowed_values:
            return f"field {field_name!r} must be one of {allowed_values!r}, got {value!r}"

    return None
