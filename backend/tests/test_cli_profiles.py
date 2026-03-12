from __future__ import annotations

from pathlib import Path

from app.cli.profiles import ProfileConfig, ProfileStore


def test_profile_store_defaults_and_upsert(tmp_path: Path) -> None:
    path = tmp_path / "profiles.toml"
    store = ProfileStore(path=path)

    store.ensure_defaults()
    assert store.get_default_profile_name() == "default"

    custom = ProfileConfig(name="work", model="ollama/llama3.1", server_mode="remote", remote_url="http://x")
    store.upsert_profile(custom)
    store.set_default_profile("work")

    loaded = store.get_profile("work")
    assert loaded is not None
    assert loaded.model == "ollama/llama3.1"
    assert loaded.server_mode == "remote"
    assert store.get_default_profile_name() == "work"


def test_profile_delete_updates_default(tmp_path: Path) -> None:
    path = tmp_path / "profiles.toml"
    store = ProfileStore(path=path)
    store.upsert_profile(ProfileConfig(name="a"))
    store.upsert_profile(ProfileConfig(name="b"))
    store.set_default_profile("a")

    store.delete_profile("a")
    assert store.get_default_profile_name() == "b"
