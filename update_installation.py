"""Atualiza os arquivos do pacote preservando a configuração e extratores adicionais."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Any

from automation_schedule import atomic_json
from pipefy_orchestrator import RunLock, load_settings


DEFAULT_INSTALL_DIR = r"C:\Users\chailer\OneDrive - KPMG\BR - CAIO 2-1 Gestão - Dashboard\Testes - PBi\extraction"
CONFIG_NAME = "pipefy_orchestrator.config.json"


def merge_config(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(existing)
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
    preferences = merged.setdefault("job_schedules", {})
    for name, values in incoming.get("job_schedules", {}).items():
        preferences.setdefault(name, copy.deepcopy(values))
    jobs = merged.setdefault("jobs", [])
    by_name = {str(item["name"]).casefold(): item for item in jobs}
    for item in incoming.get("jobs", []):
        if item["name"].casefold() not in by_name:
            jobs.append(copy.deepcopy(item))
    merged["schedule_setup_completed"] = False
    return merged


def update_installation(source: Path, target: Path) -> Path:
    source, target = source.resolve(), target.expanduser().resolve()
    if source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Extraia a atualização em uma pasta separada da instalação e execute Atualizar_Instalacao.cmd.")
    incoming = json.loads((source / CONFIG_NAME).read_text(encoding="utf-8-sig"))
    config_path = target / CONFIG_NAME
    existing = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    merged = merge_config(existing, incoming)
    runtime = load_settings(config_path).runtime_dir if existing else target / ".pipefy_orchestrator"
    backup = runtime / "package_backups" / ("v1.3.0-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    with RunLock(runtime / "orchestrator.lock"):
        if existing:
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(config_path, backup / CONFIG_NAME)
        allowed = {".py", ".ps1", ".cmd", ".md", ".txt"}
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            relative = path.relative_to(source)
            if len(relative.parts) > 1 and relative.parts[0] not in ("scripts", "tests"):
                continue
            if "__pycache__" in relative.parts:
                continue
            destination = target / relative
            if not destination.resolve().is_relative_to(target):
                raise ValueError(f"Destino inválido: {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_file():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            temporary = destination.with_name(f".{destination.name}.{os.getpid()}.update")
            try:
                shutil.copy2(path, temporary)
                os.replace(temporary, destination)
            finally:
                temporary.unlink(missing_ok=True)
        atomic_json(config_path, merged)
    return backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Atualiza Pipefy e adiciona KWMS sem apagar extratores extras.")
    parser.add_argument("--target", type=Path, default=Path(DEFAULT_INSTALL_DIR))
    args = parser.parse_args()
    try:
        backup = update_installation(Path(__file__).resolve().parent, args.target)
    except Exception as exc:
        print(f"Falha na atualização: {exc}")
        return 1
    print(f"Pacote atualizado em: {args.target}")
    print(f"Backup dos arquivos anteriores: {backup}")
    print("Agora execute Instalar_Automacao_Pipefy.cmd na pasta extraction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
