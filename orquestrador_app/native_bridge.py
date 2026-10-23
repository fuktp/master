"""JSON protocol for the PowerShell UI; no corporate connections during setup."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from . import VERSION
from .config import (
    Routine,
    Schedule,
    from_dict,
    load,
    preset_days,
    script_identifier,
    to_dict,
    validate,
)
from .io import atomic_json, read_json
from .native_install import NativeInstaller, check_windows_hosts, verify_release
from .paths import Paths, identity, onedrives
from .sandbox import check_location, prepare_config, validate_isolation


def preview(root: Path) -> dict[str, Any]:
    paths = check_location(root.resolve())
    config = load(paths) if paths.config.is_file() else prepare_config(paths)
    if not paths.config.is_file():
        config.scheduling_paused = False
        # Seed only new wizard configurations; saved and legacy calendars stay intact.
        for routine in config.routines:
            routine.schedule.days = preset_days(
                routine.schedule.frequency, routine.schedule.weekday
            )
            if routine.schedule.frequency == "weekly":
                routine.expected_hours = len(routine.schedule.days) * 24
    validate_isolation(paths, config)
    pointer = paths.root / "installation.json"
    return {
        "version": VERSION,
        "config": to_dict(config),
        "identity": identity(),
        "onedrives": onedrives(),
        "current": read_json(pointer) if pointer.is_file() else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--cancel", type=Path)
    args = parser.parse_args(argv)
    args.events.parent.mkdir(parents=True, exist_ok=True)

    def progress(message: str) -> None:
        with args.events.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "stage": message},
                    ensure_ascii=False,
                )
                + "\n"
            )

    try:
        from .runtime import install_console_policy

        install_console_policy()
        request = read_json(args.request)
        paths = Paths.user(request["data_root"])
        action = request["action"]
        installer = NativeInstaller(paths)
        if action == "preview":
            value = preview(paths.root)
        elif action == "recover":
            value = {"recovery": installer.recover()}
        elif action == "add_script":
            config = from_dict(request["config"])
            source = Path(request["script"])
            if not source.is_file() or source.suffix.casefold() != ".py":
                raise ValueError("Selecione um arquivo Python existente.")
            identifier = script_identifier(source)
            if any(j.id == identifier for j in config.routines):
                raise ValueError("Rotina já cadastrada; use Editar para trocar o script.")
            config.routines.append(
                Routine(
                    id=identifier,
                    label=source.stem,
                    script=str(source),
                    origin="cadastro no wizard",
                    enabled=False,
                    requires_browser=False,
                    command="",
                    order=max((j.order for j in config.routines), default=-1) + 1,
                    schedule=Schedule(days=preset_days("daily")),
                )
            )
            validate(config)
            value = {"config": to_dict(config)}
        elif action == "health":
            from .__main__ import health_check

            progress("Verificando a integridade dos arquivos do pacote")
            verify_release(Path(request["payload"]))
            import sys

            if sys.platform == "win32":
                progress("Verificando execução dos hosts CAIO antes de copiar o runtime")
                check_windows_hosts(Path(request["payload"]))
            progress("Verificando Python, bibliotecas, SQLite e interface; sem rede")
            value = health_check()
            progress("Etapa anterior concluída com sucesso.")
        elif action in {"install", "repair", "update"}:
            recovery = installer.recover()
            if recovery:
                progress(recovery)
            if "config" in request:
                config = from_dict(request["config"])
            else:
                config = load(paths) if paths.config.is_file() else prepare_config(paths)
            validate(config)
            validate_isolation(paths, config)
            source = Path(request["payload"])
            record = verify_release(source)

            def cancel() -> bool:
                return bool(args.cancel and args.cancel.is_file())

            launcher = installer.install(source, config, progress, cancelled=cancel)
            value = {"launcher": str(launcher), "version": record["version"], "status": "committed"}
        elif action == "rollback":
            installer.rollback(Path(request["backup"]))
            value = {"status": "rolled_back"}
        else:
            raise ValueError("Ação nativa desconhecida.")
        atomic_json(args.result, {"ok": True, "pid": os.getpid(), "result": value})
        return 0
    except Exception as exc:
        progress(str(exc))
        atomic_json(args.result, {"ok": False, "error": str(exc), "type": type(exc).__name__})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
