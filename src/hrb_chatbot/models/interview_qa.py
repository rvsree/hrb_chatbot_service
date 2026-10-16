"""Phase 187 - Interview Q&A as real, editable DB rows. The 7-part
answer structure (hint/concept/STAR/project-link/leadership/trade-offs/
keywords), plus tech_stack and feature_references for jumping to the
real implementing code."""

from pydantic import BaseModel

from src.hrb_chatbot.models.common import UserProfile


class KeywordEntry(BaseModel):
    term: str
    definition: str


class FeatureReference(BaseModel):
    label: str
    file_path: str


class InterviewQaCardFields(BaseModel):
    """Shared by create and update - every editable field."""

    topic: str
    topic_order: int = 0
    card_order: int = 0
    question: str
    hint: str | None = None
    concept: str | None = None
    situation: str | None = None
    task: str | None = None
    action: str | None = None
    result: str | None = None
    project_link: str | None = None
    leadership_angle: str | None = None
    trade_offs: list[str] = []
    keywords: list[KeywordEntry] = []
    tech_stack: list[str] = []
    feature_references: list[FeatureReference] = []


class InterviewQaCard(InterviewQaCardFields):
    id: int
    created_at: str
    updated_at: str


class InterviewQaListResponse(BaseModel):
    count: int
    cards: list[InterviewQaCard]


class CreateInterviewQaRequest(BaseModel):
    user_profile: UserProfile
    fields: InterviewQaCardFields


class UpdateInterviewQaRequest(BaseModel):
    user_profile: UserProfile
    fields: InterviewQaCardFields


class DeleteInterviewQaResponse(BaseModel):
    id: int
    deleted: bool
