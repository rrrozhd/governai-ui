from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import webbrowser

import httpx
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from app.cli.api_client import BackendClient
from app.cli.keyring_store import KeyringStore
from app.cli.process_manager import LocalStackManager, discover_workspace_root, ensure_commands_available
from app.cli.profiles import ProfileConfig, ProfileStore
from app.cli.tui import DashboardApp


console = Console()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "launch":
        _command_launch(args)
        return

    if args.command == "connect":
        _command_connect(args)
        return

    if args.command == "profile":
        _command_profile(args)
        return

    parser.print_help()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="governai-ui", description="GovernAI TUI launcher")
    subparsers = parser.add_subparsers(dest="command")

    launch = subparsers.add_parser("launch", help="Interactive launch for local/remote")
    launch.add_argument("--profile", default=None, help="Profile name to load/save")

    connect = subparsers.add_parser("connect", help="Connect directly to remote server")
    connect.add_argument("--remote-url", required=True, help="Remote API base URL")
    connect.add_argument("--profile", default="remote", help="Profile name")
    connect.add_argument("--provider", default="litellm")
    connect.add_argument("--model", default="openai/gpt-4o-mini")
    connect.add_argument("--api-base", default="")
    connect.add_argument("--api-key", default=None)

    profile = subparsers.add_parser("profile", help="Profile operations")
    profile_sub = profile.add_subparsers(dest="profile_command")

    profile_sub.add_parser("list", help="List saved profiles")

    set_default = profile_sub.add_parser("set-default", help="Set default profile")
    set_default.add_argument("name")

    delete = profile_sub.add_parser("delete", help="Delete profile")
    delete.add_argument("name")
    delete.add_argument("--purge-key", action="store_true", help="Delete stored key for profile/provider")

    return parser


def _command_launch(args: argparse.Namespace) -> None:
    store = ProfileStore()
    store.ensure_defaults()
    keyring = KeyringStore()

    profile_name = args.profile or store.get_default_profile_name() or "default"
    profile = store.get_profile(profile_name) or ProfileConfig(name=profile_name)
    stored_key = keyring.get_api_key(profile_name=profile_name, provider=profile.provider)

    updated = _interactive_profile_prompt(profile, stored_key)
    api_key = updated[1]
    profile = updated[0]

    store.upsert_profile(profile)
    store.set_default_profile(profile.name)
    if api_key:
        keyring.set_api_key(profile_name=profile.name, provider=profile.provider, api_key=api_key)

    _run_dashboard(profile_name=profile.name, profile=profile, api_key=api_key)


def _interactive_profile_prompt(profile: ProfileConfig, stored_key: str | None) -> tuple[ProfileConfig, str | None]:
    console.print("[bold]Configure Launch[/bold]")

    provider = Prompt.ask("Provider", default=profile.provider)
    model = Prompt.ask("Model", default=profile.model)
    server_mode = Prompt.ask("Server mode", choices=["local", "remote"], default=profile.server_mode)

    remote_url = profile.remote_url
    if server_mode == "remote":
        remote_url = Prompt.ask("Remote API URL", default=profile.remote_url)

    api_base = Prompt.ask("Provider API base (optional)", default=profile.api_base)

    api_key_default_label = "(stored)" if stored_key else ""
    api_key_input = Prompt.ask(
        f"API key {api_key_default_label}".strip(),
        default="",
        password=True,
        show_default=False,
    )
    api_key = api_key_input.strip() or stored_key

    browser_open = profile.browser_open
    if server_mode == "local":
        browser_open = Confirm.ask("Open browser dashboard after startup?", default=profile.browser_open)

    updated_profile = replace(
        profile,
        provider=provider,
        model=model,
        server_mode=server_mode,
        remote_url=remote_url,
        api_base=api_base,
        browser_open=browser_open,
    )
    return updated_profile, api_key


def _command_connect(args: argparse.Namespace) -> None:
    store = ProfileStore()
    store.ensure_defaults()
    keyring = KeyringStore()

    profile = ProfileConfig(
        name=args.profile,
        provider=args.provider,
        model=args.model,
        server_mode="remote",
        remote_url=args.remote_url,
        api_base=args.api_base,
        browser_open=False,
    )
    store.upsert_profile(profile)

    api_key = args.api_key or keyring.get_api_key(profile_name=profile.name, provider=profile.provider)
    if args.api_key:
        keyring.set_api_key(profile_name=profile.name, provider=profile.provider, api_key=args.api_key)

    _run_dashboard(profile_name=profile.name, profile=profile, api_key=api_key)


def _command_profile(args: argparse.Namespace) -> None:
    store = ProfileStore()
    store.ensure_defaults()
    keyring = KeyringStore()

    if args.profile_command == "list":
        profiles = store.list_profiles()
        default_name = store.get_default_profile_name()
        table = Table(title="governai-ui profiles")
        table.add_column("name")
        table.add_column("default")
        table.add_column("server")
        table.add_column("model")
        table.add_column("key")

        for profile in profiles:
            key_value = keyring.get_api_key(profile_name=profile.name, provider=profile.provider)
            masked = f"***{key_value[-4:]}" if key_value else "(none)"
            table.add_row(
                profile.name,
                "yes" if profile.name == default_name else "",
                f"{profile.server_mode}:{profile.remote_url if profile.server_mode == 'remote' else profile.api_port}",
                profile.model,
                masked,
            )
        console.print(table)
        return

    if args.profile_command == "set-default":
        store.set_default_profile(args.name)
        console.print(f"Default profile set to [bold]{args.name}[/bold]")
        return

    if args.profile_command == "delete":
        profile = store.get_profile(args.name)
        store.delete_profile(args.name)
        if args.purge_key and profile is not None:
            keyring.delete_api_key(profile_name=profile.name, provider=profile.provider)
        console.print(f"Deleted profile [bold]{args.name}[/bold]")
        return

    raise SystemExit("Unknown profile command")


def _run_dashboard(*, profile_name: str, profile: ProfileConfig, api_key: str | None) -> None:
    manager: LocalStackManager | None = None
    base_url = profile.remote_url

    try:
        if profile.server_mode == "local":
            ensure_commands_available(["npm"])
            workspace = discover_workspace_root(Path.cwd())
            manager = LocalStackManager(
                backend_dir=workspace / "backend",
                frontend_dir=workspace / "frontend",
                api_port=profile.api_port,
                ui_port=profile.ui_port,
            )
            manager.start()
            base_url = manager.api_url
            if profile.browser_open:
                webbrowser.open(manager.ui_url)

        response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=10.0)
        if response.status_code >= 500:
            raise RuntimeError(f"Backend health check failed: {response.status_code}")

        client = BackendClient(base_url)

        app = DashboardApp(
            client=client,
            profile=profile,
            profile_name=profile_name,
            api_key=api_key,
        )
        app.run()
    finally:
        if manager is not None:
            manager.stop()


if __name__ == "__main__":
    main()
