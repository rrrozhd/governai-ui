from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass
class ProfileConfig:
    name: str
    provider: str = "litellm"
    model: str = "openai/gpt-4o-mini"
    server_mode: str = "local"
    remote_url: str = "http://127.0.0.1:8000"
    api_base: str = ""
    browser_open: bool = False
    api_port: int = 8000
    ui_port: int = 5173


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".config" / "governai-ui" / "profiles.toml")

    def list_profiles(self) -> list[ProfileConfig]:
        doc = self._load_doc()
        profiles_raw = doc.get("profiles", {})
        out = [self._coerce_profile(name, payload) for name, payload in profiles_raw.items()]
        out.sort(key=lambda profile: profile.name)
        return out

    def get_profile(self, name: str) -> ProfileConfig | None:
        doc = self._load_doc()
        payload = doc.get("profiles", {}).get(name)
        if payload is None:
            return None
        return self._coerce_profile(name, payload)

    def upsert_profile(self, profile: ProfileConfig) -> None:
        doc = self._load_doc()
        doc.setdefault("profiles", {})[profile.name] = {
            "provider": profile.provider,
            "model": profile.model,
            "server_mode": profile.server_mode,
            "remote_url": profile.remote_url,
            "api_base": profile.api_base,
            "browser_open": bool(profile.browser_open),
            "api_port": int(profile.api_port),
            "ui_port": int(profile.ui_port),
        }
        meta = doc.setdefault("meta", {})
        if not meta.get("default_profile"):
            meta["default_profile"] = profile.name
        self._save_doc(doc)

    def get_default_profile_name(self) -> str | None:
        doc = self._load_doc()
        meta = doc.get("meta", {})
        default_name = meta.get("default_profile")
        if isinstance(default_name, str) and default_name.strip():
            return default_name
        return None

    def set_default_profile(self, name: str) -> None:
        doc = self._load_doc()
        if name not in doc.get("profiles", {}):
            raise KeyError(f"Unknown profile: {name}")
        doc.setdefault("meta", {})["default_profile"] = name
        self._save_doc(doc)

    def delete_profile(self, name: str) -> None:
        doc = self._load_doc()
        profiles = doc.get("profiles", {})
        if name not in profiles:
            raise KeyError(f"Unknown profile: {name}")
        profiles.pop(name)

        default_name = doc.get("meta", {}).get("default_profile")
        if default_name == name:
            next_default = sorted(profiles.keys())[0] if profiles else None
            doc.setdefault("meta", {})["default_profile"] = next_default

        self._save_doc(doc)

    def ensure_defaults(self) -> None:
        doc = self._load_doc()
        if doc.get("profiles"):
            return

        default_profile = ProfileConfig(name="default")
        doc["profiles"] = {
            "default": {
                "provider": default_profile.provider,
                "model": default_profile.model,
                "server_mode": default_profile.server_mode,
                "remote_url": default_profile.remote_url,
                "api_base": default_profile.api_base,
                "browser_open": default_profile.browser_open,
                "api_port": default_profile.api_port,
                "ui_port": default_profile.ui_port,
            }
        }
        doc["meta"] = {"default_profile": "default"}
        self._save_doc(doc)

    def _load_doc(self) -> dict:
        if not self.path.exists():
            return {"meta": {}, "profiles": {}}
        content = self.path.read_text(encoding="utf-8")
        parsed = tomllib.loads(content)
        if not isinstance(parsed, dict):
            return {"meta": {}, "profiles": {}}
        parsed.setdefault("meta", {})
        parsed.setdefault("profiles", {})
        return parsed

    def _save_doc(self, doc: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []

        default_name = doc.get("meta", {}).get("default_profile")
        lines.append("[meta]")
        if default_name is None:
            lines.append("default_profile = \"\"")
        else:
            lines.append(f"default_profile = {self._toml_string(str(default_name))}")

        profiles = doc.get("profiles", {})
        for name in sorted(profiles.keys()):
            payload = profiles[name] or {}
            lines.append("")
            lines.append(f"[profiles.{name}]")
            lines.append(f"provider = {self._toml_string(str(payload.get('provider', 'litellm')))}")
            lines.append(f"model = {self._toml_string(str(payload.get('model', 'openai/gpt-4o-mini')))}")
            lines.append(f"server_mode = {self._toml_string(str(payload.get('server_mode', 'local')))}")
            lines.append(f"remote_url = {self._toml_string(str(payload.get('remote_url', 'http://127.0.0.1:8000')))}")
            lines.append(f"api_base = {self._toml_string(str(payload.get('api_base', '')))}")
            lines.append(f"browser_open = {str(bool(payload.get('browser_open', False))).lower()}")
            lines.append(f"api_port = {int(payload.get('api_port', 8000))}")
            lines.append(f"ui_port = {int(payload.get('ui_port', 5173))}")

        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    @staticmethod
    def _toml_string(value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @staticmethod
    def _coerce_profile(name: str, payload: dict) -> ProfileConfig:
        return ProfileConfig(
            name=name,
            provider=str(payload.get("provider", "litellm")),
            model=str(payload.get("model", "openai/gpt-4o-mini")),
            server_mode=str(payload.get("server_mode", "local")),
            remote_url=str(payload.get("remote_url", "http://127.0.0.1:8000")),
            api_base=str(payload.get("api_base", "")),
            browser_open=bool(payload.get("browser_open", False)),
            api_port=int(payload.get("api_port", 8000)),
            ui_port=int(payload.get("ui_port", 5173)),
        )
