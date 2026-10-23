"""Standalone, themed confirmation shared by the root launcher and Windows Apps settings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .config import load
from .i18n import install_translation, tr
from .io import BusyError
from .native_install import NativeInstaller
from .paths import Paths
from .qt_tasks import Task
from .ui import apply_theme, explain, icon


class UninstallDialog(QDialog):
    def __init__(self, paths: Paths):
        super().__init__()
        self.paths = paths
        self.task: Task | None = None
        self.setWindowTitle(tr("Desinstalar CAIO"))
        self.setWindowIcon(icon())
        self.resize(640, 390)
        layout = QVBoxLayout(self)
        heading = QLabel(tr("Desinstalar CAIO"))
        heading.setProperty("role", "title")
        layout.addWidget(heading)
        location = explain(str(paths.root))
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(location)
        layout.addWidget(
            explain(
                "A tarefa do monitor, os atalhos e o registro desta instalação no Windows serão removidos. O monitor próprio será encerrado; execuções em andamento precisam terminar antes."
            )
        )
        layout.addWidget(
            explain(
                "Configurações, relatórios, histórico, scripts e backups serão preservados. Uma cópia da versão atual será guardada para recuperação."
            )
        )
        self.remove_files = QCheckBox(tr("Remover os arquivos verificados do aplicativo após sair"))
        self.remove_files.setChecked(True)
        self.remove_files.setAccessibleDescription(
            tr("Remove somente as versões gerenciadas em app/versions. Dados e backups permanecem.")
        )
        layout.addWidget(self.remove_files)
        self.status = explain("")
        self.status.setMinimumHeight(60)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        layout.addLayout(actions)
        self.cancel = QPushButton(tr("Cancelar"))
        self.cancel.clicked.connect(self.reject)
        actions.addWidget(self.cancel)
        self.apply = QPushButton(tr("Desinstalar"))
        self.apply.setProperty("intent", "danger")
        self.apply.clicked.connect(self.start)
        actions.addWidget(self.apply)
        self.cancel.setDefault(True)
        self.cancel.setFocus()

    def reject(self) -> None:
        if not self.task or not self.task.isRunning():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.task and self.task.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)

    def start(self) -> None:
        if self.task and self.task.isRunning():
            return
        self.apply.setEnabled(False)
        self.cancel.setEnabled(False)
        self.remove_files.setEnabled(False)
        self.progress.setRange(0, 0)
        self.status.setText(tr("Preparando desinstalação…"))
        remove_files = self.remove_files.isChecked()
        task = Task(
            lambda: NativeInstaller(self.paths).uninstall(
                remove_program_files=remove_files, progress=task.progress.emit
            ),
            self,
        )
        self.task = task
        task.progress.connect(lambda message: self.status.setText(tr(message)))
        task.done.connect(lambda result: self.accept())
        task.failed.connect(self.failed)
        task.start()

    def failed(self, error: str) -> None:
        self.progress.setRange(0, 1)
        self.status.setProperty("severity", "error")
        self.status.setText(
            tr("Feche a interface CAIO e aguarde as rotinas em execução antes de tentar novamente.")
            if error == str(BusyError("Recurso em uso por outra execução."))
            else tr(error)
        )
        self.apply.setEnabled(True)
        self.cancel.setEnabled(True)
        self.remove_files.setEnabled(True)


def run(paths: Paths) -> int:
    current = QApplication.instance()
    if current is not None and not isinstance(current, QApplication):
        raise RuntimeError("O desinstalador exige QApplication.")
    app = current if current is not None else QApplication([])
    apply_theme(app)
    if paths.config.is_file():
        install_translation(app, load(paths).language)
    from .windows_identity import set_process_identity, set_window_identity

    set_process_identity(paths)
    dialog = UninstallDialog(paths)
    if app.platformName() == "windows":
        set_window_identity(dialog, paths)
    dialog.exec()
    if dialog.task:
        dialog.task.wait(15000)
    return 0 if dialog.result() == QDialog.DialogCode.Accepted else 3
