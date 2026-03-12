from __future__ import annotations

from app.cli.keyring_store import KeyringStore


class FakeKeyring:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, account: str, value: str) -> None:
        self.data[(service, account)] = value

    def get_password(self, service: str, account: str) -> str | None:
        return self.data.get((service, account))

    def delete_password(self, service: str, account: str) -> None:
        self.data.pop((service, account), None)


def test_keyring_store_roundtrip() -> None:
    backend = FakeKeyring()
    store = KeyringStore(backend=backend)

    store.set_api_key(profile_name="default", provider="litellm", api_key="sk-test")
    assert store.get_api_key(profile_name="default", provider="litellm") == "sk-test"

    store.delete_api_key(profile_name="default", provider="litellm")
    assert store.get_api_key(profile_name="default", provider="litellm") is None
