"""Integrated developer console: bounded, read-only observation of managed activity."""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import VERSION
from .config import load
from .i18n import display_value, tr
from .io import BusyError, Lock, read_json, sanitize
from .paths import Paths
from .processes import command, spawn
from .qt_tasks import Task
from .runtime import decode_log_bytes
from .store import Store
from .ui import FlowLayout, configure_table, set_cell
from .versioning import history

_cpu_samples: dict[tuple[int, float], tuple[float, float]] = {}


def lock_status(path: Path) -> str:
    try:
        with Lock(path):
            return "livre"
    except BusyError:
        return "em uso (lock do sistema operacional)"


def process_row(process: psutil.Process, role: str) -> dict[str, Any]:
    with process.oneshot():
        identity = (process.pid, process.create_time())
        clock = time.monotonic()
        times = process.cpu_times()
        total = times.user + times.system
        previous = _cpu_samples.get(identity)
        cpu = (
            round(100 * max(0, total - previous[1]) / (clock - previous[0]), 1)
            if previous and clock > previous[0]
            else None
        )
        if len(_cpu_samples) > 2000:
            _cpu_samples.clear()
        _cpu_samples[identity] = (clock, total)
        return {
            "pid": process.pid,
            "role": role,
            "name": process.name(),
            "status": process.status(),
            "rss_mb": round(process.memory_info().rss / 1024**2, 1),
            "cpu_percent": cpu,
            "created": dt.datetime.fromtimestamp(process.create_time())
            .astimezone()
            .isoformat(timespec="seconds"),
        }


def collect(paths: Paths, selected_log: str = "") -> dict[str, Any]:
    config = load(paths)
    store = Store(paths.database)
    runs = store.history(limit=100)
    with store.connect() as db:
        active = [
            dict(row)
            for row in db.execute(
                "SELECT id,job,batch,stage,checkpoint_at FROM runs WHERE status='running' ORDER BY started"
            )
        ]
        events = [
            dict(row) for row in db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 300")
        ]
    processes: dict[int, dict[str, Any]] = {}
    from .monitor_status import monitor_state

    monitor = monitor_state(paths, config)
    heartbeat = paths.root / "state/monitor-heartbeat.json"
    if heartbeat.is_file():
        identity_record = read_json(heartbeat)
        try:
            process = psutil.Process(identity_record["pid"])
            if abs(process.create_time() - identity_record["created"]) < 0.01:
                processes[process.pid] = process_row(process, "monitor")
        except (psutil.Error, KeyError):
            pass
    try:
        current = psutil.Process(os.getpid())
        processes[current.pid] = process_row(current, "interface/monitor atual")
    except psutil.Error:
        pass
    for event in events:
        if event["kind"] != "process":
            continue
        value = json.loads(event["detail"])
        try:
            process = psutil.Process(value["pid"])
            birth = value.get("created")
            if birth is None or abs(process.create_time() - birth) > 0.01:
                continue
            for item in [process, *process.children(recursive=True)]:
                processes[item.pid] = process_row(item, f"execução {event['run']}")
        except psutil.Error:
            continue
    folder = Path(config.logs).resolve()
    logs = sorted(
        (p.name for p in folder.glob("*.log*") if p.is_file() and not p.is_symlink()),
        key=lambda name: (folder / name).stat().st_mtime,
        reverse=True,
    )[:100]
    text = "Selecione um log gerenciado. Nenhum comando de terminal é necessário."
    if selected_log in logs:
        file = folder / selected_log
        with file.open("rb") as stream:
            stream.seek(max(0, file.stat().st_size - 131072))
            text = str(
                sanitize(decode_log_bytes(stream.read(), tail=stream.tell() > 131072), export=True)
            )
    pointer = paths.root / "installation.json"
    transaction = paths.root / "state/install-transaction.json"
    if (paths.root / "state/native-transaction.json").is_file():
        transaction = paths.root / "state/native-transaction.json"
    return {
        "observed_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "runtime": {
            "version": VERSION,
            "edition": "teste isolado" if config.test_mode else "desenvolvimento em código",
            "os": platform.platform(),
            "python_private": sys.version,
            "frozen": bool(getattr(sys, "frozen", False)),
            "executable": sys.executable,
            "data_root": str(paths.root),
            "pid": os.getpid(),
            "scheduling_paused": config.scheduling_paused,
            "execution_lock": lock_status(paths.lock),
            "maintenance_lock": lock_status(paths.maintenance_lock),
            "console_policy": "CREATE_NO_WINDOW; executável no subsistema gráfico Windows",
            "installation": read_json(pointer) if pointer.is_file() else "não instalada",
            "transaction": read_json(transaction) if transaction.is_file() else "nenhuma",
            "monitor": monitor,
            "active_queue": active,
            "cpu_method": "delta user+system / elapsed wall time; null until second sample; may exceed 100% with multiple cores",
        },
        "processes": list(processes.values()),
        "runs": runs,
        "events": events,
        "logs": logs,
        "log_text": text,
        "versions": history(paths),
    }


class DevPanel(QWidget):
    def __init__(self, paths: Paths, parent: QWidget | None = None):
        super().__init__(parent)
        self.paths = paths
        self.task: Task | None = None
        self.latest: dict[str, Any] = {}
        self.last_tick = time.perf_counter()
        self.largest_tick_gap = 0.0
        layout = QVBoxLayout(self)
        title = QLabel("Painel de Dev • observação interna sem terminal")
        title.setProperty("role", "section")
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                "Leitura em segundo plano. Processos e evidências pertencem a esta instalação. A exportação remove dados sensíveis."
            )
        )
        controls = FlowLayout()
        self.paused = QCheckBox("Pausar atualização da visualização")
        controls.addWidget(self.paused)
        self.refresh_button = QPushButton("Atualizar agora")
        self.refresh_button.clicked.connect(lambda: self.refresh(True))
        controls.addWidget(self.refresh_button)
        self.health_button = QPushButton("Autoteste isolado, sem rede")
        self.health_button.clicked.connect(self.health)
        controls.addWidget(self.health_button)
        export = QPushButton("Exportar diagnóstico sanitizado…")
        export.clicked.connect(self.export)
        controls.addWidget(export)
        layout.addLayout(controls)
        self.status = QLabel("Aguardando primeira leitura.")
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.runtime = self.text_tab("Runtime, instalação e locks")
        self.processes = self.table_tab(
            "Processos próprios",
            ["PID", "Origem", "Processo", "Estado", "RAM (MiB)", "CPU (%)", "Início"],
        )
        self.runs = self.table_tab(
            "Fila e execuções",
            ["Execução", "Lote", "Rotina", "Estado", "Etapa", "Tentativa", "Código"],
        )
        self.events = self.table_tab(
            "Eventos correlacionados", ["Seq.", "Data", "Execução", "Evento", "Evidência"]
        )
        logs_page = QWidget()
        logs_layout = QVBoxLayout(logs_page)
        self.log_choice = QComboBox()
        self.log_choice.currentTextChanged.connect(lambda _: self.refresh(True))
        logs_layout.addWidget(self.log_choice)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.document().setMaximumBlockCount(3000)
        logs_layout.addWidget(self.log_text)
        self.tabs.addTab(logs_page, "Logs ao vivo")
        self.versions = self.text_tab("Versionamento interno")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1500)

    def text_tab(self, label: str) -> QPlainTextEdit:
        widget = QPlainTextEdit()
        widget.setReadOnly(True)
        self.tabs.addTab(widget, label)
        return widget

    def table_tab(self, label: str, columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        configure_table(table)
        table.setWordWrap(False)
        self.tabs.addTab(table, label)
        return table

    def tick(self) -> None:
        now = time.perf_counter()
        self.largest_tick_gap = max(self.largest_tick_gap, now - self.last_tick)
        self.last_tick = now
        if self.isVisible() and not self.paused.isChecked():
            self.refresh()

    def refresh(self, force: bool = False) -> None:
        if self.task and self.task.isRunning():
            return
        selected = self.log_choice.currentText()
        self.start(lambda: collect(self.paths, selected), self.apply)

    def start(self, callback: Callable[[], Any], completed: Callable[[Any], None]) -> None:
        if self.task and self.task.isRunning():
            return
        self.task = Task(callback, self)
        self.task.done.connect(completed)
        self.task.failed.connect(lambda text: self.status.setText(tr(f"Leitura falhou: {text}")))
        self.task.start()

    @staticmethod
    def fill(table: QTableWidget, rows: list[list[Any]]) -> None:
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                set_cell(table, row, column, value)
        table.resizeColumnsToContents()

    def apply(self, value: dict[str, Any]) -> None:
        self.latest = value
        self.status.setText(
            tr("Leitura")
            + f": {display_value(value['observed_at'])} • "
            + str(len(value["processes"]))
            + " "
            + tr("processos")
            + " • "
            + str(len(value["events"]))
            + " "
            + tr("eventos")
        )
        self.runtime.setPlainText(json.dumps(value["runtime"], ensure_ascii=False, indent=2))
        self.fill(
            self.processes,
            [
                [
                    p[k]
                    for k in ("pid", "role", "name", "status", "rss_mb", "cpu_percent", "created")
                ]
                for p in value["processes"]
            ],
        )
        self.fill(
            self.runs,
            [
                [r.get(k) for k in ("id", "batch", "job", "status", "stage", "attempt", "code")]
                for r in value["runs"]
            ],
        )
        self.fill(
            self.events,
            [[e[k] for k in ("seq", "at", "run", "kind", "detail")] for e in value["events"]],
        )
        current = self.log_choice.currentText()
        self.log_choice.blockSignals(True)
        self.log_choice.clear()
        self.log_choice.addItems(value["logs"])
        if current in value["logs"]:
            self.log_choice.setCurrentText(current)
        self.log_choice.blockSignals(False)
        if self.log_text.toPlainText() != value["log_text"]:
            self.log_text.setPlainText(value["log_text"])
            bar = self.log_text.verticalScrollBar()
            bar.setValue(bar.maximum())
        self.versions.setPlainText(
            json.dumps(value["versions"], ensure_ascii=False, indent=2)
            if value["versions"]
            else "Nenhuma instalação registrada. O wizard cria manifestos com versão, data, SHA-256 e snapshot anterior. Não utiliza Git."
        )

    def health(self) -> None:
        if self.task and self.task.isRunning():
            self.status.setText(tr("Aguarde a leitura atual e tente novamente."))
            return
        report = self.paths.root / "logs/autoteste-interno.json"
        logfile = self.paths.root / "logs/autoteste-interno.log"

        def run() -> dict[str, Any]:
            report.unlink(missing_ok=True)
            with logfile.open("ab") as output:
                process = spawn(
                    command("--health-check", "--health-output", str(report)),
                    stdout=output,
                    stderr=output,
                )
                try:
                    code = process.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                    raise RuntimeError("Autoteste excedeu 180 segundos.") from None
            if code or not report.is_file():
                raise RuntimeError(f"Autoteste falhou (código {code}); veja autoteste-interno.log.")
            result = read_json(report)
            Store(self.paths.database).event(None, "dev_health_check", result)
            return result

        self.status.setText(tr("Autoteste em subprocesso oculto; nenhuma extração será iniciada."))
        self.start(
            run,
            lambda result: self.status.setText(
                tr(
                    f"Autoteste: {result.get('health')} • versão {result.get('version')} • sem rede."
                )
            ),
        )

    def export(self) -> None:
        name = QFileDialog.getSaveFileName(
            self,
            tr("Exportar diagnóstico sanitizado"),
            "diagnostico-dev.xlsx",
            tr("Excel (*.xlsx);;JSON (*.json)"),
            options=QFileDialog.Option.DontUseNativeDialog,
        )[0]
        if not name:
            return
        try:
            from .exporting import export_data

            self.start(
                lambda: export_data(Path(name), self.latest),
                lambda result: self.status.setText(str(result)),
            )
        except Exception as exc:
            QMessageBox.warning(self, tr("Exportação"), tr(str(exc)))

    def shutdown(self) -> None:
        self.timer.stop()
        if self.task and self.task.isRunning():
            self.task.wait(12000)
