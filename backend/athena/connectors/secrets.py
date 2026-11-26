"""Where connection secrets live. Never in .athena files, connections.json or exported code.

Default: the OS keychain via ``keyring`` (Windows Credential Manager, macOS Keychain, Secret Service).
A secret field may instead hold an ``env://VAR_NAME`` reference, resolved from the environment at use
time; that is the option for CI, containers and machines without a keychain.
"""
from __future__ import annotations

import os
from typing import Protocol

SERVICE = "athena"
ENV_PREFIX = "env://"


class SecretStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class KeyringStore:
    def get(self, key: str) -> str | None:
        import keyring
        return keyring.get_password(SERVICE, key)

    def set(self, key: str, value: str) -> None:
        import keyring
        try:
            keyring.set_password(SERVICE, key, value)
        except Exception as exc:  # e.g. no keychain on a headless Linux box
            raise RuntimeError(
                f"Couldn't store the secret in the OS keychain ({exc}). "
                "Use an environment-variable reference instead, e.g. env://MY_DB_PASSWORD."
            ) from exc

    def delete(self, key: str) -> None:
        import keyring
        try:
            keyring.delete_password(SERVICE, key)
        except Exception:
            pass  # already gone


class MemoryStore:
    """For tests."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


_store: SecretStore = KeyringStore()


def get_store() -> SecretStore:
    return _store


def set_store(store: SecretStore) -> None:
    global _store
    _store = store


def secret_key(connection: str, field: str) -> str:
    return f"connection/{connection}/{field}"


def resolve(value: str, connection: str, field: str) -> str:
    """Turn a stored marker into the secret: env://VAR -> os.environ[VAR], else the keychain entry."""
    if value.startswith(ENV_PREFIX):
        var = value[len(ENV_PREFIX):]
        if var not in os.environ:
            raise RuntimeError(f"Connection {connection!r}: environment variable {var} isn't set")
        return os.environ[var]
    secret = get_store().get(secret_key(connection, field))
    if secret is None:
        raise RuntimeError(f"Connection {connection!r}: no saved {field}. Edit the connection and enter it again.")
    return secret
