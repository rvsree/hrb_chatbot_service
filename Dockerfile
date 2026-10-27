# The HRB chatbot, as a container image.
#
# Build it from the REPOSITORY ROOT, not from anywhere else:
#
#     docker build -t hrb-chatbot:local .
#
# The build context has to be the repository root, because that is where
# requirements.txt and src/ live.
#
# Two stages
# ----------
# The builder stage installs the dependencies; the runtime stage copies the
# finished virtual environment across and nothing else. The compilers and
# build headers some wheels need never reach the final image, which keeps it
# smaller and removes tooling an attacker could otherwise use.

# ---------------------------------------------------------------------------
# Stage 1 - build the virtual environment
# ---------------------------------------------------------------------------
# 3.12, not 3.13+: chromadb depends on Pydantic v1 internals that Python 3.13
# removed - see the workshop README this project's RAG approach is modeled on.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Requirements are copied on their own, before the source, so an ordinary code
# edit reuses Docker's cached install layer instead of reinstalling everything.
COPY requirements.txt ./
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt

# Presidio's analyzer (used by the "mask sensitive data" guardrail, Phase 7)
# needs this model at runtime - requirements.txt's own presidio-analyzer
# comment already named this, but the download step was never added here,
# so every query was blocked in production (Phase 82) until this line
# existed. Installs as a package into the venv, so the existing
# COPY --from=builder /opt/venv /opt/venv below picks it up automatically.
RUN /opt/venv/bin/python -m spacy download en_core_web_lg

# Build this project's own code into a wheel - the same role a JAR plays in
# a Java build - instead of copying loose source into the final image.
# --no-deps/--no-build-isolation: requirements.txt already installed every
# runtime dependency above; this step packages only src/, nothing else.
COPY pyproject.toml ./
COPY src ./src
RUN /opt/venv/bin/pip install setuptools>=68 wheel && \
    /opt/venv/bin/pip wheel . --no-deps --no-build-isolation -w /tmp/dist && \
    /opt/venv/bin/pip install --no-deps /tmp/dist/*.whl

# ---------------------------------------------------------------------------
# Stage 2 - the image that actually runs
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8093

# curl is for the HEALTHCHECK below - without it the health check can never
# pass. libmagic1 (for python-magic) was here but that dependency was
# removed 2026-10-07 - never actually imported anywhere in src/, uploads
# are validated by content-type string only (see requirements.txt).
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Run as a normal user. Nothing here needs root, and a container that starts
# as root stays root if somebody finds a way to execute code in it.
RUN useradd --create-home --uid 10001 hrbchat

COPY --from=builder /opt/venv /opt/venv

# No src/ copied here anymore - the builder stage already installed it as a
# real package (src.hrb_chatbot.*) into /opt/venv's site-packages, carried
# over by the COPY above, the same way a runtime image only needs the JAR,
# not the .java files that built it. No .env is copied in either: a
# container is configured through environment variables at run time (see
# README.md's Docker section), not a file baked into the image.
WORKDIR /srv

# ChromaDB's persistent store, the SQLite metadata file, and uploaded PDFs
# all write under data/ (relative to /srv). /srv itself is root-owned and
# not writable by hrbchat, so without this, the app fails at startup with a
# confusing "unable to open database file" / "could not connect to tenant" -
# it's actually a permission error, not a missing-database error.
RUN mkdir -p data && chown hrbchat:hrbchat data

USER hrbchat

EXPOSE 8093

# GET /ping only confirms the process is up - no provider is called, no
# tokens spent. A probe running every 30 seconds forever must never be able
# to cost money or fail because a backend (not this container) is down -
# that's what GET /health is for, checked deliberately by hand, not by this probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8093/ping || exit 1

# No --reload here - reload runs the app in a child process, which breaks
# both container signal handling and any attached debugger.
CMD ["uvicorn", "src.hrb_chatbot.main:app", "--host", "0.0.0.0", "--port", "8093"]
