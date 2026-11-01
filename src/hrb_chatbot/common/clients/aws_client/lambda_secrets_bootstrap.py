"""Phase 287 - shared Secrets-Manager-to-os.environ bootstrap for Lambda
handlers that need real Postgres/Redis credentials without ever holding
them as plaintext Lambda environment variables. Extracted out of
idle_auto_pause_handler.py (Phase 262, the first Lambda to need this)
once a second Lambda (wake_up_handler.py) needed the same thing plus one
more secret - a single shared implementation instead of two copies
drifting apart.

Caches by SECRET NAME (not env var name) so the same secret is never
fetched twice within one warm execution environment, regardless of which
caller asked for it or what env var name it's destined for."""

import os

import boto3

_loaded_secret_names: set[str] = set()


def load_secrets_into_env(secret_env_map: dict[str, str]) -> None:
    """secret_env_map: {env_var_name: secret_manager_secret_name}. Skips
    any env var already set (e.g. a local/test run with a real .env -
    never calls AWS in that case) and any secret already fetched this
    warm container."""
    client = None
    for env_name, secret_name in secret_env_map.items():
        if os.environ.get(env_name):
            continue
        if secret_name in _loaded_secret_names:
            continue
        if client is None:
            client = boto3.client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
        os.environ[env_name] = response["SecretString"]
        _loaded_secret_names.add(secret_name)
