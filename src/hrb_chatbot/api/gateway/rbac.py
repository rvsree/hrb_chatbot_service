"""Identity + role check for every route - 401 for a missing/invalid identity, 403 for the wrong role."""

from fastapi import HTTPException, Query

from src.hrb_chatbot.api.gateway.activity_tracker import track_activity_if_due
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.models.common import UserProfile


def identity_from_query_params(
    employee_id: str | None = Query(None),
    full_name: str | None = Query(None),
    role: str | None = Query(None),
) -> UserProfile | None:
    """Phase 96, GET routes only - the Fetch spec forbids a body on GET/HEAD,
    so a real browser can never send identity the way every POST/DELETE
    route does. Returns None (not a 422) when anything's missing, so
    require_role() still raises its normal 401 - same error behavior,
    different transport."""
    if employee_id is None or full_name is None or role is None:
        return None
    return UserProfile(employee_id=employee_id, full_name=full_name, role=role)


def require_role(user_profile: UserProfile | None, *allowed_roles: Role) -> UserProfile:
    if user_profile is None:
        raise HTTPException(status_code=401, detail="Missing required user_profile in the request payload")

    try:
        Role(user_profile.role)
    except ValueError:
        valid_roles = [member.value for member in Role]
        raise HTTPException(status_code=401, detail=f"Unknown role {user_profile.role!r} - choose one of {valid_roles}")

    if user_profile.role not in allowed_roles:
        allowed = [role.value for role in allowed_roles]
        raise HTTPException(
            status_code=403,
            detail=f"Role {user_profile.role!r} is not permitted here - requires one of {allowed}",
        )
    # Phase 262 - every protected route funnels through this point once
    # identity is confirmed valid; this is the one chokepoint that lets
    # the idle-timeout auto-pause feature see real usage across the whole
    # app without instrumenting each route by hand. Deliberately placed
    # after both checks above, not before - an invalid/unauthorized
    # request shouldn't count as "someone using the app."
    track_activity_if_due()
    return user_profile
