"""The real caller's IP, not a reverse proxy's - Phase 266."""

from fastapi import Request


def resolve_client_ip(request: Request) -> str | None:
    """Behind AWS App Runner (production) or any other reverse proxy,
    request.client.host is the proxy's own address, not the real visitor's;
    X-Forwarded-For's first entry is the original client. Falls back to
    request.client.host unchanged (today's exact behavior) when the header
    is absent - a plain local dev request (no proxy in front) still
    resolves to 127.0.0.1."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_entry = forwarded_for.split(",")[0].strip()
        if first_entry:
            return first_entry
    return request.client.host if request.client else None
