"""Background observations, incremental log reader and bounded table model."""

from __future__ import annotations

import codecs
import datetime as dt
import os
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from .config import load
from .engine import Engine
from .files import Publisher
from .i18n import tr
from .monitor_status import monitor_state
from .paths import Paths
from .tasks import WindowsTasks


class LogTail:
    def __init__(self) -> None:
        self.file: Path | None = None
        self.offset = 0
        self.inode = 0
        self.decoder: codecs.IncrementalDecoder = codecs.getincrementaldecoder("utf-8-sig")(
            errors="strict"
        )

    def read(self, file: Path | None) -> dict[str, Any]:
        if file is None or not file.is_file():
            return {"text": "", "reset": False}
        stat = file.stat()
        reset = file != self.file or stat.st_ino != self.inode or stat.st_size < self.offset
        if reset:
            self.file, self.offset, self.inode = file, max(0, stat.st_size - 65536), stat.st_ino
            self.decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
        with file.open("rb") as stream:
            stream.seek(self.offset)
            data = stream.read(65536)
            self.offset = stream.tell()
        if reset and stat.st_size > 65536:
            # The bounded tail may begin in the middle of a UTF-8 character.
            while data and data[0] & 0xC0 == 0x80:
                data = data[1:]
        buffered = self.decoder.getstate()[0]
        try:
            text = self.decoder.decode(data)
        except UnicodeDecodeError:
            # Old Windows redirected logs used CP1252. Read them without rewriting the evidence.
            self.decoder = codecs.getincrementaldecoder("cp1252")(errors="replace")
            text = self.decoder.decode(buffered + data)
        return {
            "text": text,
            "reset": reset,
            "file": file.name,
            "more": self.offset < stat.st_size,
        }


class Observer:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.tail = LogTail()
        self.checked_at = 0.0
        self.task_checked_at = ""
        self.installed: bool | None = None
        self.task_error = ""
        self.engine: Engine | None = None

    def collect(
        self, *, log_run: str = "", history: dict[str, Any] | None = None, backups: bool = False
    ) -> dict[str, Any]:
        if log_run and (len(log_run) > 100 or any(c not in "0123456789abcdef-" for c in log_run)):
            raise ValueError("Identificador de execução inválido.")
        config = load(self.paths)
        if self.engine is None:
            self.engine = Engine(self.paths, config)
        engine = self.engine
        engine.config = config
        if os.name == "nt" and time.monotonic() - self.checked_at > 60:
            self.checked_at = time.monotonic()
            self.task_checked_at = dt.datetime.now(dt.timezone.utc).isoformat()
            try:
                if config.execution_profile == "portable_gui":
                    from .portable import task_status

                    report = task_status(self.paths)
                    self.installed = report["installed"]
                    if report["installed"] and not report["matches"]:
                        raise RuntimeError(
                            tr(
                                "A tarefa difere da configuração esperada. Confira os campos em Diagnóstico."
                            )
                        )
                else:
                    self.installed = bool(WindowsTasks(self.paths).export())
                self.task_error = ""
            except Exception as exc:
                self.installed = None
                self.task_error = str(exc)
        from .notifications import claim

        notifications = claim(engine.store)
        result: dict[str, Any] = {
            "config": config,
            "rows": engine.panel(),
            "monitor": monitor_state(
                self.paths, config, installed=self.installed, task_error=self.task_error
            ),
            "notifications": notifications,
            "log": self.tail.read(
                Path(config.logs) / (log_run + ".process.log") if log_run else None
            ),
        }
        result["monitor"]["task_checked_at"] = self.task_checked_at
        if history is not None:
            result["history"] = engine.store.history_page(**history)
        if backups:
            result["backups"] = Publisher(
                self.paths.root / "backups/reports", config.retention
            ).versions()
        return result


class HistoryModel(QAbstractTableModel):
    columns = ("started", "job", "status", "mode", "category", "batch", "id", "stage")
    labels = ("Início", "Rotina", "Estado", "Modo", "Categoria", "Lote", "Execução", "Etapa")

    def __init__(self, parent: Any = None):
        super().__init__(parent)
        self.rows: list[dict[str, Any]] = []
        self.names: dict[str, str] = {}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return tr(self.labels[section])
        return None

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        row = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return row["id"]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            key = self.columns[index.column()]
            value = row.get(key) or ""
            if key == "job":
                return self.names.get(value, value)
            from .i18n import display_value

            return display_value(str(value))
        return None

    def update(self, rows: list[dict[str, Any]], names: dict[str, str]) -> None:
        same = [r["id"] for r in rows] == [r["id"] for r in self.rows]
        old_names = self.names
        self.names = names
        if same:
            for i, (old, new) in enumerate(zip(self.rows, rows)):
                if old != new or old_names.get(new["job"]) != names.get(new["job"]):
                    self.rows[i] = new
                    self.dataChanged.emit(self.index(i, 0), self.index(i, len(self.columns) - 1))
        else:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()
