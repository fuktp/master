"""Qt worker and VPN notice shared by tray and desktop, without importing MainWindow."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout, QWidget

from .i18n import tr
from .store import Store


class Task(QThread):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, callback: Callable[[], Any], parent: Any = None):
        super().__init__(parent)
        self.callback = callback

    def run(self) -> None:
        owner = threading.get_ident()
        signal = self.progress

        class Output(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                if record.thread == owner:
                    signal.emit(record.getMessage())

        output = Output()
        logger = logging.getLogger()
        logger.addHandler(output)
        try:
            self.done.emit(self.callback())
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            logger.removeHandler(output)


class VpnNotice(QDialog):
    def __init__(self, store: Store, run: str, message: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.store, self.run_id = store, run
        self.setWindowTitle("KWMS • Verifique a VPN")
        layout = QVBoxLayout(self)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.countdown = QLabel("Aguardando o próximo registro da execução…")
        self.read_task: Task | None = None
        layout.addWidget(self.countdown)
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.update_countdown)
        self.clock.start(1000)
        self.update_countdown()
        self.show()
        QApplication.alert(self, 15000)

    def update_countdown(self) -> None:
        if self.read_task and self.read_task.isRunning():
            return

        def read() -> Any:
            with self.store.connect() as db:
                row = db.execute(
                    "SELECT status,stage FROM runs WHERE id=?", (self.run_id,)
                ).fetchone()
                return dict(row) if row else None

        def loaded(row: Any) -> None:
            if not row or row["status"] != "running":
                self.clock.stop()
                self.close()
            else:
                self.countdown.setText(tr(row["stage"]))

        if self.read_task:
            self.read_task.deleteLater()
        self.read_task = Task(read, self)
        self.read_task.done.connect(loaded)
        self.read_task.failed.connect(lambda message: self.countdown.setText(tr(message)))
        self.read_task.start()
