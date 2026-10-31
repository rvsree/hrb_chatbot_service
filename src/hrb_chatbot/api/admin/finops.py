"""Phase 283 - FinOps Monitoring: real AWS Cost Explorer + LangSmith usage
data, plus honest static content for the 3 services (Pinecone/Upstash/
Neon) that have no usable cost/pause API. Role.ADMIN only (DevOps tier) -
same require_role()-inside-each-route pattern every other admin route in
manage_admin.py already uses, query-param identity on these 3 GET routes
(Phase 96 - a GET can't carry a body)."""

import asyncio

from fastapi import APIRouter, Depends

from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.finops_client.aws_cost_client import AwsCostClient
from src.hrb_chatbot.common.clients.finops_client.langsmith_usage_client import LangSmithUsageClient
from src.hrb_chatbot.common.enums import FinopsProvider, Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.models.admin import (
    FinopsCostSnapshot,
    FinopsHistoryResponse,
    FinopsOtherServiceInfo,
    FinopsOtherServicesResponse,
)
from src.hrb_chatbot.models.common import UserProfile

logger = get_logger("admin.finops")

router_finops = APIRouter(tags=["admin", "finops"])

_HISTORY_LIMIT = 30

# provider -> the live client call to make on a refresh. Both clients
# return the same error-as-data shape (status/message/period_start/
# period_end/total_cost/cost_breakdown) - see aws_cost_client.py/
# langsmith_usage_client.py.
_LIVE_FETCHERS = {
    FinopsProvider.AWS: lambda: AwsCostClient().get_current_month_cost(),
    FinopsProvider.LANGSMITH: lambda: LangSmithUsageClient().get_current_month_usage(),
}

# Phase 283 - static content, no live call. Researched directly (see
# RAG-ROADMAP.md's Phase 283 entry) rather than assumed: none of these 3
# has a cost API worth polling or a pause mechanism worth building.
_OTHER_SERVICES = [
    FinopsOtherServiceInfo(
        provider="pinecone",
        display_name="Pinecone (vector store)",
        billing_model="Serverless, pay-per-use (storage + read/write operations) - no fixed monthly fee on the serverless tier this project uses.",
        why_no_pause_needed=(
            "No cost or pause API exists. Moot anyway - this project's ~281-vector index is already "
            "near $0 idle; there is no meaningful ongoing cost to pause."
        ),
        pause_available=False,
    ),
    FinopsOtherServiceInfo(
        provider="upstash_redis",
        display_name="Upstash (Redis cache)",
        billing_model="Pay-as-you-go with a free tier - billed per request/storage, no fixed monthly fee.",
        why_no_pause_needed=(
            "No reliable official cost API, and no pause mechanism. Moot anyway - this project's cache "
            "usage stays well inside the free tier."
        ),
        pause_available=False,
    ),
    FinopsOtherServiceInfo(
        provider="neon",
        display_name="Neon (Postgres)",
        billing_model="Usage-based compute billing with autoscaling; a real cost API exists but needs a separate, not-yet-generated API key.",
        why_no_pause_needed=(
            "Moot regardless of the API key - Neon already auto-suspends (scale-to-zero) its compute "
            "when idle, so there is nothing left to manually pause."
        ),
        pause_available=False,
    ),
]


@router_finops.get("/{provider}/cost", response_model=FinopsCostSnapshot)
async def get_finops_cost(
    provider: FinopsProvider,
    force_refresh: bool = False,
    user_profile: UserProfile | None = Depends(identity_from_query_params),
):
    """Latest stored snapshot for this provider, or a fresh live fetch (and
    a new stored row) when force_refresh=true or none exists yet. Never a
    500 on a provider-side failure - {"error": ..., "code":
    "FINOPS_PROVIDER_UNAVAILABLE"} instead."""
    user = require_role(user_profile, Role.ADMIN)

    store = get_db_gateway().finops_snapshot_store()

    if not force_refresh:
        latest = await store.get_latest_snapshot(provider.value)
        if latest is not None:
            return FinopsCostSnapshot(**latest)

    result = await asyncio.to_thread(_LIVE_FETCHERS[provider])
    if result["status"] != "ok":
        logger.warning("FinOps provider %s unavailable: %s", provider.value, result["message"])
        return json_error(503, result["message"], code=error_codes.FINOPS_PROVIDER_UNAVAILABLE)

    snapshot = await store.insert_snapshot(
        provider=provider.value,
        period_start=result["period_start"],
        period_end=result["period_end"],
        total_cost=result["total_cost"],
        cost_breakdown=result["cost_breakdown"],
        created_by=user.employee_id,
    )
    return FinopsCostSnapshot(**snapshot)


@router_finops.get("/{provider}/history", response_model=FinopsHistoryResponse)
async def get_finops_history(
    provider: FinopsProvider, user_profile: UserProfile | None = Depends(identity_from_query_params)
):
    """Up to the last 30 stored snapshots for this provider, newest first."""
    require_role(user_profile, Role.ADMIN)

    rows = await get_db_gateway().finops_snapshot_store().list_history(provider.value, limit=_HISTORY_LIMIT)
    return FinopsHistoryResponse(count=len(rows), snapshots=[FinopsCostSnapshot(**row) for row in rows])


@router_finops.get("/other-services", response_model=FinopsOtherServicesResponse)
async def get_finops_other_services(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Static, no live call - why Pinecone/Upstash/Neon don't get a cost
    tab or a pause control."""
    require_role(user_profile, Role.ADMIN)

    return FinopsOtherServicesResponse(services=_OTHER_SERVICES)
