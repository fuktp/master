"""Local, content-addressed script snapshots. Hashes identify versions, never grant permission."""

from __future__ import annotations

import dataclasses
import datetime as dt
import difflib
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .config import Config, Routine, save
from .io import Lock, atomic_json, digest, read_json, sanitize
from .paths import Paths
from .resources import script_path


def capture(paths: Paths, job: Routine) -> dict[str, Any]:
    source = script_path(job.script)
    if source.suffix.casefold() != ".py" or not source.is_file():
        raise ValueError("O script precisa ser um arquivo Python existente.")
    root = Path(job.package_root).resolve() if job.package_root else source.parent
    files = {source.name: source} if not job.package_root else package_files(root)
    if not source.resolve().is_relative_to(root):
        raise ValueError("Entrada fora da pasta do script.")
    entry = source.resolve().relative_to(root).as_posix()
    hashes = {name: digest(file) for name, file in files.items()}
    contract = sanitize(
        {
            k: getattr(job, k)
            for k in (
                "arguments",
                "options",
                "command",
                "target",
                "staged_output",
                "working_directory",
                "environment",
            )
        }
    )
    checksum = hashlib.sha256(
        json.dumps(
            {
                "files": hashes,
                "entry": entry,
                "contract": contract,
                "version": job.script_version,
                "notes": job.notes,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    folder = paths.root / "extras/versions" / job.id / checksum
    with Lock(paths.root / "state/scripts.lock"):
        folder.mkdir(parents=True, exist_ok=True)
        for name, file in files.items():
            target = folder / "files" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if digest(target) != hashes[name]:
                    raise ValueError("Snapshot corrompido; versão anterior preservada.")
            else:
                shutil.copy2(file, target)
                if digest(target) != hashes[name]:
                    raise ValueError("Arquivo mudou durante o snapshot; tente novamente.")
        metadata = folder / "version.json"
        if not metadata.is_file():
            atomic_json(
                metadata,
                {
                    "sha256": checksum,
                    "version": job.script_version or checksum[:12],
                    "declared_version": job.script_version,
                    "at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                    "source": str(source),
                    "size": sum(p.stat().st_size for p in files.values()),
                    "entry": entry,
                    "files": hashes,
                    "contract": contract,
                    "notes": job.notes,
                },
            )
        return dict(read_json(metadata))


def versions(paths: Paths, job: Routine) -> list[dict[str, Any]]:
    root = paths.root / "extras/versions" / job.id
    return sorted(
        (dict(read_json(p)) for p in root.glob("*/version.json")),
        key=lambda x: x["at"],
        reverse=True,
    )


def restore(paths: Paths, config: Config, job: Routine, checksum: str) -> None:
    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("Identificador de versão inválido.")
    with Lock(paths.maintenance_lock), Lock(paths.lock), Lock(paths.root / "state/config.lock"):
        capture(paths, job)
        folder = paths.root / "extras/versions" / job.id / checksum
        metadata = read_json(folder / "version.json")
        if "files" in metadata:
            contents = {
                "files": metadata["files"],
                "entry": metadata["entry"],
                "contract": metadata["contract"],
                "version": metadata.get("declared_version", ""),
                "notes": metadata.get("notes", ""),
            }
            if (
                hashlib.sha256(json.dumps(contents, sort_keys=True).encode()).hexdigest()
                != checksum
            ):
                raise ValueError("Metadados de snapshot divergentes.")
            if metadata["entry"] not in metadata["files"]:
                raise ValueError("Entrada ausente no snapshot.")
            for name, expected in metadata["files"].items():
                file = (folder / "files" / name).resolve()
                if (
                    not file.is_relative_to((folder / "files").resolve())
                    or file.is_symlink()
                    or digest(file) != expected
                ):
                    raise ValueError("Snapshot de pasta inválido.")
            source = folder / "files" / metadata["entry"]
        else:
            source = folder / "script.py"
            if digest(source) != checksum:
                raise ValueError("Snapshot de script inválido.")
        # A rollback never overwrites an external production source.
        active = paths.root / "extras/active" / job.id / str(uuid.uuid4())
        if "files" in metadata:
            shutil.copytree(folder / "files", active)
            target = active / metadata["entry"]
            job.package_root = str(active)
        else:
            target = active / "script.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target.with_suffix(".tmp"))
        target.with_suffix(".tmp").replace(target)
        job.script = str(target)
        job.script_version = metadata.get("declared_version", metadata["version"])
        save(paths, config)


def remove(paths: Paths, config: Config, identifier: str, purge: bool = False) -> None:
    if any(d.job == identifier for j in config.routines for d in j.dependencies):
        raise ValueError("Remova primeiro as dependências que apontam para esta rotina.")
    with Lock(paths.maintenance_lock), Lock(paths.lock), Lock(paths.root / "state/config.lock"):
        job = config.job(identifier)
        if script_path(job.script).is_file():
            capture(paths, job)
        atomic_json(
            paths.root / "extras/trash" / (identifier + "-" + str(uuid.uuid4()) + ".json"),
            {
                "owner": "caio-routine-trash-v1",
                "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "routine": dataclasses.asdict(job),
            },
        )
        config.routines.remove(job)
        save(paths, config)
        if purge:
            # Only application-managed copies; never delete a source file or report.
            for category in ("versions", "active"):
                folder = paths.root / "extras" / category / identifier
                if folder.is_symlink():
                    raise ValueError("Link inesperado na área de scripts.")
                if folder.is_dir():
                    shutil.rmtree(folder)


def package_files(root: Path) -> dict[str, Path]:
    excluded = {".git", ".venv", "__pycache__", "profiles", "downloads", "logs", "node_modules"}
    files: dict[str, Path] = {}
    total = 0
    for file in root.rglob("*"):
        relative = file.relative_to(root)
        if any(p in excluded for p in relative.parts):
            continue
        if file.is_symlink():
            raise ValueError("Links não são aceitos em pastas de script.")
        if not file.is_file():
            continue
        if file.name.casefold().startswith(".env") or file.suffix.casefold() in {
            ".pem",
            ".key",
            ".pfx",
            ".har",
        }:
            continue
        total += file.stat().st_size
        if len(files) >= 2000 or total > 100_000_000:
            raise ValueError(
                "Pasta excede 2.000 arquivos ou 100 MB; escolha somente os recursos necessários."
            )
        files[relative.as_posix()] = file
    return files


def check_dependencies(job: Routine) -> dict[str, Any]:
    import ast
    import importlib.util
    import sys

    root = Path(job.package_root) if job.package_root else script_path(job.script).parent
    files = (
        package_files(root)
        if job.package_root
        else {script_path(job.script).name: script_path(job.script)}
    )
    local = {Path(name).parts[0].split(".")[0] for name in files}
    imports: set[str] = set()
    for file in files.values():
        if file.suffix == ".py":
            for node in ast.walk(
                ast.parse(file.read_text(encoding="utf-8-sig"), filename=file.name)
            ):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imports.add(node.module.split(".")[0])
    missing = []
    for name in sorted(imports - local - sys.stdlib_module_names):
        try:
            found = importlib.util.find_spec(name) is not None
        except (ValueError, ImportError):
            found = False
        if not found:
            missing.append(name)
    return {
        "missing": missing,
        "imports": sorted(imports),
        "executed": False,
        "limitation": "Imports dinâmicos e extensões nativas exigem teste no runtime alvo.",
    }


def compare_versions(paths: Paths, job: Routine, before: str, after: str) -> dict[str, Any]:
    def read(version: str) -> tuple[dict[str, Any], str]:
        if len(version) != 64 or any(c not in "0123456789abcdef" for c in version):
            raise ValueError("Versão inválida.")
        folder = paths.root / "extras/versions" / job.id / version
        data = read_json(folder / "version.json")
        file = folder / "files" / data["entry"] if "entry" in data else folder / "script.py"
        if file.is_symlink() or not file.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Arquivo de versão fora do snapshot.")
        return data, file.read_text(encoding="utf-8-sig")

    a, code_a = read(before)
    b, code_b = read(after)
    return {
        "source_diff": "".join(
            difflib.unified_diff(
                code_a.splitlines(True),
                code_b.splitlines(True),
                fromfile=before[:12],
                tofile=after[:12],
            )
        ),
        "before": a,
        "after": b,
        "changed_files": [
            name
            for name in sorted(set(a.get("files", {})) | set(b.get("files", {})))
            if a.get("files", {}).get(name) != b.get("files", {}).get(name)
        ],
    }


def restore_registration(paths: Paths, config: Config, record: Path) -> None:
    area = paths.root / "extras/trash"
    if record.is_symlink() or not record.resolve().is_relative_to(area.resolve()):
        raise ValueError("Cadastro fora da lixeira gerenciada.")
    item = read_json(record)
    if item.get("owner") != "caio-routine-trash-v1":
        raise ValueError("Cadastro não reconhecido.")
    from .config import from_dict, to_dict

    data = to_dict(config)
    if any(j["id"] == item["routine"]["id"] for j in data["routines"]):
        raise ValueError(
            "Identificador já cadastrado; restauração não substitui rotinas existentes."
        )
    restored = dict(item["routine"])
    restored["enabled"] = False
    data["routines"].append(restored)
    candidate = from_dict(data)
    with Lock(paths.maintenance_lock), Lock(paths.lock):
        save(paths, candidate, expected=getattr(config, "_source_revision", None))
    record.unlink()
