"""Read-only previews and explicit operations on managed application data."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .config import Config, Routine, portable
from .files import Publisher, xlsx_content
from .io import Lock, atomic_json, digest, sanitize
from .paths import Paths
from .resources import script_path
from .script_versions import package_files
from .store import Store


def file_info(file: Path) -> dict[str, Any]:
    if not file.is_file():
        return {"exists": False, "file": str(file)}
    stat = file.stat()
    return {
        "exists": True,
        "file": str(file),
        "size": stat.st_size,
        "modified": dt.datetime.fromtimestamp(stat.st_mtime, dt.timezone.utc).isoformat(),
        "sha256": digest(file),
    }


def publication_preview(config: Config, job: Routine, source: Path) -> dict[str, Any]:
    if not job.target:
        raise ValueError("Defina o destino desta rotina antes de publicar.")
    xlsx_content(source)
    from .worker import module_for

    module = module_for(job)
    validators = {
        "pipefy_clientes_tool_edge": "validate_clients_workbook",
        "pipefy_procedimentos_tool_edge": "validate_procedures_workbook",
        "pipefy_status_atms_tool_edge": "validate_atms_workbook",
        "kwms_alocacoes_tool_edge": "validate_workbook",
    }
    if job.id in validators:
        validator = getattr(module, validators[job.id])
        if job.id.startswith("kwms"):
            validator(source)
        else:
            validator(
                source,
                sheet=str(config.events.get("sheet", "0")),
                header_row=int(config.events.get("header_row", 0)),
                allow_empty=False,
            )
    if job.id == "pipefy_eventos_tool_edge":
        frame = module.read_report(
            source, str(config.events["sheet"]), int(config.events["header_row"])
        )
        keys = [module.EXPORT_TO_HISTORY.get(k, k) for k in config.events["keys"]]
        for key in keys:
            if key not in frame.columns:
                raise ValueError("Chave ausente: " + key)
            values = frame[key].map(module._normalize_key)
            if any(
                not str(value).strip() or str(value).casefold() in {"nan", "none", "nat"}
                for value in values
            ):
                raise ValueError("Chave de Eventos ausente ou inválida: " + key)
    target = Path(job.target)
    parent = target.parent
    return {
        "source": file_info(source),
        "target": file_info(target),
        "validation": "passed; revalidated at commit",
        "destination_state": "local"
        if parent.is_dir() and os.access(parent, os.W_OK)
        else "unavailable",
        "external_sync": "not verified",
        "operation": "merge" if job.id == "pipefy_eventos_tool_edge" else "replace",
        "events_keys": config.events["keys"] if job.id == "pipefy_eventos_tool_edge" else [],
        "creates_backup": target.exists(),
    }


def restoration_preview(publisher: Publisher, identifier: str) -> dict[str, Any]:
    record = next((r for r in publisher.versions() if r["id"] == identifier), None)
    if not record:
        raise ValueError("Backup não encontrado.")
    content = publisher.validate_version(record)
    current = Path(record["target"])
    return {
        "current": file_info(current),
        "backup": {**record, "verified_file": str(content)},
        "identical": current.is_file() and digest(current) == record["sha256"],
        "differences_available": "metadata and hash; contents are not assumed equivalent",
        "preserves_current_before_restore": True,
    }


def quarantine(
    paths: Paths, source: Path, reason: str, run: str, area: Path | None = None
) -> dict[str, Any]:
    area = area or paths.root / "downloads"
    if (
        not area.resolve().is_relative_to(paths.root.resolve())
        or source.is_symlink()
        or not source.resolve().is_relative_to(area.resolve())
    ):
        raise ValueError("Somente downloads gerenciados podem ir para rejeitados.")
    identifier = str(uuid.uuid4())
    folder = paths.root / "rejected" / identifier
    folder.mkdir(parents=True)
    target = folder / source.name
    shutil.copy2(source, target)
    if digest(target) != digest(source):
        raise ValueError("Falha ao preservar arquivo rejeitado.")
    record = {
        "owner": "caio-rejected-v1",
        "run": run,
        "reason": reason,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "file": str(target),
        "sha256": digest(target),
    }
    atomic_json(folder / "record.json", record)
    return record


def storage_preview(paths: Paths, config: Config, now: float | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now().timestamp()
    roots = {
        "report_backups": paths.root / "backups/reports",
        "application_versions": paths.root / "app/versions",
        "script_versions": paths.root / "extras/versions",
        "logs": Path(config.logs),
        "temporaries": Path(config.downloads),
        "rejected": paths.root / "rejected",
    }
    with Store(paths.database).connect() as db:
        owned_runs = {r[0] for r in db.execute("SELECT id FROM runs")}
    sizes, candidates = {}, []
    for kind, root in roots.items():
        total = 0
        for file in root.rglob("*"):
            if (
                file.is_symlink()
                or not file.is_file()
                or not file.resolve().is_relative_to(paths.root.resolve())
            ):
                continue
            stat = file.stat()
            total += stat.st_size
            # Only owned run-* temporary files and the product's own log naming contracts.
            own_temp = kind == "temporaries" and file.relative_to(root).parts[0].startswith("run-")
            own_log = kind == "logs" and (
                bool(re.fullmatch(r"desktop\.log(?:\.\d+)?", file.name))
                or (
                    file.name.split(".")[0] in owned_runs
                    and bool(re.search(r"\.(?:process\.)?log(?:\.\d+)?$", file.name))
                )
            )
            days = int(config.maintenance["temporary_days" if own_temp else "log_days"])
            if (own_temp or own_log) and stat.st_mtime < now - days * 86400:
                candidates.append({**file_info(file), "kind": kind, "mtime_ns": stat.st_mtime_ns})
        sizes[kind] = total
    sizes["reports"] = sum(
        p.stat().st_size
        for p in {Path(j.target) for j in config.routines if j.target}
        if p.is_file()
    )
    return {
        "usage_bytes": sizes,
        "candidates": candidates,
        "automatic": False,
        "report_retention": config.retention,
        "protected": "report backups, application versions, script versions, rejected files and unmanaged files are not deleted by this action",
    }


def clean_previewed(paths: Paths, preview: dict[str, Any]) -> list[str]:
    removed = []
    with Lock(paths.maintenance_lock), Lock(paths.lock):
        for item in preview["candidates"]:
            file = Path(item["file"])
            if file.is_symlink() or not file.resolve().is_relative_to(paths.root.resolve()):
                raise ValueError("Limpeza fora do diretório gerenciado recusada.")
            if file.stat().st_mtime_ns != item["mtime_ns"] or digest(file) != item["sha256"]:
                raise ValueError("Arquivo mudou após a prévia; refaça a revisão.")
        for item in preview["candidates"]:
            Path(item["file"]).unlink()
            removed.append(item["file"])
    return removed


def export_routine_preview(
    config: Config, job: Routine, selected: list[str] | None = None
) -> dict[str, Any]:
    root = Path(job.package_root) if job.package_root else script_path(job.script).parent
    files = (
        package_files(root)
        if job.package_root
        else {script_path(job.script).name: script_path(job.script)}
    )
    chosen = set(selected) if selected is not None else set(files)
    if chosen - set(files):
        raise ValueError("Arquivo fora da pasta revisada.")
    inventory, rejected = [], []
    for name in sorted(chosen):
        file = files[name]
        if file.suffix.casefold() in {
            ".json",
            ".ini",
            ".cfg",
            ".yaml",
            ".yml",
            ".txt",
            ".toml",
            ".py",
        }:
            text = file.read_text(encoding="utf-8-sig")
            structured_secret = False
            if file.suffix.casefold() == ".json":
                try:
                    obj = json.loads(text)
                    structured_secret = sanitize(obj) != obj
                except ValueError:
                    pass
            if (
                structured_secret
                or sanitize(text, export=False) != text
                or re.search(
                    r"""(?im)["']?(?:password|secret|token|api_key)["']?\s*[:=]\s*["']?[^\s"']+""",
                    text,
                )
            ):
                rejected.append(name)
                continue
        inventory.append({"name": name, **file_info(file)})
    data = next(j for j in portable(config)["routines"] if j["id"] == job.id)
    return {
        "routine": sanitize(data, export=True),
        "files": inventory,
        "excluded_possible_secrets": rejected,
        "machine_paths_excluded": True,
        "profiles_excluded": True,
    }


def export_routine(target: Path, preview: dict[str, Any]) -> None:
    if preview.get("excluded_possible_secrets"):
        raise ValueError(
            "Revise os arquivos sinalizados; exportação cancelada para não transportar segredos."
        )
    for item in preview["files"]:
        if digest(Path(item["file"])) != item["sha256"]:
            raise ValueError("Arquivo mudou depois da prévia.")
    temporary = target.with_name(target.name + "." + str(uuid.uuid4()) + ".tmp")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "routine.json", json.dumps(preview["routine"], ensure_ascii=False, indent=2)
            )
            for item in preview["files"]:
                archive.write(item["file"], "files/" + item["name"])
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def support_preview(
    store: Store, *, start: str = "", end: str = "", jobs: list[str] | None = None
) -> dict[str, Any]:
    data = []
    page = 0
    while True:
        result = store.history_page(start=start, end=end, page=page, size=200)
        for row in result["rows"]:
            if jobs and row["job"] not in jobs:
                continue
            data.append({**row, "events": store.details(row["id"])})
        if (page + 1) * 200 >= result["total"]:
            break
        page += 1
    return sanitize(
        {"runs": data, "period": {"start": start, "end": end}, "network_used": False}, export=True
    )
