"""Request/response contracts for login validation (Phase 106)."""

from pydantic import BaseModel, Field

from src.hrb_chatbot.models.common import UserProfile


class LoginRequest(BaseModel):
    employee_id: str = Field(..., max_length=50)
    full_name: str = Field(..., max_length=200)
    role: str = Field(..., max_length=50)
    # Phase 169 - only read/checked when role == "admin".
    secret_code: str | None = Field(default=None, max_length=50)
    # Milestone 3 - the login page's own speculative check (does the
    # typed secret code reveal the employee_id/full_name fields yet?)
    # calls this same endpoint on blur. That check must never count
    # toward the lockout - a real admin's own typos while still typing
    # their correct code would otherwise lock them out before they ever
    # click Sign In. True (the real submit flow) unless told otherwise.
    count_as_attempt: bool = Field(default=True)


class LoginResponse(BaseModel):
    user_profile: UserProfile
    # Phase 171 - true only for an admin whose code is still the one-time
    # seeded value, or hasn't been reset since an admin-initiated reset.
    must_reset_secret_code: bool = False


class ResetSecretCodeRequest(BaseModel):
    user_profile: UserProfile
    current_secret_code: str = Field(..., max_length=50)
    new_secret_code: str = Field(..., min_length=1, max_length=50)


class ResetSecretCodeResponse(BaseModel):
    employee_id: str
    reset: bool
