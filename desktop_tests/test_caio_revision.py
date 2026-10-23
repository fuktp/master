from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from desktop_tests.ui_helpers import settle
from orquestrador_app.config import (
    Config,
    Routine,
    Schedule,
    defaults,
    from_dict,
    import_preview,
    portable,
    save,
)
from orquestrador_app.paths import Paths
from orquestrador_app.resources import source_root
from orquestrador_app.schedule import eligible, next_execution


def test_translation_catalog_has_unique_keys_for_windows_powershell() -> None:
    pairs = json.loads(
        (source_root() / "orquestrador_app/locales.json").read_text(encoding="utf-8"),
        object_pairs_hook=list,
    )
    keys = [key.casefold() for key, _ in pairs]
    assert len(keys) == len(set(keys)), "ConvertFrom-Json rejects case-insensitive duplicate keys"
    assert all(
        len(values) == 2 and all(isinstance(v, str) and v for v in values) for _, values in pairs
    )


@pytest.mark.parametrize("language,expected", [("en", "Disabled"), ("es", "Deshabilitada")])
def test_disabled_status_translation_uses_one_key(language: str, expected: str) -> None:
    from orquestrador_app.i18n import set_language, tr

    try:
        set_language(language)
        assert tr("Desabilitada") == tr("desabilitada") == expected
        assert tr("Texto fora do catálogo") == "Texto fora do catálogo"
    finally:
        set_language("pt-BR")
    assert tr("desabilitada") == "desabilitada"


def test_portable_round_trip_includes_language_delay_and_excludes_script_versions(
    tmp_path: Path,
) -> None:
    paths = Paths.user(tmp_path)
    config = defaults(paths, source_root())
    config.language = "es"
    config.queue_delay_seconds = 45
    config.routines[0].script_version = "1.8"
    exported = portable(config)
    assert "script_version" not in exported["routines"][0]
    other = defaults(paths, source_root())
    restored, _ = import_preview(other, exported)
    assert portable(restored) == exported
    assert restored.routines[0].script == other.routines[0].script


def test_weekdays_daily_success_and_weekend() -> None:
    job = Routine(
        "custom",
        "Custom",
        "script.py",
        schedule=Schedule(frequency="weekdays", days=list(range(7)), times=["08:30", "14:45"]),
    )
    now = dt.datetime(2026, 10, 23, 14, 45, tzinfo=dt.timezone.utc)
    assert eligible(job, {}, now).due
    state = {"periods": {"D:2026-10-23"}}
    assert not eligible(job, state, now).due
    assert not eligible(job, {}, now + dt.timedelta(days=1)).due
    assert next_execution(job, state, now).weekday() == 0


def test_script_versions_no_reauthorization_restore_and_remove(tmp_path: Path) -> None:
    from orquestrador_app.script_versions import capture, remove, restore, versions

    paths = Paths.user(tmp_path / "app")
    paths.ensure()
    source = tmp_path / "production.py"
    source.write_text("print(1)")
    job = Routine("custom", "Custom", str(source), requires_browser=False, command="")
    config = Config(routines=[job])
    save(paths, config)
    first = capture(paths, job)
    source.write_text("print(2)")
    second = capture(paths, job)
    assert first["sha256"] != second["sha256"] and len(versions(paths, job)) == 2
    restore(paths, config, job, first["sha256"])
    assert Path(job.script).read_text() == "print(1)" and source.read_text() == "print(2)"
    remove(paths, config, job.id)
    assert not config.routines and len(versions(paths, job)) == 2 and source.is_file()
    config.routines = [job]
    save(paths, config)
    remove(paths, config, job.id, purge=True)
    assert versions(paths, job) == [] and source.is_file()


def test_missing_script_cannot_replace_recorded_snapshot(tmp_path: Path) -> None:
    from orquestrador_app.script_versions import capture

    with pytest.raises(ValueError, match="Python"):
        capture(Paths.user(tmp_path), Routine("missing", "Missing", str(tmp_path / "missing.py")))


def test_json_xlsx_sanitization_and_formula_cells(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    from orquestrador_app.exporting import export_data

    values = [
        {"message": "=1+1", "password": "secret", "url": "https://internal.example.invalid/path"}
    ]
    for suffix in ("json", "xlsx"):
        export_data(tmp_path / f"output.{suffix}", values)
    value = json.loads((tmp_path / "output.json").read_text())
    assert value[0]["password"] == "[removido]" and "internal" not in value[0]["url"]
    book = load_workbook(tmp_path / "output.xlsx", read_only=True, data_only=False)
    cells = list(book.active.rows)
    rows = [[cell.value for cell in row] for row in cells]
    assert cells[1][0].data_type == "s"
    book.close()
    assert rows[1][0] == "=1+1" and rows[1][1] == "[removido]"


def test_native_preview_schedules_start_active_but_preserves_pause(tmp_path: Path) -> None:
    from orquestrador_app.native_bridge import preview
    from orquestrador_app.sandbox import mark

    root = tmp_path / "isolated"
    new = preview(root)
    assert new["config"]["scheduling_paused"] is False
    paths = Paths.user(root)
    paths.ensure()
    mark(paths)
    config = from_dict(new["config"])
    config.scheduling_paused = True
    save(paths, config)
    assert preview(root)["config"]["scheduling_paused"] is True


def test_driver_search_prefers_local_without_global_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orquestrador_app.driver import candidates

    paths = Paths.user(tmp_path / "app")
    external = tmp_path / "user tool/msedgedriver.exe"
    external.parent.mkdir()
    external.write_bytes(b"fixture")
    config = Config(
        driver=str(tmp_path / "missing.exe"),
        driver_options={"search_paths": [str(external.parent)]},
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    result = candidates(paths, config)
    assert external.resolve() in result and external.read_bytes() == b"fixture"


def test_driver_auto_repair_reuses_signed_compatible_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import orquestrador_app.driver as driver

    paths = Paths.user(tmp_path / "app")
    paths.ensure()
    config = Config(driver=str(paths.root / "driver.exe"), logs=str(paths.root / "logs"))
    instance = driver.guard(paths, config)
    local = tmp_path / "msedgedriver.exe"
    local.write_bytes(b"fixture")
    monkeypatch.setattr(driver, "candidates", lambda *_: [local])
    monkeypatch.setattr(instance, "edge_version", lambda *_: (140, 0, 1, 2))
    monkeypatch.setattr(instance, "driver_version", lambda *_: (140, 0, 1, 7))
    verified = []
    monkeypatch.setattr(instance, "authenticode_status", lambda p: verified.append(p) or "Valid")
    assert instance._resolve_driver_with_selenium_manager(Path("edge")) == local
    assert verified == [local]


def test_queue_delay_is_after_previous_finish_and_cancellable(
    environment: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orquestrador_app.engine import Engine

    paths, config = environment
    config.routines = config.routines[:2]
    config.queue_delay_seconds = 30
    config.routines[0].schedule.days = list(range(7))
    config.routines[1].schedule.days = list(range(7))
    clock = [0.0]
    starts = []
    monkeypatch.setattr("orquestrador_app.engine.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "orquestrador_app.engine.time.sleep", lambda n: clock.__setitem__(0, clock[0] + n)
    )

    def run(*_: Any) -> dict[str, Any]:
        starts.append(clock[0])
        clock[0] += 5
        return {"code": 0}

    results = Engine(paths, config, runner=run).run(
        scheduled=True, now=dt.datetime(2026, 10, 22, 9, 0, tzinfo=dt.timezone.utc)
    )
    assert all(r["status"] == "success" for r in results)
    assert starts == [0, 35]


def test_task_install_remove_return_verified_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orquestrador_app.tasks import WindowsTasks

    paths = Paths.user(tmp_path)
    tasks = WindowsTasks(paths)
    value = [None]
    monkeypatch.setattr(tasks, "export", lambda: value[0])
    monkeypatch.setattr(tasks, "register_xml", lambda text: value.__setitem__(0, text))
    monkeypatch.setattr(tasks, "_call", lambda *_, **__: value.__setitem__(0, None))
    result = tasks.install(Path("Iniciar.vbs"), "user")
    assert result["installed"] and result["matches"]
    assert tasks.remove()["action"] == "removed"
    assert tasks.remove()["action"] == "already_absent"


@pytest.mark.parametrize("language", ["pt-BR", "en", "es"])
def test_translated_visible_controls_selection_and_new_script_path(
    tmp_path: Path, language: str
) -> None:
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from orquestrador_app.gui import MainWindow, RoutineDialog
    from orquestrador_app.i18n import tr, translate_tree

    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    paths.ensure()
    config = defaults(paths, source_root())
    config.language = language
    save(paths, config)
    window = MainWindow(paths)
    settle(window)
    window.show()
    app.processEvents()
    translate_tree(window)
    try:
        assert window.tabs.tabText(0) == tr("Painel")
        assert app.palette().color(QPalette.ColorRole.Text).name() == "#333333"
        assert app.palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
        assert not window.progress.isVisible()
        window.panel.selectRow(0)
        window.selection_actions()
        assert window.run_button.isEnabled() and not window.batch_button.isVisible()
        selection = window.panel.selectionModel()
        selection.select(
            window.panel.model().index(1, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
        window.selection_actions()
        assert window.run_button.text() == tr("Executar lote selecionado")
        dialog = RoutineDialog(config, config.routines[0], window)
        dialog.show()
        app.processEvents()
        dialog.frequency.setCurrentIndex(dialog.frequency.findData("weekdays"))
        assert dialog.days_picker.values() == list(range(5))
        assert all(button.toolTip() for button in dialog.days_picker.buttons)
        replacement = tmp_path / "replacement.py"
        replacement.write_text('print("local")')
        dialog.script.setText(str(replacement))
        dialog.order.setCurrentIndex(2)
        dialog.accept_values()
        assert dialog.updated.script == str(replacement)
        assert sorted(j.order for j in dialog.result_config.routines) == list(range(5))
        assert dialog.updated.order == 2
        assert dialog.times.values() == ["08:30"]
        dialog.done(0)
    finally:
        window.exit_requested = True
        window.close()
        app.processEvents()


def test_kwms_diagnostic_uses_real_empty_response_rule_and_preserves_inconclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from orquestrador_app import connectivity
    from orquestrador_app.worker import module_for

    paths = Paths.user(tmp_path / "app")
    paths.ensure()
    config = defaults(paths, source_root())
    job = config.job("kwms_alocacoes_tool_edge")
    module = module_for(job)
    evidence = connectivity.Evidence(public_reachable=True, target_dns=True, target_tcp=True)
    monkeypatch.setattr(connectivity, "probe", lambda *_: evidence)
    monkeypatch.setattr("orquestrador_app.driver.diagnose", lambda *_, **__: {"status": "ready"})
    closed = []
    browser = SimpleNamespace(
        set_page_load_timeout=lambda _: None,
        get=lambda _: None,
        execute_script=lambda _: "ERR_EMPTY_RESPONSE",
        quit=lambda: closed.append(True),
    )
    monkeypatch.setattr("selenium.webdriver.Edge", lambda **_: browser)
    result = connectivity.kwms_diagnostic(
        paths, config, job, module, module.LOGIN_URL, "https://public.example.invalid"
    )
    assert result["category"] == "inconclusive" and result["evidence"]["empty_response"]
    assert closed == [True]
    from orquestrador_app.store import Store

    assert Store(paths.database).state(job.id)["last_success"] is None


def test_task_drift_detects_disabled_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orquestrador_app.tasks import WindowsTasks, xml

    paths = Paths.user(tmp_path)
    task = WindowsTasks(paths)
    actual = xml(Path("Iniciar.vbs"), paths, "user").replace(
        "<Enabled>true</Enabled>", "<Enabled>false</Enabled>", 1
    )
    monkeypatch.setattr(task, "export", lambda: actual)
    report = task.differences(Path("Iniciar.vbs"), paths.root.name)
    assert not report["matches"] and "Triggers/LogonTrigger/Enabled" in report["differences"]
