"""Phase 285 - request/response contracts for the public Testing Strategy
sample endpoint (Explainability modal, every role). Reuses the existing
GoldenDatasetCaseSummary/SyntheticDatasetCaseSummary/LiveQuerySummary
models from models/admin.py unchanged - this is a smaller, public view
over the same rows, not a new shape."""

from pydantic import BaseModel

from src.hrb_chatbot.models.admin import GoldenDatasetCaseSummary, LiveQuerySummary, SyntheticDatasetCaseSummary


class TestingStrategySampleResponse(BaseModel):
    """sample is capped at 10 rows; total_count is the real full count, so
    the frontend can say "showing 10 of N" without going stale."""

    dataset: str
    total_count: int
    sample: list[GoldenDatasetCaseSummary] | list[SyntheticDatasetCaseSummary] | list[LiveQuerySummary]
