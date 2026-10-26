"""First-use forms and the existing Qt shell, without installation side effects."""

from __future__ import annotations

import copy
import os
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
)

from .config import load
from .editors import SettingsEditor
from .gui import MainWindow, button, path_field
from .i18n import install_translation, tr
from .io import BusyError, Lock
from .paths import Paths
from .portable import import_preview, initialize, prepare, validate_root
from .qt_tasks import Task
from .ui import apply_theme, explain, icon


class SetupDialog(QDialog):
    def __init__(self, paths: Paths):
        super().__init__()
        self.paths = paths
        self.source: Path | None = None
        self.config = prepare(paths)
        self.task: Task | None = None
        self.setWindowIcon(icon())
        self.setWindowTitle(tr("Preparar dados do CAIO"))
        self.resize(880, 740)
        self.setMinimumSize(640, 520)
        layout = QVBoxLayout(self)
        self.language = QComboBox()
        for label, code in [("Português (Brasil)", "pt-BR"), ("English", "en"), ("Español", "es")]:
            self.language.addItem(label, code)
        self.language.setAccessibleName(tr("Idioma"))
        layout.addWidget(self.language)
        self.intro = explain("")
        layout.addWidget(self.intro)
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        layout.addWidget(self.form_scroll, 1)
        self.editor = SettingsEditor(self.config, path_field)
        self.form_scroll.setWidget(self.editor)
        self.import_button = button("Importar configuração e histórico…", self.import_data, layout)
        self.error = explain("")
        self.error.setProperty("severity", "error")
        layout.addWidget(self.error)
        self.dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.dialog_buttons.accepted.connect(self.commit)
        self.dialog_buttons.rejected.connect(self.reject)
        layout.addWidget(self.dialog_buttons)
        self.language.currentIndexChanged.connect(self.change_language)
        self.change_language()

    def change_language(self) -> None:
        self.config = self.editor.value(validating=False)
        self.config.language = self.language.currentData()
        install_translation(QApplication.instance(), self.config.language)
        self.setWindowTitle(tr("Preparar dados do CAIO"))
        self.intro.setText(
            tr(
                "Escolha e-mail e destinos. Esta etapa salva somente seus dados; não instala programas nem tarefas."
            )
            + "\n"
            + str(self.paths.root)
        )
        previous = self.form_scroll.takeWidget()
        self.editor = SettingsEditor(self.config, path_field)
        self.form_scroll.setWidget(self.editor)
        if previous:
            previous.deleteLater()
        self.import_button.setText(tr("Importar configuração e histórico…"))
        self.dialog_buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Salvar"))
        self.dialog_buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancelar"))

    def import_data(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("Selecionar origem da configuração"),
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not folder:
            return
        try:
            preview = import_preview(Path(folder), self.paths)
            dialog = QDialog(self)
            dialog.setWindowTitle(tr("Revisar importação"))
            dialog.resize(800, 620)
            layout = QVBoxLayout(dialog)
            layout.addWidget(
                explain(
                    "Os originais serão preservados. Revise os novos destinos. O perfil do navegador não será copiado."
                )
            )
            content = QPlainTextEdit()
            content.setReadOnly(True)
            import json

            content.setPlainText(json.dumps(preview, ensure_ascii=False, indent=2))
            layout.addWidget(content)
            actions = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            actions.accepted.connect(dialog.accept)
            actions.rejected.connect(dialog.reject)
            layout.addWidget(actions)
            if dialog.exec():
                from .config import from_dict

                self.config = from_dict(preview["configuration"])
                self.config.language = self.language.currentData()
                self.source = Path(folder)
                previous = self.form_scroll.takeWidget()
                self.editor = SettingsEditor(self.config, path_field)
                self.form_scroll.setWidget(self.editor)
                if previous:
                    previous.deleteLater()
                self.error.clear()
        except Exception as exc:
            self.error.setText(tr(str(exc)))

    def commit(self) -> None:
        try:
            config = self.editor.value()
            config.language = self.language.currentData()
            self.error.clear()
            self.dialog_buttons.setEnabled(False)
            self.import_button.setEnabled(False)
            self.language.setEnabled(False)
            self.editor.setEnabled(False)
            self.task = Task(
                lambda: initialize(self.paths, copy.deepcopy(config), self.source), self
            )
            self.task.done.connect(lambda _: self.accept())
            self.task.failed.connect(self.failed)
            self.task.start()
        except Exception as exc:
            self.error.setText(tr(str(exc)))

    def failed(self, error: str) -> None:
        self.error.setText(tr(error))
        for widget in (self.dialog_buttons, self.import_button, self.language, self.editor):
            widget.setEnabled(True)

    def reject(self) -> None:
        if not self.task or not self.task.isRunning():
            super().reject()


def launch(paths: Paths | None) -> int:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication(sys.argv[:1])
    apply_theme(app)
    app.setApplicationName("CAIO")
    app.setWindowIcon(icon())
    if os.name == "nt" and (
        sys.version_info[:3] != (3, 13, 5)
        or struct.calcsize("P") != 8
        or Path(sys.executable).name.casefold() != "pythonw.exe"
    ):
        raise RuntimeError("Use CPython 3.13.5 x64 e o pythonw.exe original aprovado pela TI.")
    if paths is None:
        folder = QFileDialog.getExistingDirectory(
            None,
            tr("Selecionar pasta dos dados do CAIO"),
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not folder:
            return 0
        paths = Paths.user(folder)
    if not paths.config.is_file():
        validate_root(paths)
        dialog = SetupDialog(paths)
        if not dialog.exec():
            return 0
    config = load(paths)
    if config.execution_profile != "portable_gui":
        raise ValueError("Importe os dados anteriores para uma nova pasta pelo primeiro acesso.")
    install_translation(app, config.language)
    from .__main__ import configure_logging
    from .runtime import capture_windowed_streams
    from .store import Store

    configure_logging(paths)
    capture_windowed_streams(paths.root / "logs")
    Store(paths.database)
    try:
        with Lock(paths.root / "state/interface.lock"):
            window = MainWindow(paths)
            window.show()

            # Own execution lock prevents replacing a driver used by a running routine.
            def driver_check() -> object:
                from .portable_driver import check

                with Lock(paths.lock):
                    return check(paths, load(paths), repair=True)

            QTimer.singleShot(0, lambda: window.background(driver_check))
            return app.exec()
    except BusyError:
        QMessageBox.information(
            None, "CAIO", tr("A interface já está aberta para esta pasta de dados.")
        )
        return 0
