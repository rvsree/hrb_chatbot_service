"""Phase 186 - employee-submitted questions: real-time LLM first-pass
answer, then human/Claude review before publishing."""

from pydantic import BaseModel

from src.hrb_chatbot.models.common import UserProfile


class FaqSubmitRequest(BaseModel):
    user_profile: UserProfile
    query: str


class FaqSubmissionRecord(BaseModel):
    id: int
    employee_id: str
    query: str
    external_llm_answer: str | None
    internal_review_status: str
    answer_restructuring_status: str
    final_answer: str | None
    published: bool
    reviewed_by: str | None
    created_at: str
    updated_at: str


class FaqSubmissionListResponse(BaseModel):
    count: int
    submissions: list[FaqSubmissionRecord]


class FaqRestructureRequest(BaseModel):
    user_profile: UserProfile


class FaqReviewRequest(BaseModel):
    user_profile: UserProfile
    internal_review_status: str
    final_answer: str | None = None
    published: bool = False


class PublishedFaq(BaseModel):
    id: int
    query: str
    final_answer: str | None


class PublishedFaqListResponse(BaseModel):
    count: int
    faqs: list[PublishedFaq]
