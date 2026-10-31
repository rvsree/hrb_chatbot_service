"""Phase 106 - lightweight login validation. Denies an employee_id/
full_name/role combo that isn't in the known-personas roster, instead of
accepting anything typed into the login form. Still not real
authentication - role stays self-asserted on every request after this,
unchanged from this project's documented RBAC-is-a-formality design."""

import asyncio

from fastapi import APIRouter, Request

from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.aws_client.apprunner_client import AppRunnerClient
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import get_app_environment, read_setting
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.known_personas import is_known_persona
from src.hrb_chatbot.common.rate_limiting import backend_activation_limiter
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.common.utils.request_ip import resolve_client_ip
from src.hrb_chatbot.models.auth import (
    BackendActivationStatusResponse,
    LoginRequest,
    LoginResponse,
    ResetSecretCodeRequest,
    ResetSecretCodeResponse,
)
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

# Milestone 3 - the recovery path out of a lockout, same "env var holding
# a known-safe temporary code" shape as the seed code above, never a
# plaintext literal in source. None (unset) disables recovery entirely -
# a locked admin then just waits out LOCKOUT_DURATION_MINUTES instead.
ADMIN_UNLOCK_CODE = read_setting(None, "ADMIN_UNLOCK_CODE", None)


@router_login.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request):
    await enforce_rate_limit(request)

    if not is_known_persona(payload.employee_id, payload.full_name, payload.role):
        return json_error(
            401,
            f"{payload.employee_id!r} isn't a known persona for this demo - check the id, name, and role.",
            code=error_codes.UNKNOWN_PERSONA,
        )

    must_reset_secret_code = False
    if payload.role in ("admin", "employee_admin"):
        credential_store = get_db_gateway().admin_credential_store()
        credential = await credential_store.get_or_seed(payload.employee_id, ADMIN_ONE_TIME_SEED_SECRET_CODE)

        if credential["is_locked"]:
            if ADMIN_UNLOCK_CODE and payload.secret_code == ADMIN_UNLOCK_CODE:
                await credential_store.force_unlock_and_require_reset(payload.employee_id, ADMIN_UNLOCK_CODE)
                must_reset_secret_code = True
            else:
                return json_error(
                    423,
                    f"Too many wrong secret codes - locked until {credential['locked_until'].isoformat()}.",
                    code=error_codes.ADMIN_ACCOUNT_LOCKED,
                )
        elif not await credential_store.verify_secret_code(payload.employee_id, payload.secret_code):
            if payload.count_as_attempt:
                await credential_store.record_failed_attempt(payload.employee_id)
                # Re-fetch rather than compute locally - the exact attempt
                # that crosses the threshold must report the lock
                # immediately, not leave the admin finding out only on
                # their next (also-rejected) try. The DB's own count/clock
                # stay the single source of truth, not a value guessed here.
                refreshed = await credential_store.get_credential(payload.employee_id)
                if refreshed["is_locked"]:
                    return json_error(
                        423,
                        f"Too many wrong secret codes - locked until {refreshed['locked_until'].isoformat()}.",
                        code=error_codes.ADMIN_ACCOUNT_LOCKED,
                    )
            return json_error(
                401,
                "Incorrect secret code for the admin role.",
                code=error_codes.INVALID_ADMIN_SECRET_CODE,
            )
        else:
            if payload.count_as_attempt:
                await credential_store.reset_failed_attempts(payload.employee_id)
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
    require_role(payload.user_profile, Role.ADMIN, Role.EMPLOYEE_ADMIN)

    credential_store = get_db_gateway().admin_credential_store()
    if not await credential_store.verify_secret_code(payload.user_profile.employee_id, payload.current_secret_code):
        return json_error(
            401,
            "Current secret code is incorrect.",
            code=error_codes.INVALID_ADMIN_SECRET_CODE,
        )

    await credential_store.set_secret_code(payload.user_profile.employee_id, payload.new_secret_code)
    return ResetSecretCodeResponse(employee_id=payload.user_profile.employee_id, reset=True)


@router_login.get("/backend-activation/status", response_model=BackendActivationStatusResponse)
async def backend_activation_status():
    """Phase 284 - public status check for a visitor hitting a paused AWS
    demo environment. No-op outside production - never touches AWS."""
    if get_app_environment() != "production":
        return BackendActivationStatusResponse(all_running=True, services=[])

    statuses = await asyncio.to_thread(AppRunnerClient().describe_all)
    all_running = all(service["status"] == "RUNNING" for service in statuses)
    return BackendActivationStatusResponse(all_running=all_running, services=statuses)


@router_login.post("/backend-activation/resume", response_model=BackendActivationStatusResponse)
async def backend_activation_resume(request: Request):
    """Phase 284 - public resume counterpart to the status check above.
    Skips the rate limiter entirely when nothing needs resuming."""
    if get_app_environment() != "production":
        return BackendActivationStatusResponse(all_running=True, services=[])

    statuses = await asyncio.to_thread(AppRunnerClient().describe_all)
    non_running_names = [service["service_name"] for service in statuses if service["status"] != "RUNNING"]
    if not non_running_names:
        return BackendActivationStatusResponse(all_running=True, services=statuses)

    under_cap = await backend_activation_limiter.check_and_record(resolve_client_ip(request))
    if not under_cap:
        return json_error(
            429,
            "Too many backend-activation attempts from this address today - try again tomorrow.",
            code=error_codes.BACKEND_ACTIVATION_RATE_LIMITED,
        )

    resumed = await asyncio.to_thread(AppRunnerClient().resume, non_running_names)
    all_running = all(service["status"] == "RUNNING" for service in resumed)
    return BackendActivationStatusResponse(all_running=all_running, services=resumed)
