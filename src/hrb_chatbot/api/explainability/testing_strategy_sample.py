"""Phase 285 - public, non-admin sample endpoint for the Explainability
modal's Testing Strategy tab. The existing /v1/admin/golden-dataset,
/v1/admin/synthetic-dataset, and /v1/admin/live-queries routes (manage_admin.py)
are all Role.ADMIN-only and return every row - this is a new, separate,
narrower route: a fixed 10-row example slice, no role gating, no identity
params at all, visible to every role's own Explainability modal."""

from fastapi import APIRouter

from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.enums import TestingStrategyDataset
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.models.admin import GoldenDatasetCaseSummary, LiveQuerySummary, SyntheticDatasetCaseSummary
from src.hrb_chatbot.models.explainability import TestingStrategySampleResponse

logger = get_logger("explainability.testing_strategy_sample")

router_testing_strategy_sample = APIRouter(tags=["explainability"])

_SAMPLE_SIZE = 10


@router_testing_strategy_sample.get("/{dataset}/sample", response_model=TestingStrategySampleResponse)
async def get_testing_strategy_sample(dataset: TestingStrategyDataset):
    """dataset=golden|synthetic|live-queries (a 422 on anything else is
    FastAPI's own enum-path-param validation, no check needed here).
    total_count is the real full count; sample is always the first 10 rows."""
    gateway = get_db_gateway()

    try:
        if dataset == TestingStrategyDataset.GOLDEN:
            rows = await gateway.golden_dataset_store().list_cases()
            sample = [GoldenDatasetCaseSummary(**row) for row in rows[:_SAMPLE_SIZE]]
        elif dataset == TestingStrategyDataset.SYNTHETIC:
            rows = await gateway.synthetic_dataset_store().list_cases()
            sample = [SyntheticDatasetCaseSummary(**row) for row in rows[:_SAMPLE_SIZE]]
        else:
            rows = await gateway.live_query_store().list_queries()
            sample = [LiveQuerySummary(**row) for row in rows[:_SAMPLE_SIZE]]
    except Exception as error:
        logger.error("Loading testing-strategy sample for %s failed: %s: %s", dataset, type(error).__name__, error)
        return json_error(
            500, "Could not load sample data. Please try again.", code=error_codes.EXPLAINABILITY_SAMPLE_FAILED
        )

    return TestingStrategySampleResponse(dataset=dataset.value, total_count=len(rows), sample=sample)
