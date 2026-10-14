"""Phase 106 - lightweight login validation. Denies an employee_id/
full_name/role combo that isn't in the known-personas roster, instead of
accepting anything typed into the login form. Still not real
authentication - role stays self-asserted on every request after this,
unchanged from this project's documented RBAC-is-a-formality design."""

from fastapi import APIRouter

from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.known_personas import is_known_persona
from src.hrb_chatbot.models.auth import LoginRequest, LoginResponse, ResetSecretCodeRequest, ResetSecretCodeResponse
from src.hrb_chatbot.models.common import UserProfile

router_login = APIRouter(tags=["auth"])

# Phase 180 (round 8) - moved out of a plaintext source literal into
# ADMIN_SEED_SECRET_CODE (.env, never committed). The original literal
# ("$reeRad") ended up copied into several committed docs before being
# caught and redacted there - having it live in source at all meant any
# redaction elsewhere was incomplete by construction. Only ever used the
# very first time admin_credentials has no row for an employee_id
# (AdminCredentialStore.get_or_seed() is idempotent past that point) - a
# login with this code always comes back with must_reset_secret_code=True,
# so a real admin always replaces it before this value matters again.
ADMIN_ONE_TIME_SEED_SECRET_CODE = read_setting(None, "ADMIN_SEED_SECRET_CODE", "change-me-on-first-login")


@router_login.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    if not is_known_persona(payload.employee_id, payload.full_name, payload.role):
        return json_error(
            401,
            f"{payload.employee_id!r} isn't a known persona for this demo - check the id, name, and role.",
            code=error_codes.UNKNOWN_PERSONA,
        )

    must_reset_secret_code = False
    if payload.role == "admin":
        credential_store = get_db_gateway().admin_credential_store()
        credential = await credential_store.get_or_seed(payload.employee_id, ADMIN_ONE_TIME_SEED_SECRET_CODE)
        if not await credential_store.verify_secret_code(payload.employee_id, payload.secret_code):
            return json_error(
                401,
                "Incorrect secret code for the admin role.",
                code=error_codes.INVALID_ADMIN_SECRET_CODE,
            )
        must_reset_secret_code = credential["must_reset"]

    return LoginResponse(
        user_profile=UserProfile(employee_id=payload.employee_id, full_name=payload.full_name, role=payload.role),
        must_reset_secret_code=must_reset_secret_code,
    )


@router_login.post("/admin/reset-secret-code", response_model=ResetSecretCodeResponse)
async def reset_admin_secret_code(payload: ResetSecretCodeRequest):
    """Phase 171 - only an already-authenticated admin can reach this (the
    caller must assert role=admin, same RBAC mechanism every other route
    uses), and must also prove they know the CURRENT code - a stolen
    session token alone can't silently change it."""
    require_role(payload.user_profile, Role.ADMIN)

    credential_store = get_db_gateway().admin_credential_store()
    if not await credential_store.verify_secret_code(payload.user_profile.employee_id, payload.current_secret_code):
        return json_error(
            401,
            "Current secret code is incorrect.",
            code=error_codes.INVALID_ADMIN_SECRET_CODE,
        )

    await credential_store.set_secret_code(payload.user_profile.employee_id, payload.new_secret_code)
    return ResetSecretCodeResponse(employee_id=payload.user_profile.employee_id, reset=True)
