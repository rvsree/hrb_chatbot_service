# Checks all backend services are wired up and working correctly?

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway
from src.hrb_chatbot.common.config.settings import SETTINGS_TAKEN_FROM_ENV_FILE
from src.hrb_chatbot.common.enums import LlmProvider, MetadataStore, VectorDB

# TODO(next feature - tools): add a "tools" check here once a tool/schema

def check_vector_database(provider: str = VectorDB.CHROMADB) -> dict:
    # Check the vector store the RAG pipeline reads and writes chunks in.
    gateway = get_db_gateway()

    try:
        if provider == VectorDB.PINECONE:
            client = gateway.pinecone()
        else:
            client = gateway.chroma()

        return client.health_check()
    except Exception as error:
        return {"status": "unhealthy", "provider": provider, "message": str(error)}


def check_metadata_database(provider: str = MetadataStore.SQLITE) -> dict:
    # Check the store holding one row per uploaded document.
    gateway = get_db_gateway()

    try:
        if provider == MetadataStore.POSTGRES:
            client = gateway.postgres()
        else:
            client = gateway.sqlite()

        return client.health_check()
    except Exception as error:
        return {"status": "unhealthy", "provider": provider, "message": str(error)}


def check_llm(provider: str = LlmProvider.OPENAI) -> dict:
    """Check the chat client the agent will use - makes one real, free call."""
    gateway = get_client_gateway()

    try:
        if provider == LlmProvider.ANTHROPIC:
            client = gateway.anthropic_chat()
        elif provider == LlmProvider.OPENROUTER:
            client = gateway.openrouter_chat()
        elif provider == LlmProvider.BEDROCK:
            client = gateway.bedrock_chat()
        else:
            client = gateway.openai_chat()

        return client.health_check()
    except Exception as error:
        return {"status": "unhealthy", "provider": provider, "message": str(error)}


def is_working(check_result: dict) -> bool:
    """Return True if one check result means that part is usable."""
    return check_result.get("status") == "healthy"


def check_all_backend_services(
    provider: str = LlmProvider.OPENAI,
    metadata_provider: str = MetadataStore.SQLITE,
    vector_provider: str = VectorDB.CHROMADB,
) -> dict:

    checks = {
        "llm": check_llm(provider=provider),
        "vector_database": check_vector_database(provider=vector_provider),
        "metadata_database": check_metadata_database(provider=metadata_provider),
        # TODO(next feature - tools): "tools": check_tools()
    }

    all_backend_services_health = True
    for result in checks.values():
        if not is_working(result):
            all_backend_services_health = False
            break

    if all_backend_services_health:
        overall_status = "healthy"
    else:
        overall_status = "unhealthy"

    # Phase 128 - a static config value, not a live call like the 3 checks above.
    embedding_model = get_client_gateway().openai_embedding().get_configuration()["model"]

    return {
        "status": overall_status,
        "app": "HRB Chatbot",
        "settings_taken_from_env_file": SETTINGS_TAKEN_FROM_ENV_FILE,
        "embedding_model": embedding_model,
        "checks": checks,
    }
