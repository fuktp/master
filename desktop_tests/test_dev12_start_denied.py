from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from desktop_tests.test_native_distribution import (
    FakeLinks,
    FakeTasks,
    make_payload,
    public_payload,
)
from orquestrador_app import native_install
from orquestrador_app.io import atomic_json, digest, read_json
from orquestrador_app.paths import Paths
from orquestrador_app.sandbox import prepare_config
from orquestrador_app.windows_hosts import HOST_DESCRIPTIONS


def test_start_denied_preserves_native_code_executable_and_directory_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def denied(arguments: list[str], **options: Any) -> None:
        calls.append(arguments)
        error = PermissionError(13, "Access is denied")
        error.winerror = 5  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr(subprocess, "run", denied)
    target = tmp_path / "CAIO-Orquestrador.exe"
    with pytest.raises(RuntimeError) as raised:
        native_install.hidden_run([str(target), "-c", "pass"], cwd=tmp_path)
    assert "Código nativo: 5" in str(raised.value)
    assert str(target) in str(raised.value) and str(tmp_path) in str(raised.value)
    assert "Access is denied" in str(raised.value)
    assert len(calls) == 1


def test_host_check_starts_only_empty_probes_in_each_declared_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    atomic_json(tmp_path / "release.json", {"windows_process_hosts": HOST_DESCRIPTIONS})
    calls = []

    def run(arguments: list[str], **options: Any) -> subprocess.CompletedProcess[Any]:
        calls.append((arguments, options))
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(native_install, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(native_install, "hidden_run", run)
    native_install.check_windows_hosts(tmp_path)
    assert [Path(args[0]).name for args, _ in calls] == list(HOST_DESCRIPTIONS)
    assert all(args[1:] == ["-B", "-c", "pass"] for args, _ in calls)
    assert all(options["cwd"] == tmp_path / "src" for _, options in calls)


def test_denied_host_blocks_before_snapshot_and_runtime_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-data"))
    payload = make_payload(tmp_path / "payload")
    public_payload(payload)
    record = read_json(payload / "release.json")
    for name in HOST_DESCRIPTIONS:
        target = payload / "runtime" / name
        target.write_bytes(b"not executable; host preflight is mocked")
        record["files"]["runtime/" + name] = digest(target)
    record["windows_process_hosts"] = HOST_DESCRIPTIONS
    atomic_json(payload / "release.json", record)
    paths = Paths.user(tmp_path / "installation")
    config = prepare_config(paths)
    installer = native_install.NativeInstaller(
        paths, tasks=FakeTasks(), links=FakeLinks(), health=lambda _: None
    )

    def denied(release: Path) -> None:
        assert release == payload
        raise RuntimeError("host denied; code 5")

    monkeypatch.setattr(native_install, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(native_install, "check_windows_hosts", denied)
    with pytest.raises(RuntimeError, match="host denied"):
        installer.install(payload, config)
    assert not (paths.root / "app/versions").exists()
    assert not (paths.root / "backups/app").exists()
    assert not paths.config.exists() and not installer.pointer.exists()
