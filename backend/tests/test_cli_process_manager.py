from __future__ import annotations

from pathlib import Path

from app.cli.process_manager import LocalStackManager


class FakeProcess:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):  # noqa: ARG002
        return 0

    def send_signal(self, sig):  # noqa: ARG002
        self.killed = True


def test_local_stack_manager_start_and_stop(monkeypatch, tmp_path: Path) -> None:
    created: list[list[str]] = []

    def fake_popen(cmd, **kwargs):
        created.append(cmd)
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(LocalStackManager, "_wait_for_healthy", lambda self, url: None)

    manager = LocalStackManager(
        backend_dir=tmp_path / "backend",
        frontend_dir=tmp_path / "frontend",
        api_port=8000,
        ui_port=5173,
    )
    manager.start()

    assert created
    assert any("uvicorn" in part for part in created[0])

    manager.stop()
    assert manager.backend_process is None
    assert manager.frontend_process is None
