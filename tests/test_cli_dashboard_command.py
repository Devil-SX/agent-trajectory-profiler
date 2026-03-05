from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

import agent_vis.cli.main as cli_main


class _FakeProcess:
    def __init__(self, poll_sequence: list[int | None]) -> None:
        self._poll_sequence = poll_sequence
        self._poll_index = 0
        self.returncode: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        if self._poll_index < len(self._poll_sequence):
            result = self._poll_sequence[self._poll_index]
            self._poll_index += 1
            if result is not None:
                self.returncode = result
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        self.returncode = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_dashboard_starts_dual_processes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()

    backend_process = _FakeProcess([None, 0])
    frontend_process = _FakeProcess([None, None, None])
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def _fake_popen(cmd: list[str], **kwargs: object) -> _FakeProcess:
        popen_calls.append((cmd, kwargs))
        if "uvicorn" in cmd:
            return backend_process
        return frontend_process

    monkeypatch.setattr(cli_main, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli_main.shutil, "which", lambda _: "/usr/bin/npm")
    monkeypatch.setattr(cli_main.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(cli_main.time, "sleep", lambda _: None)

    runner = CliRunner()
    result = runner.invoke(
        cli_main.main,
        [
            "dashboard",
            "--host",
            "127.0.0.1",
            "--port",
            "8123",
            "--reload",
            "--log-level",
            "debug",
            "--frontend-port",
            "5178",
        ],
    )

    assert result.exit_code == 0
    assert len(popen_calls) == 2
    backend_cmd, backend_kwargs = popen_calls[0]
    frontend_cmd, frontend_kwargs = popen_calls[1]

    assert backend_cmd[:4] == [cli_main.sys.executable, "-m", "uvicorn", "agent_vis.api.app:app"]
    assert "--host" in backend_cmd and "127.0.0.1" in backend_cmd
    assert "--port" in backend_cmd and "8123" in backend_cmd
    assert "--reload" in backend_cmd
    assert "--log-level" in backend_cmd and "debug" in backend_cmd
    assert "env" in backend_kwargs

    assert frontend_cmd == [
        "/usr/bin/npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5178",
    ]
    assert frontend_kwargs["cwd"] == frontend_dir
    assert frontend_process.terminate_calls == 1


def test_dashboard_fails_when_npm_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "frontend").mkdir()
    monkeypatch.setattr(cli_main, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli_main.shutil, "which", lambda _: None)

    runner = CliRunner()
    result = runner.invoke(cli_main.main, ["dashboard"])

    assert result.exit_code == 1
    assert "npm not found" in result.output


def test_dashboard_fails_when_frontend_directory_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_main, "get_project_root", lambda: tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli_main.main, ["dashboard"])

    assert result.exit_code == 1
    assert "frontend directory not found" in result.output


def test_dashboard_keyboard_interrupt_cleans_up_processes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()

    backend_process = _FakeProcess([None, None, None])
    frontend_process = _FakeProcess([None, None, None])

    popen_calls = {"count": 0}

    def _fake_popen(cmd: list[str], **kwargs: object) -> _FakeProcess:
        del cmd, kwargs
        popen_calls["count"] += 1
        if popen_calls["count"] == 1:
            return backend_process
        return frontend_process

    def _interrupt_sleep(_: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli_main.shutil, "which", lambda _: "/usr/bin/npm")
    monkeypatch.setattr(cli_main.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(cli_main.time, "sleep", _interrupt_sleep)

    runner = CliRunner()
    result = runner.invoke(cli_main.main, ["dashboard"])

    assert result.exit_code == 0
    assert backend_process.terminate_calls == 1
    assert frontend_process.terminate_calls == 1
