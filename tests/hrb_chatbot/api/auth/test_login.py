"""Tests for POST /v1/auth/login (Phase 106) and POST /v1/auth/admin/reset-secret-code (Phase 171)."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.auth import login
from src.hrb_chatbot.main import app
from tests.conftest import FakeAdminCredentialStore, FakeDBGateway

client = TestClient(app)


def test_known_combo_returns_200_with_the_matched_profile():
    response = client.post(
        "/v1/auth/login", json={"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_profile": {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"},
        "must_reset_secret_code": False,
    }


def test_unknown_employee_id_is_401():
    response = client.post(
        "/v1/auth/login", json={"employee_id": "EMP999", "full_name": "Nobody", "role": "employee"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNKNOWN_PERSONA"


def test_right_employee_id_wrong_role_is_401():
    response = client.post(
        "/v1/auth/login", json={"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "hr_support"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNKNOWN_PERSONA"


# Phase 169/171 - admin role also requires a correct secret_code, now
# verified against AdminCredentialStore's salted hash (seeded one-time via
# get_or_seed()), not a plaintext literal.


def test_admin_login_with_correct_one_time_code_returns_200_and_flags_must_reset(monkeypatch):
    monkeypatch.setattr(login, "get_db_gateway", lambda: FakeDBGateway())

    response = client.post(
        "/v1/auth/login",
        json={"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin", "secret_code": login.ADMIN_ONE_TIME_SEED_SECRET_CODE},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_profile"] == {"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"}
    assert body["must_reset_secret_code"] is True


def test_admin_login_with_wrong_secret_code_is_401(monkeypatch):
    monkeypatch.setattr(login, "get_db_gateway", lambda: FakeDBGateway())

    response = client.post(
        "/v1/auth/login",
        json={"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin", "secret_code": "wrong-code"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_ADMIN_SECRET_CODE"


def test_admin_login_with_missing_secret_code_is_401(monkeypatch):
    monkeypatch.setattr(login, "get_db_gateway", lambda: FakeDBGateway())

    response = client.post("/v1/auth/login", json={"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"})

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_ADMIN_SECRET_CODE"


def test_admin_login_after_reset_no_longer_flags_must_reset(monkeypatch):
    store = FakeAdminCredentialStore()
    monkeypatch.setattr(login, "get_db_gateway", lambda: FakeDBGateway(admin_credential_store=store))

    response = client.post(
        "/v1/auth/login",
        json={"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin", "secret_code": login.ADMIN_ONE_TIME_SEED_SECRET_CODE},
    )
    assert response.json()["must_reset_secret_code"] is True

    client.post(
        "/v1/auth/admin/reset-secret-code",
        json={
            "user_profile": {"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"},
            "current_secret_code": login.ADMIN_ONE_TIME_SEED_SECRET_CODE,
            "new_secret_code": "a-new-code",
        },
    )

    response = client.post(
        "/v1/auth/login",
        json={"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin", "secret_code": "a-new-code"},
    )
    assert response.status_code == 200
    assert response.json()["must_reset_secret_code"] is False


# Phase 171 - POST /v1/auth/admin/reset-secret-code


def test_non_admin_cannot_reset_the_secret_code(monkeypatch):
    monkeypatch.setattr(login, "get_db_gateway", lambda: FakeDBGateway())

    response = client.post(
        "/v1/auth/admin/reset-secret-code",
        json={
            "user_profile": {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"},
            "current_secret_code": "whatever",
            "new_secret_code": "new-code",
        },
    )

    assert response.status_code == 403


def test_reset_with_wrong_current_code_is_401(monkeypatch):
    monkeypatch.setattr(login, "get_db_gateway", lambda: FakeDBGateway())

    response = client.post(
        "/v1/auth/admin/reset-secret-code",
        json={
            "user_profile": {"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"},
            "current_secret_code": "wrong-code",
            "new_secret_code": "new-code",
        },
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_ADMIN_SECRET_CODE"


async def test_reset_with_correct_current_code_succeeds(monkeypatch):
    store = FakeAdminCredentialStore()
    await store.get_or_seed("ADM001", login.ADMIN_ONE_TIME_SEED_SECRET_CODE)  # simulates having already logged in once
    monkeypatch.setattr(login, "get_db_gateway", lambda: FakeDBGateway(admin_credential_store=store))

    response = client.post(
        "/v1/auth/admin/reset-secret-code",
        json={
            "user_profile": {"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"},
            "current_secret_code": login.ADMIN_ONE_TIME_SEED_SECRET_CODE,
            "new_secret_code": "a-new-code",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"employee_id": "ADM001", "reset": True}
