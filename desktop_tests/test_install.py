from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orquestrador_app.config import Config, save
from orquestrador_app.install import Installer
from orquestrador_app.io import Lock, atomic_json
from orquestrador_app.paths import Paths


class FakeTasks:
    def __init__(self) -> None:
        self.value = "<old/>"
        self.calls = []

    def export(self) -> str | None:
        return self.value

    def install(self, executable: Path, user: str) -> None:
        self.value = "<new/>"
        self.calls.append((str(executable), user))

    def register_xml(self, value: str, name: str | None = None) -> None:
        self.value = value

    def remove(self) -> None:
        self.value = ""

    def legacy(self, source: str) -> dict:
        return {}


def setup(
    environment: tuple[Paths, Config], tmp_path: Path
) -> tuple[Installer, Path, FakeTasks, list]:
    paths, config = environment
    for job in config.routines:
        job.enabled = False
    save(paths, config)
    source = tmp_path / "Orquestrador.exe"
    source.write_bytes(b"fixture: NOT a real Windows executable")
    tasks = FakeTasks()
    shortcuts = []
    installer = Installer(paths, tasks=tasks, health=lambda _: None, shortcut=shortcuts.append)
    return installer, source, tasks, shortcuts


@pytest.mark.parametrize("fault", ["copy", "health", "migration", "activation", "post"])
def test_transaction_failure_restores_configuration_state_pointer_and_task(
    environment: tuple[Paths, Config], tmp_path: Path, fault: str
) -> None:
    paths, config = environment
    installer, source, tasks, shortcuts = setup(environment, tmp_path)
    old = paths.config.read_bytes()
    current = {
        "owner": "orquestrador-app-v1",
        "version": "old",
        "executable": str(tmp_path / "old.exe"),
    }
    atomic_json(installer.pointer, current)
    candidate = copy.deepcopy(config)
    candidate.email = "another@example.invalid"
    with pytest.raises(RuntimeError, match="induzida"):
        installer.install(source, candidate, fault=fault)
    assert paths.config.read_bytes() == old
    assert json.loads(installer.pointer.read_text()) == current
    assert tasks.value == "<old/>"
    assert json.loads(installer.journal.read_text())["status"] == "rolled_back"
    assert shortcuts[-1] == Path(current["executable"])


def test_commit_and_interrupted_recovery(environment: tuple[Paths, Config], tmp_path: Path) -> None:
    paths, config = environment
    installer, source, tasks, shortcuts = setup(environment, tmp_path)
    installed = installer.install(source, config)
    assert installed.name == "Orquestrador.exe" and installed.read_bytes() == source.read_bytes()
    assert tasks.value == "<new/>"
    assert json.loads(installer.journal.read_text())["status"] == "committed"
    state = json.loads(installer.journal.read_text())
    state["status"] = "activating"
    atomic_json(installer.journal, state)
    assert "restaurados" in installer.recover()
    assert tasks.value == "<old/>"


def test_active_execution_blocks_update(environment: tuple[Paths, Config], tmp_path: Path) -> None:
    paths, config = environment
    installer, source, _, _ = setup(environment, tmp_path)
    from orquestrador_app.io import BusyError

    with Lock(paths.lock):
        with pytest.raises(BusyError):
            installer.install(source, config)


def test_snapshot_tamper_detected_before_restore(
    environment: tuple[Paths, Config], tmp_path: Path
) -> None:
    paths, config = environment
    installer, source, _, _ = setup(environment, tmp_path)
    installer.install(source, config)
    backup = Path(json.loads(installer.journal.read_text())["backup"])
    (backup / "config.json").write_text("tampered")
    with pytest.raises(ValueError, match="integridade"):
        installer.verify_snapshot(backup)


def test_real_health_rejects_non_windows_binary(
    environment: tuple[Paths, Config], tmp_path: Path
) -> None:
    installer, source, _, _ = setup(environment, tmp_path)
    with pytest.raises(RuntimeError, match="Windows"):
        installer.check_health(source)
