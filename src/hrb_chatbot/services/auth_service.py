"""Phase 292 - extracted out of api/auth/login.py's route handlers. The
route used to call get_db_gateway().admin_credential_store() directly and
implement the lockout/unlock/attempt-counting policy inline - no service
layer, unlike documents_service.py (the pattern CLAUDE.md names as the
right one: route orchestrates, service raises, route maps to HTTP)."""

from datetime import datetime

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway


class AdminAccountLockedError(Exception):
    """Too many wrong secret codes. locked_until is when retrying is allowed again."""

    def __init__(self, locked_until: datetime):
        self.locked_until = locked_until
        super().__init__(f"locked until {locked_until.isoformat()}")


class InvalidAdminSecretCodeError(Exception):
    """Secret code didn't match - either at login, or when resetting it."""


async def authenticate_admin(
    employee_id: str,
    secret_code: str | None,
    seed_secret_code: str,
    unlock_code: str | None,
    count_as_attempt: bool,
) -> bool:
    """Verifies an admin/employee_admin login. Returns must_reset_secret_code.
    Raises AdminAccountLockedError or InvalidAdminSecretCodeError for the
    route to map to the matching 423/401 response."""
    credential_store = get_db_gateway().admin_credential_store()
    credential = await credential_store.get_or_seed(employee_id, seed_secret_code)

    if credential["is_locked"]:
        if unlock_code and secret_code == unlock_code:
            await credential_store.force_unlock_and_require_reset(employee_id, unlock_code)
            return True
        raise AdminAccountLockedError(credential["locked_until"])

    if not await credential_store.verify_secret_code(employee_id, secret_code):
        if count_as_attempt:
            await credential_store.record_failed_attempt(employee_id)
            # Re-fetch rather than compute locally - the exact attempt that
            # crosses the threshold must report the lock immediately, not
            # leave the caller finding out only on their next (also-
            # rejected) try. The DB's own count/clock stay the single
            # source of truth, not a value guessed here.
            refreshed = await credential_store.get_credential(employee_id)
            if refreshed["is_locked"]:
                raise AdminAccountLockedError(refreshed["locked_until"])
        raise InvalidAdminSecretCodeError()

    if count_as_attempt:
        await credential_store.reset_failed_attempts(employee_id)
    return credential["must_reset"]


async def reset_secret_code(employee_id: str, current_secret_code: str, new_secret_code: str) -> None:
    """Only an already-authenticated admin can reach this (the route's own
    require_role call), and must also prove they know the CURRENT code - a
    stolen session token alone can't silently change it."""
    credential_store = get_db_gateway().admin_credential_store()
    if not await credential_store.verify_secret_code(employee_id, current_secret_code):
        raise InvalidAdminSecretCodeError()
    await credential_store.set_secret_code(employee_id, new_secret_code)
