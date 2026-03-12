from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import signal
import subprocess
import sys
import time
from typing import Iterable

import httpx


@dataclass
class LocalStackManager:
    backend_dir: Path
    frontend_dir: Path
    api_port: int
    ui_port: int
    python_bin: str = sys.executable
    npm_cmd: str = "npm"

    def __post_init__(self) -> None:
        self.backend_process: subprocess.Popen | None = None
        self.frontend_process: subprocess.Popen | None = None

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def ui_url(self) -> str:
        return f"http://127.0.0.1:{self.ui_port}"

    def start(self) -> None:
        if self.backend_process or self.frontend_process:
            return

        backend_env = os.environ.copy()
        backend_env["GOV_UI_CORS_ORIGINS"] = (
            f"[\"http://127.0.0.1:{self.ui_port}\",\"http://localhost:{self.ui_port}\"]"
        )

        self.backend_process = subprocess.Popen(
            [
                self.python_bin,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.api_port),
            ],
            cwd=self.backend_dir,
            env=backend_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self.frontend_process = subprocess.Popen(
            [self.npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(self.ui_port)],
            cwd=self.frontend_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        self._wait_for_healthy(self.api_url + "/health")
        self._wait_for_healthy(self.ui_url)

    def stop(self) -> None:
        for process in [self.frontend_process, self.backend_process]:
            self._stop_process(process)

        self.backend_process = None
        self.frontend_process = None

    def _wait_for_healthy(self, url: str, timeout_seconds: float = 30.0) -> None:
        start = time.monotonic()
        while time.monotonic() - start < timeout_seconds:
            try:
                with httpx.Client(timeout=2.0) as client:
                    response = client.get(url)
                if response.status_code < 500:
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError(f"Timed out waiting for service: {url}")

    @staticmethod
    def _stop_process(process: subprocess.Popen | None) -> None:
        if process is None:
            return
        if process.poll() is not None:
            return

        try:
            process.terminate()
            process.wait(timeout=5)
            return
        except Exception:
            pass

        try:
            process.send_signal(signal.SIGKILL)
            process.wait(timeout=3)
        except Exception:
            pass


def discover_workspace_root(start: Path) -> Path:
    for candidate in [start, *start.parents]:
        if (candidate / "backend").exists() and (candidate / "frontend").exists():
            return candidate
    raise RuntimeError("Unable to discover workspace root containing backend/ and frontend/")


def ensure_commands_available(commands: Iterable[str]) -> None:
    from shutil import which

    for command in commands:
        if which(command) is None:
            raise RuntimeError(f"Required command not found: {command}")
