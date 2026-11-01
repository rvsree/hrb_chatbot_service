"""Tests for lambda_secrets_bootstrap.py (Phase 287) - boto3 is explicitly
faked in every test, real AWS call never possible."""

from src.hrb_chatbot.common.clients.aws_client import lambda_secrets_bootstrap


class _FakeSecretsManagerClient:
    def __init__(self):
        self.requested_secret_ids = []

    def get_secret_value(self, SecretId):
        self.requested_secret_ids.append(SecretId)
        return {"SecretString": f"fake-value-for-{SecretId}"}


def _reset_cache(monkeypatch):
    monkeypatch.setattr(lambda_secrets_bootstrap, "_loaded_secret_names", set())


def test_fetches_each_secret_when_none_are_already_set(monkeypatch):
    _reset_cache(monkeypatch)
    for env_name in ("A", "B"):
        monkeypatch.delenv(env_name, raising=False)
    fake_client = _FakeSecretsManagerClient()
    monkeypatch.setattr(lambda_secrets_bootstrap.boto3, "client", lambda service: fake_client)

    lambda_secrets_bootstrap.load_secrets_into_env({"A": "secret/a", "B": "secret/b"})

    assert sorted(fake_client.requested_secret_ids) == ["secret/a", "secret/b"]
    import os

    assert os.environ["A"] == "fake-value-for-secret/a"
    assert os.environ["B"] == "fake-value-for-secret/b"


def test_skips_an_env_var_already_set_without_calling_secrets_manager_for_it(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.delenv("A", raising=False)
    monkeypatch.setenv("B", "already-set-locally")
    fake_client = _FakeSecretsManagerClient()
    monkeypatch.setattr(lambda_secrets_bootstrap.boto3, "client", lambda service: fake_client)

    lambda_secrets_bootstrap.load_secrets_into_env({"A": "secret/a", "B": "secret/b"})

    assert fake_client.requested_secret_ids == ["secret/a"]
    import os

    assert os.environ["B"] == "already-set-locally"


def test_does_not_refetch_a_secret_already_loaded_this_container(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.delenv("A", raising=False)
    fake_client = _FakeSecretsManagerClient()
    monkeypatch.setattr(lambda_secrets_bootstrap.boto3, "client", lambda service: fake_client)

    lambda_secrets_bootstrap.load_secrets_into_env({"A": "secret/a"})
    # A new caller asking for the same secret under a DIFFERENT env var
    # name still shouldn't trigger a second real fetch - cached by secret
    # name, not env var name.
    monkeypatch.delenv("C", raising=False)
    lambda_secrets_bootstrap.load_secrets_into_env({"C": "secret/a"})

    assert fake_client.requested_secret_ids == ["secret/a"]


def test_boto3_client_is_never_constructed_when_everything_is_already_set(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setenv("A", "already-set")
    monkeypatch.setattr(
        lambda_secrets_bootstrap.boto3, "client", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not be constructed"))
    )

    lambda_secrets_bootstrap.load_secrets_into_env({"A": "secret/a"})
