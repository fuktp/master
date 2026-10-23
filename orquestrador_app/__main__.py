from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import TEST_EDITION, VERSION
from .config import defaults, load, save, to_dict
from .io import digest, read_json
from .paths import Paths
from .resources import source_root


def health_check() -> dict[str, Any]:
    import importlib

    from .store import Store
    from .worker import module_for

    for name in ("PySide6.QtWidgets", "pandas", "requests", "selenium", "openpyxl"):
        importlib.import_module(name)

    with tempfile.TemporaryDirectory(prefix="orquestrador-health-") as temporary:
        paths = Paths.user(temporary)
        paths.ensure()
        config = defaults(paths, source_root())
        save(paths, config)
        assert load(paths).schema_version == 2
        store = Store(paths.database)
        with store.connect() as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Falha do SQLite.")
        for job in config.routines:
            module_for(job).build_parser()
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from .gui import InstallWizard, MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow(paths, observe=False)
        wizard = InstallWizard(paths, config)
        app.processEvents()
        ui_tabs, wizard_pages = window.tabs.count(), len(wizard.pageIds())
        if ui_tabs != 6 or wizard_pages != 8:
            raise RuntimeError("Componentes obrigatórios da interface não foram construídos.")
        wizard.reject()
        window.timer.stop()
        window.tray.hide()
        window.exit_requested = True
        window.close()
        manifest = source_root() / "payload-manifest.json"
        if getattr(sys, "frozen", False) and not manifest.is_file():
            raise RuntimeError("Manifesto interno ausente.")
        if manifest.is_file():
            for name, expected in read_json(manifest)["files"].items():
                path = (source_root() / name).resolve()
                if not path.is_relative_to(source_root().resolve()) or digest(path) != expected:
                    raise RuntimeError("Integridade do payload interno divergiu.")
        return {
            "version": VERSION,
            "health": "ok",
            "extractors": len(config.routines),
            "runtime": sys.version,
            "network_used": False,
            "ui_tabs": ui_tabs,
            "wizard_pages": wizard_pages,
            "libraries": {
                name: importlib.metadata.version(name)
                for name in ("PySide6", "pandas", "selenium", "requests", "openpyxl")
            },
        }


def configure_logging(paths: Paths) -> None:
    path = paths.root / "logs/desktop.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(
                path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
            )
        ],
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    result: Any
    parser = argparse.ArgumentParser(
        description="Orquestrador • interface, agendamento e manutenção integrados"
    )
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--health-output", type=Path)
    parser.add_argument("--agent", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--worker")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-detail", default="")
    parser.add_argument("--mode", default="manual", choices=["manual", "scheduled"])
    parser.add_argument("--action", default="run", choices=["run", "login", "replace", "merge"])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--job", action="append")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "command", nargs="?", choices=["run", "login", "list-jobs", "doctor", "configure-schedules"]
    )
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args(argv)
    if args.health_check:
        try:
            result = health_check()
        except Exception as exc:
            if args.health_output:
                from .io import atomic_json

                atomic_json(
                    args.health_output, {"health": "failed", "error": str(exc), "version": VERSION}
                )
            raise
        if args.health_output:
            from .io import atomic_json

            atomic_json(args.health_output, result)
        if sys.stdout:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.data_root:
        paths = Paths.user(args.data_root)
    elif TEST_EDITION:
        from .sandbox import locate

        paths = locate()
    else:
        paths = Paths.user()
    if (
        TEST_EDITION
        and (getattr(sys, "frozen", False) or (source_root().parent / "release.json").is_file())
        and paths.config.is_file()
        and not load(paths).test_mode
    ):
        raise ValueError("A edição de teste não abre configurações da instalação original.")
    paths.ensure()
    configure_logging(paths)
    from .runtime import capture_windowed_streams

    capture_windowed_streams(paths.root / "logs")
    if args.uninstall:
        from .uninstall_gui import run

        return run(paths)
    if args.worker:
        from .worker import execute

        return execute(
            paths, args.worker, args.run_id, args.mode, args.action, args.input, args.snapshot
        )
    if args.agent:
        from .agent import run_agent

        return run_agent(paths)
    if args.scheduled or args.command in {"run", "login", "list-jobs", "doctor"}:
        if not paths.config.is_file():
            raise ValueError("Configuração inicial necessária; abra o wizard do aplicativo.")
        from .driver import diagnose
        from .engine import Engine

        if args.command == "list-jobs":
            result = to_dict(load(paths))
        elif args.command == "doctor":
            result = diagnose(paths, load(paths), repair=args.repair)
        else:
            engine = Engine(paths)
            result = engine.run(
                args.job,
                scheduled=args.scheduled,
                force=args.force,
                simulate=args.dry_run,
                login=args.command == "login",
            )
            engine.monitor()
        if sys.stdout:
            print(json.dumps(result, ensure_ascii=False, default=str))
        return int(isinstance(result, list) and any(r.get("status") == "failed" for r in result))
    from .gui import launch
    from .native_updates import is_native

    if is_native(paths):
        from .io import BusyError, Lock, atomic_json

        ownership = Lock(paths.root / "state/interface.lock")
        try:
            ownership.__enter__()
        except BusyError:
            atomic_json(paths.root / "state/open-interface.json", {"run": args.run_detail})
            return 0
        try:
            return launch(paths, args.run_detail)
        finally:
            ownership.__exit__()
    return launch(paths, args.run_detail)


def entry() -> int:
    try:
        from .runtime import install_console_policy

        install_console_policy()
        return main()
    except Exception as exc:
        logging.exception("Falha no aplicativo")
        if sys.stderr:
            print(str(exc), file=sys.stderr)
        elif sys.platform == "win32" and "--health-check" not in sys.argv:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, str(exc), "Orquestrador", 0x10)
        return 2


if __name__ == "__main__":
    raise SystemExit(entry())
