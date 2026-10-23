from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from desktop_tests.ui_helpers import settle
from orquestrador_app import ui
from orquestrador_app.config import defaults, save
from orquestrador_app.gui import MainWindow, RoutineDialog
from orquestrador_app.i18n import tr
from orquestrador_app.paths import Paths
from orquestrador_app.resources import asset_path, source_root


@pytest.fixture(params=["pt-BR", "en", "es"])
def design_window(tmp_path: Path, request: Any) -> Any:
    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    paths.ensure()
    config = defaults(paths, source_root())
    config.language = request.param
    save(paths, config)
    window = MainWindow(paths)
    settle(window)
    window.timer.stop()
    window.dev_panel.timer.stop()
    window.resize(1040, 850)
    window.show()
    app.processEvents()
    try:
        yield window
    finally:
        window.tray.hide()
        window.exit_requested = True
        window.close()
        app.processEvents()


def test_full_theme_and_documented_tokens_are_preserved() -> None:
    # The original complete user-supplied JSON is the contract, not a new palette.
    assert hashlib.sha256(asset_path("dashboard-theme.json").read_bytes()).hexdigest() == (
        "ccbd72f0ba43bef2d0fc22a3ed5c725fee5d5a3b96aeac73ed0ae77ece806ce6"
    )
    document = (source_root() / "DESIGN.md").read_text()
    for role, key in {
        "primary": "firstLevelElements",
        "action": "accent",
        "canvas": "backgroundNeutral",
        "danger": "bad",
    }.items():
        assert f'{role}: "{ui.theme()[key]}"' in document


def test_navigation_keyboard_and_drafts_survive(
    design_window: MainWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = design_window
    assert window.page_title.text() == tr("Painel")
    window.filter_job.setEditText("local-filter")
    for index in range(window.tabs.count()):
        window.navigation.setCurrentRow(index)
        QApplication.processEvents()
        assert window.tabs.currentIndex() == index
        assert window.page_title.text() == tr(window.tabs.tabText(index))
        assert window.page_title.text() in window.windowTitle()
        assert window.log.isVisible() and window.status_label.isVisible()
        assert window.width() == 1040
    window.tabs.setCurrentIndex(2)
    assert window.navigation.currentRow() == 2
    window.settings_json.appendPlainText("\n ")
    draft = window.settings_json.toPlainText()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    window.navigation.setCurrentRow(0)
    assert window.tabs.currentIndex() == 2
    assert window.settings_json.toPlainText() == draft
    window.reset_settings(window.config)
    assert window.filter_job.currentText() == "local-filter"
    window.navigation.setCurrentRow(0)
    window.navigation.setFocus()
    QTest.keyClick(window.navigation, Qt.Key.Key_Down)
    assert window.tabs.currentIndex() == 1


def test_clear_filters_restores_real_local_history(design_window: MainWindow) -> None:
    window = design_window
    run = window.store.begin("test-batch", window.config.routines[0].id, "manual", None)
    window.store.finish(run, "success", 0)
    window.filter_job.setEditText("no-such-routine")
    window.navigation.setCurrentRow(3)
    window.refresh_history()
    settle(window)
    assert window.history_model.rowCount() == 0
    assert window.history_empty.isVisible()
    clear = next(b for b in window.findChildren(QPushButton) if b.text() == tr("Limpar filtros"))
    clear.click()
    QApplication.processEvents()
    settle(window)
    assert window.history_model.rowCount() == 1
    assert window.history_model.rows[0]["id"] == run
    assert not window.history_empty.isVisible()
    assert window.filter_job.hasFocus()


def test_action_wrapping_and_progress_keep_controls_reachable(design_window: MainWindow) -> None:
    window = design_window
    window.panel.selectRow(0)
    QApplication.processEvents()
    for control in (
        window.run_button,
        window.force_button,
        window.login_button,
        window.pause_schedule,
    ):
        top_left = control.mapTo(window, control.rect().topLeft())
        bottom_right = control.mapTo(window, control.rect().bottomRight())
        assert window.rect().contains(top_left) and window.rect().contains(bottom_right)
        assert control.height() >= control.fontMetrics().height() + 12
    before = window.pause_schedule.mapTo(window, window.pause_schedule.rect().topLeft())
    window.progress.setRange(0, 0)
    window.progress.show()
    QApplication.processEvents()
    assert window.pause_schedule.mapTo(window, window.pause_schedule.rect().topLeft()) == before
    window.set_status(tr("Operação não concluída"), "error")
    assert window.status_label.text() and window.status_label.property("severity") == "error"
    window.progress.hide()


def test_routine_popup_and_font_sized_inputs(design_window: MainWindow) -> None:
    dialog = RoutineDialog(design_window.config, design_window.config.routines[0], design_window)
    dialog.show()
    QApplication.processEvents()
    try:
        assert dialog.script.height() >= dialog.script.fontMetrics().height() + 12
        assert dialog.times.clock.height() >= dialog.times.clock.fontMetrics().height() + 12
        dialog.frequency.setFocus()
        dialog.frequency.showPopup()
        QApplication.processEvents()
        assert dialog.frequency.view().isVisible()
        QTest.keyClick(dialog.frequency.view(), Qt.Key.Key_Escape)
        QApplication.processEvents()
        assert not dialog.frequency.view().isVisible()
    finally:
        dialog.reject()


def test_shared_adapter_uses_json_instead_of_copied_colors(monkeypatch: pytest.MonkeyPatch) -> None:
    app = QApplication.instance() or QApplication([])
    original = ui.theme()
    candidate = copy.deepcopy(original)
    candidate["accent"] = "#255580"
    candidate["firstLevelElements"] = "#16334D"
    with monkeypatch.context() as patch:
        patch.setattr(ui, "theme", lambda: candidate)
        ui.apply_theme(app)
        assert app.palette().color(QPalette.ColorRole.Highlight).name() == "#255580"
        assert "#16334D" in app.styleSheet()
        assert "#00338D" not in app.styleSheet().split("QFrame#navigation {", 1)[1].split("}", 1)[0]
    ui.apply_theme(app)
