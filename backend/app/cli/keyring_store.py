from __future__ import annotations

from typing import Any


class KeyringStore:
    def __init__(self, service_name: str = "governai-ui", backend: Any | None = None) -> None:
        self.service_name = service_name
        if backend is not None:
            self._backend = backend
            return

        try:
            import keyring
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("keyring package is required for secure API key storage") from exc
        self._backend = keyring

    def set_api_key(self, *, profile_name: str, provider: str, api_key: str) -> None:
        account = self._account(profile_name, provider)
        self._backend.set_password(self.service_name, account, api_key)

    def get_api_key(self, *, profile_name: str, provider: str) -> str | None:
        account = self._account(profile_name, provider)
        value = self._backend.get_password(self.service_name, account)
        if value is None:
            return None
        return str(value)

    def delete_api_key(self, *, profile_name: str, provider: str) -> None:
        account = self._account(profile_name, provider)
        try:
            self._backend.delete_password(self.service_name, account)
        except Exception:
            return

    @staticmethod
    def _account(profile_name: str, provider: str) -> str:
        return f"{profile_name}:{provider}"
