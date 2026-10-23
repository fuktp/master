from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QDate, QLocale
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_tests.ui_helpers import settle
from orquestrador_app.config import save
from orquestrador_app.gui import MainWindow
from orquestrador_app.i18n import install_translation, set_language, tr
from orquestrador_app.paths import Paths
from orquestrador_app.sandbox import prepare_config
from tools.audit_localization import audit


def test_owned_caption_inventory_and_all_catalog_placeholders() -> None:
    assert audit()["errors"] == []


@pytest.mark.parametrize("locale", ["en", "es"])
def test_catalog_renders_dynamic_messages_without_mutating_user_values(locale: str) -> None:
    set_language(locale)
    try:
        values = json.loads(Path("orquestrador_app/locales.json").read_text())
        index = 0 if locale == "en" else 1
        for source, translations in values.items():
            assert tr(source) == translations[index]
        path = r"C:\Ação\Diária {1}\Relatório ãéí.exe"
        source = "Falha ao iniciar processo. Codigo nativo: 5\r\nExecutavel: " + path
        translated = tr(source)
        assert path in translated and "\r\n" in translated
        assert "Executavel:" not in translated
        assert tr("Rotina • Diária").endswith(" • Diária")
        assert tr("Diária: falhou. Abra o detalhe da execução.").startswith("Diária: ")
        assert "21 / 99" in tr("Arquivos copiados: 21 / 99")
        assert tr(path) == path
    finally:
        set_language("pt-BR")


@pytest.mark.parametrize(
    "locale,yes,month",
    [("pt-BR", "Sim", "outubro"), ("en", "Yes", "October"), ("es", "Sí", "octubre")],
)
def test_qt_standard_buttons_and_calendar_use_application_locale(
    locale: str, yes: str, month: str
) -> None:
    app = QApplication.instance() or QApplication([])
    install_translation(app, locale)
    try:
        dialog = QMessageBox()
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        button = dialog.button(QMessageBox.StandardButton.Yes)
        assert button.text().replace("&", "") == yes
        assert QLocale().monthName(QDate(2026, 10, 23).month()) == month
        dialog.close()
    finally:
        install_translation(app, "pt-BR")


def test_spanish_window_preserves_routine_names_and_raw_logs(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    config = prepare_config(paths)
    config.language = "es"
    config.routines[0].label = "Diária"
    save(paths, config)
    window = MainWindow(paths)
    settle(window)
    window.timer.stop()
    window.dev_panel.timer.stop()
    window.show()
    app.processEvents()
    try:
        assert window.panel.item(0, 0).text() == "Diária"
        assert window.routines.item(0, 0).text() == "Diária"
        assert window.language.currentData() == "es"
        window.set_status("Arquivos copiados: 21 / 99")
        assert window.status_label.text() == "Archivos copiados: 21 / 99"
        raw = "Log original: ação, relatório, início; Diária {1}"
        window.append_log(raw)
        assert raw in window.log.toPlainText()
    finally:
        window.tray.hide()
        window.exit_requested = True
        window.close()
        app.processEvents()
        install_translation(app, "pt-BR")


def test_running_monitor_follows_saved_language_without_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QSystemTrayIcon

    from orquestrador_app import agent
    from orquestrador_app.config import load

    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    config = prepare_config(paths)
    config.language = "en"
    for routine in config.routines:
        routine.enabled = False
    save(paths, config)
    trays = []

    def tray_factory(*args: object) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(*args)
        trays.append(tray)
        return tray

    monkeypatch.setattr(agent, "QSystemTrayIcon", tray_factory)
    monkeypatch.setattr(agent, "poll_seconds", lambda *args: 1)
    changed = False
    observed = False
    previous_quit_setting = app.quitOnLastWindowClosed()
    watcher = QTimer()

    def check() -> None:
        nonlocal changed, observed
        if not trays or not trays[0].contextMenu():
            return
        label = trays[0].contextMenu().actions()[0].text()
        if not changed and label == "Open CAIO":
            selected = load(paths)
            selected.language = "es"
            save(paths, selected)
            changed = True
        elif changed and label == "Abrir CAIO":
            observed = True
            app.quit()

    watcher.timeout.connect(check)
    watcher.start(20)
    deadline = QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(app.quit)
    deadline.start(5000)
    try:
        assert agent.run_agent(paths) == 0
        assert changed and observed
    finally:
        watcher.stop()
        app.setQuitOnLastWindowClosed(previous_quit_setting)
        deadline.stop()
        for tray in trays:
            tray.hide()
        install_translation(app, "pt-BR")
