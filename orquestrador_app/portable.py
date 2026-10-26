"""Graphical scripts on the original, IT-provisioned interpreter; no installer."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import logging
import os
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .config import KNOWN, Config, from_dict, load, save, to_dict
from .io import BusyError, Lock, atomic_json, digest, read_json
from .paths import Paths
from .resources import source_root
from .sandbox import check_location, prepare_config
from .tasks import NS, WindowsTasks, compare_tasks, current_user, xml

PROFILE = "portable_gui"


def prepare(paths: Paths, source: Config | None = None) -> Config:
    config = prepare_config(paths, source)
    config.execution_profile = PROFILE
    config.install_root = str(source_root())
    config.driver_options = {}  # Mirrors and executable resolvers are not configurable here.
    for job in config.routines:
        if job.id in KNOWN:
            job.script = "bundle:scripts/" + job.id + ".py"
            job.script_version = ""
            job.package_root = ""
    return config


def validate_root(paths: Paths) -> None:
    root, code = paths.root.resolve(), source_root().resolve()
    if root.is_relative_to(code) or code.is_relative_to(root):
        raise ValueError("Separe a pasta dos dados da pasta dos scripts.")
    marker = root / "portable.json"
    if marker.is_file() and read_json(marker).get("profile") == PROFILE:
        if root.is_symlink() or root == Path(root.anchor) or root == Path.home():
            raise ValueError("Escolha uma pasta exclusiva para os dados do CAIO.")
    else:
        check_location(root)


def import_preview(source: Path, paths: Paths) -> dict[str, Any]:
    if source.resolve() == paths.root.resolve():
        raise ValueError("Escolha uma origem diferente da pasta dos dados.")
    config = prepare(paths, from_dict(read_json(source / "config.json")))
    history = source / "state/history.sqlite3"
    return {
        "source": str(source.resolve()),
        "configuration_sha256": digest(source / "config.json"),
        "history": str(history) if history.is_file() else "",
        "configuration": to_dict(config),
        "browser_profile_copied": False,
        "original_files_modified": False,
    }


def initialize(paths: Paths, config: Config, source: Path | None = None) -> None:
    validate_root(paths)
    if config.execution_profile != PROFILE:
        raise ValueError("Perfil de execução inválido.")
    paths.ensure()
    with Lock(paths.maintenance_lock), Lock(paths.lock):
        if paths.config.exists() or paths.database.exists():
            raise ValueError("A pasta dos dados já está configurada.")
        # SQLite's backup API includes committed WAL contents; the origin is read-only.
        history = source / "state/history.sqlite3" if source else None
        try:
            atomic_json(
                paths.root / "portable.json", {"profile": PROFILE, "code": str(source_root())}
            )
            if history and history.is_file():
                with sqlite3.connect(history.resolve().as_uri() + "?mode=ro", uri=True) as origin:
                    with sqlite3.connect(paths.database) as target:
                        deadline = time.monotonic() + 120

                        def progress(status: int, remaining: int, total: int) -> None:
                            if time.monotonic() > deadline:
                                raise TimeoutError(
                                    "A cópia do histórico excedeu dois minutos. Feche a origem e tente novamente."
                                )

                        origin.backup(target, pages=256, progress=progress, sleep=0.1)
                        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise ValueError("Falha do SQLite.")
            from .store import Store

            Store(paths.database)
            save(paths, config, expected="")
        except Exception:
            if not paths.config.exists():
                paths.database.unlink(missing_ok=True)
            raise


def task_name(paths: Paths) -> str:
    key = hashlib.sha256(str(paths.root.resolve()).encode()).hexdigest()[:12]
    return rf"\CAIO-Scripts-{key}"


def task_xml(paths: Paths, *, enabled: bool = False) -> str:
    root = ET.fromstring(xml(Path(sys.executable), paths, current_user()))

    def set_value(name: str, value: str) -> None:
        node = root.find("/".join("{" + NS + "}" + part for part in name.split("/")))
        assert node is not None
        node.text = value

    set_value("RegistrationInfo/URI", task_name(paths))
    set_value(
        "RegistrationInfo/Description", "CAIO scripts: one check per minute; no resident agent."
    )
    triggers = root.find(f"{{{NS}}}Triggers")
    assert triggers is not None
    logon = triggers.find(f"{{{NS}}}LogonTrigger")
    assert logon is not None
    triggers.remove(logon)
    set_value(
        "Actions/Exec/Arguments",
        subprocess.list2cmdline(
            ["-B", str(source_root() / "caio_jobs.py"), "--data-root", str(paths.root), "--tick"]
        ),
    )
    set_value("Actions/Exec/WorkingDirectory", str(source_root()))
    set_value("Settings/Enabled", str(enabled).lower())
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + ET.tostring(root, encoding="unicode")


def export_task(paths: Paths, target: Path) -> dict[str, Any]:
    target.write_text(task_xml(paths), encoding="utf-16")
    return {"task": task_name(paths), "xml": str(target), "enabled": False}


def task_status(paths: Paths) -> dict[str, Any]:
    actual = WindowsTasks(paths).export(task_name(paths))
    return {"task": task_name(paths), **compare_tasks(actual, task_xml(paths, enabled=True))}


def tick(paths: Paths) -> int:
    from .engine import Engine

    state = paths.root / "state/scheduler-check.json"
    try:
        with Lock(paths.root / "state/scheduler-tick.lock"):
            atomic_json(
                state, {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "state": "checking"}
            )
            try:
                # Do not grow the execution history for idle minute checks.
                with Lock(paths.lock):
                    pass
                engine = Engine(paths)
                engine.monitor()
                due = any(row["status"] != "not_eligible" for row in engine.preview(scheduled=True))
                results = engine.run(scheduled=True) if due else []
                code = int(any(row.get("status") == "failed" for row in results))
                status = "failed" if code else "complete"
            except BusyError:
                code, status = 0, "busy"
            except Exception as exc:
                atomic_json(
                    state,
                    {
                        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "state": "failed",
                        "error": str(exc),
                    },
                )
                raise
            atomic_json(
                state, {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "state": status}
            )
            return code
    except BusyError:
        return 0


def main(*, graphical: bool = False, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CAIO graphical scripts")
    parser.add_argument("--data-root", type=Path, required=False)
    if not graphical:
        parser.add_argument("--health-check", action="store_true")
        parser.add_argument("--health-output", type=Path)
        parser.add_argument("--tick", action="store_true")
        parser.add_argument("--export-task", type=Path)
        parser.add_argument("--shortcut", type=Path)
        parser.add_argument("--worker")
        parser.add_argument("--run-id", default="")
        parser.add_argument("--mode", default="manual", choices=["manual", "scheduled"])
        parser.add_argument("--action", default="run", choices=["run", "login", "replace", "merge"])
        parser.add_argument("--input", type=Path)
        parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args(argv)
    os.environ.update(CAIO_EXECUTION_PROFILE=PROFILE, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if os.name == "nt" and (
        sys.version_info[:3] != (3, 13, 5)
        or sys.maxsize <= 2**32
        or Path(sys.executable).name.casefold() != "pythonw.exe"
    ):
        raise RuntimeError("Use CPython 3.13.5 x64 e o pythonw.exe original aprovado pela TI.")
    if graphical:
        from .portable_gui import launch

        return launch(Paths.user(args.data_root) if args.data_root else None)
    if args.health_check:
        result = health_check()
        if args.health_output:
            atomic_json(args.health_output, result)
        return 0
    if not args.data_root:
        parser.error("--data-root is required")
    paths = Paths.user(args.data_root)
    if args.shortcut:
        create_shortcut(paths, args.shortcut)
        return 0
    config = load(paths)
    if config.execution_profile != PROFILE:
        raise ValueError("Abra esta configuração pelo modo correspondente.")
    from .__main__ import configure_logging
    from .runtime import capture_windowed_streams

    configure_logging(paths)
    capture_windowed_streams(paths.root / "logs")
    if args.export_task:
        export_task(paths, args.export_task)
        return 0
    if args.worker:
        from .worker import execute

        return execute(
            paths, args.worker, args.run_id, args.mode, args.action, args.input, args.snapshot
        )
    if args.tick:
        return tick(paths)
    parser.error("Choose --tick, --export-task, --shortcut or --worker")
    return 2


def create_shortcut(paths: Paths, target: Path) -> None:
    """Explicit IT provisioning only. No AppID, relaunch metadata or registry writes."""
    if os.name != "nt" or Path(sys.executable).name.casefold() != "pythonw.exe":
        raise RuntimeError("Use o pythonw.exe original aprovado pela TI.")
    if target.suffix.casefold() != ".lnk" or target.exists():
        raise ValueError("Escolha um novo atalho .lnk.")
    import win32com.client

    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(target.resolve()))
    link.TargetPath = sys.executable
    link.Arguments = subprocess.list2cmdline(
        ["-B", str(source_root() / "caio_gui.py"), "--data-root", str(paths.root)]
    )
    link.WorkingDirectory = str(source_root())
    link.IconLocation = str(source_root() / "assets/caio.ico") + ",0"
    link.Description = "CAIO"
    link.Save()


def report_failure(error: Exception, *, graphical: bool) -> int:
    logging.getLogger(__name__).exception("CAIO scripts failed")
    if graphical:
        from .i18n import tr

        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, "CAIO", tr(str(error)))
            app.processEvents()
        except ImportError:
            if os.name != "nt":
                raise
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                tr(
                    "Não foi possível abrir a interface. Peça à TI para conferir o Python e as dependências aprovadas."
                )
                + "\n"
                + str(error),
                "CAIO",
                0x10,
            )
    elif sys.stderr:
        print(str(error), file=sys.stderr)
    return 1


def health_check() -> dict[str, Any]:
    import importlib
    import tempfile

    from . import VERSION
    from .worker import module_for

    for name in ("PySide6.QtWidgets", "pandas", "requests", "selenium", "openpyxl"):
        importlib.import_module(name)
    from PySide6.QtWidgets import QApplication

    from .gui import MainWindow
    from .store import Store

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="caio-scripts-health-") as folder:
        paths = Paths.user(folder)
        paths.ensure()
        config = prepare(paths)
        save(paths, config)
        store = Store(paths.database)
        with store.connect() as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for job in config.routines:
            module_for(job).build_parser()
        window = MainWindow(paths, observe=False)
        app.processEvents()
        tabs = window.tabs.count()
        window.exit_requested = True
        window.close()
        assert tabs == 6
    return {
        "version": VERSION,
        "health": "ok",
        "profile": PROFILE,
        "ui_tabs": tabs,
        "extractors": len(config.routines),
        "network_used": False,
        "windows_executed": os.name == "nt",
    }
