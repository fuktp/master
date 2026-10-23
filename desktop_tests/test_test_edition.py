from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from orquestrador_app.config import defaults, portable, save
from orquestrador_app.engine import Engine
from orquestrador_app.io import Lock, atomic_json, digest
from orquestrador_app.paths import Paths
from orquestrador_app.resources import source_root
from orquestrador_app.runtime import CREATE_NEW_CONSOLE, CREATE_NO_WINDOW, hidden_options
from orquestrador_app.sandbox import (
    check_location,
    locate,
    mark,
    prepare_config,
    remember,
    validate_isolation,
)
from orquestrador_app.store import Store
from orquestrador_app.tasks import task_name
from orquestrador_app.versioning import history, record


def test_existing_original_folder_is_rejected_without_changes(tmp_path: Path) -> None:
    original = tmp_path / "produção"
    original.mkdir()
    report = original / "Clientes.xlsx"
    report.write_bytes(b"original: never overwrite")
    before = digest(report)
    with pytest.raises(ValueError, match="arquivos existentes"):
        check_location(original)
    assert digest(report) == before and list(original.iterdir()) == [report]


def test_empty_location_is_read_only_until_apply(tmp_path: Path) -> None:
    selected = tmp_path / "nova pasta com ç e espaços"
    assert check_location(selected).root == selected
    assert not selected.exists()


def test_import_rebases_all_production_paths_and_preserves_original(tmp_path: Path) -> None:
    production = Paths.user(tmp_path / "original")
    original = defaults(production, source_root())
    original.routines[0].target = str(production.root / "Clientes.xlsx")
    original.routines[0].arguments = ["--clients-dir", str(production.root)]
    original.routines[0].environment = {"DESTINO": str(production.root)}
    original.legacy = {"state_path": str(production.root / "state.json"), "config_source": "old"}
    selected = Paths.user(tmp_path / "teste")
    config = prepare_config(selected, original)
    validate_isolation(selected, config)
    assert original.routines[0].arguments and original.profile == str(
        production.root / "profiles/Edge"
    )
    assert config.test_mode and config.scheduling_paused and not config.install_schedules
    assert not config.routines[0].arguments and not config.routines[0].environment
    assert "state_path" not in config.legacy and "config_source" not in config.legacy
    assert all(Path(job.target).is_relative_to(selected.root) for job in config.routines)


@pytest.mark.parametrize("field", ["profile", "driver", "downloads", "logs", "install_root"])
def test_machine_path_cannot_escape_test_folder(tmp_path: Path, field: str) -> None:
    paths = Paths.user(tmp_path / "teste")
    config = prepare_config(paths)
    setattr(config, field, str(tmp_path / "original" / field))
    with pytest.raises(ValueError):
        save(paths, config)
    assert not paths.config.exists()


def test_destination_escape_and_symlink_are_rejected_before_execution(tmp_path: Path) -> None:
    paths = Paths.user(tmp_path / "teste")
    paths.ensure()
    config = prepare_config(paths)
    production = tmp_path / "original"
    production.mkdir()
    (paths.root / "relatorios").symlink_to(production, target_is_directory=True)
    with pytest.raises(ValueError, match="Destino"):
        Engine(paths, config=config)
    assert not list(production.iterdir())


def test_reopen_uses_only_recognized_test_locator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "perfil"))
    selected = Paths.user(tmp_path / "teste")
    assert locate().root.name == "launcher"
    mark(selected)
    remember(selected)
    assert locate().root == selected.root
    assert task_name(selected).startswith("\\Orquestrador-Teste-")
    (selected.root / "instalacao-teste.json").unlink()
    assert locate().root.name == "launcher"


def test_frozen_entry_rejects_original_configuration_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orquestrador_app.__main__ import main

    original = Paths.user(tmp_path / "produção")
    config = defaults(original, source_root())
    save(original, config)
    before = original.config.read_bytes()
    before_files = {
        p.relative_to(original.root): p.read_bytes()
        for p in original.root.rglob("*")
        if p.is_file()
    }
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    with pytest.raises(ValueError, match="original"):
        main(["--data-root", str(original.root), "list-jobs"])
    assert original.config.read_bytes() == before
    assert {
        p.relative_to(original.root): p.read_bytes()
        for p in original.root.rglob("*")
        if p.is_file()
    } == before_files


def test_portable_preferences_do_not_move_test_ownership(tmp_path: Path) -> None:
    config = prepare_config(Paths.user(tmp_path))
    data = portable(config)
    assert "test_mode" not in data and "install_schedules" not in data


def test_console_flags_preserve_controls_and_remove_visible_console() -> None:
    options = {"creationflags": CREATE_NEW_CONSOLE | 0x200, "stdout": "capture"}
    result = hidden_options(options)
    assert result["creationflags"] & CREATE_NO_WINDOW
    assert not result["creationflags"] & CREATE_NEW_CONSOLE
    assert result["creationflags"] & 0x200 and result["stdout"] == "capture"
    assert options["creationflags"] & CREATE_NEW_CONSOLE


def test_global_console_policy_covers_legacy_subprocess_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    from orquestrador_app import runtime

    values = []

    class Base:
        def __init__(self, *args: object, **kwargs: object):
            values.append(kwargs)

    monkeypatch.setattr(runtime, "_installed", False)
    monkeypatch.setattr(subprocess, "Popen", Base)
    monkeypatch.setattr(sys, "platform", "win32")
    runtime.install_console_policy()
    subprocess.Popen(["cmd.exe"], creationflags=CREATE_NEW_CONSOLE)
    assert values[0]["creationflags"] == CREATE_NO_WINDOW


def test_internal_versions_are_immutable_manifests(tmp_path: Path) -> None:
    paths = Paths.user(tmp_path)
    paths.ensure()
    save(paths, prepare_config(paths))
    exe = tmp_path / "Orquestrador.exe"
    exe.write_bytes(b"unit fixture, not PE")
    backup = tmp_path / "backups/app/fixture"
    atomic_json(backup / "manifest.json", {"files": {}})
    first = record(paths, exe, backup)
    original = next((tmp_path / "versionamento").glob("*.json")).read_bytes()
    second = record(paths, exe, backup)
    assert first["id"] != second["id"] and len(history(paths)) == 2
    assert any(p.read_bytes() == original for p in (tmp_path / "versionamento").glob("*.json"))
    assert first["sha256"] == digest(exe)


def test_wizard_folder_selection_rebases_everything_without_installing(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from orquestrador_app.gui import InstallWizard

    app = QApplication.instance() or QApplication([])
    bootstrap = Paths.user(tmp_path / "bootstrap")
    wizard = InstallWizard(bootstrap)
    chosen = tmp_path / "nova pasta ç"
    wizard.install_root.setText(str(chosen))
    try:
        assert wizard.select_location()
        assert wizard.paths.root == chosen
        validate_isolation(wizard.paths, wizard.config)
        assert not chosen.exists()
        wizard.reject()
        app.processEvents()
        assert not chosen.exists()
    finally:
        wizard.reject()


def test_dev_gui_reads_events_locks_and_logs_off_ui_thread(tmp_path: Path) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from orquestrador_app.dev_gui import DevPanel

    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    paths.ensure()
    save(paths, prepare_config(paths))
    store = Store(paths.database)
    run = store.begin("batch-test", "Clientes", "local", None)
    store.stage(run, "validando arquivo", 2)
    store.event(run, "test", {"code": 20, "token": "do-not-export"})
    (paths.root / "logs/fixture.log").write_text(
        "password=do-not-export https://interno.example\n", encoding="utf-8"
    )
    panel = DevPanel(paths)
    panel.log_choice.addItem("fixture.log")
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(5)
    try:
        with Lock(paths.lock):
            panel.refresh(True)
            deadline = time.monotonic() + 5
            while (not panel.latest or not ticks) and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.001)
        assert panel.latest and ticks
        assert "em uso" in panel.latest["runtime"]["execution_lock"]
        assert panel.runs.rowCount() == 1 and panel.events.rowCount() == 1
        assert "do-not-export" not in panel.log_text.toPlainText()
        assert "interno.example" not in panel.log_text.toPlainText()
        assert "do-not-export" not in json.dumps(panel.latest["events"])
    finally:
        timer.stop()
        panel.shutdown()
        panel.close()
