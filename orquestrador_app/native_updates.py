"""Explicitly configured HTTPS feed and local ZIP updates; no invented server."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from packaging.version import Version

from . import VERSION
from .io import atomic_json, digest, read_json
from .native_install import PACKAGE_OWNER, verify_release
from .paths import Paths
from .processes import spawn
from .resources import source_root

MAX_PACKAGE = 1_500_000_000


def https_host(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("Use um endereço HTTPS sem credenciais na URL.")
    return parsed.netloc.casefold()


def prepare_zip(paths: Paths, archive: Path, expected_hash: str = "") -> Path:
    if expected_hash and digest(archive) != expected_hash:
        raise ValueError("O hash do ZIP diverge do feed aprovado.")
    stage = paths.root / "cache/updates" / str(uuid.uuid4())
    stage.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as z:
            entries = z.infolist()
            if len(entries) > 22000 or sum(x.file_size for x in entries) > MAX_PACKAGE:
                raise ValueError("Pacote excede o limite de tamanho/arquivos.")
            if shutil.disk_usage(stage).free < sum(x.file_size for x in entries) * 4:
                raise ValueError("Espaço insuficiente para preparar atualização e backup.")
            names: set[str] = set()
            for item in entries:
                name = item.filename
                target = stage / name
                normalized = name.casefold().rstrip("/")
                if (
                    not name
                    or "\\" in name
                    or ":" in name
                    or name.startswith("/")
                    or ".." in Path(name).parts
                    or not target.resolve().is_relative_to(stage.resolve())
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                    or normalized in names
                ):
                    raise ValueError("Caminho inseguro/duplicado no ZIP de atualização.")
                names.add(normalized)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(item) as src, target.open("wb") as out:
                        shutil.copyfileobj(src, out)
        manifests = [p for p in stage.glob("*/payload/release.json")]
        if (stage / "payload/release.json").is_file():
            manifests.append(stage / "payload/release.json")
        if len(manifests) != 1:
            raise ValueError("ZIP não contém exatamente um pacote completo do Orquestrador.")
        root = manifests[0].parents[1]
        verify_release(root / "payload")
        # Execute only the verified native scripts inside the manifested payload.
        return root
    except Exception:
        shutil.rmtree(stage)
        raise


def check_feed(paths: Paths, url: str) -> dict[str, Any]:
    host = https_host(url)
    with requests.get(url, timeout=(10, 30), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("O feed exige resposta HTTPS 200 sem redirecionamento.")
        data = b""
        for chunk in response.iter_content(8192):
            data += chunk
            if len(data) > 128_000:
                raise ValueError("Feed excede o limite.")
    import json

    feed = json.loads(data)
    if feed.get("owner") != PACKAGE_OWNER or https_host(feed["package_url"]) != host:
        raise ValueError("Feed inválido ou pacote em outro servidor; revise a origem.")
    checksum = feed.get("sha256", "")
    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("Feed sem SHA-256 válido.")
    if Version(feed["version"]) <= Version(VERSION):
        return {"available": False, "version": feed["version"]}
    cache = paths.root / "cache/updates"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (checksum + ".zip")
    if not archive.is_file() or digest(archive) != checksum:
        temporary = archive.with_suffix(".partial")
        hashed = hashlib.sha256()
        try:
            with requests.get(
                feed["package_url"], timeout=(10, 60), stream=True, allow_redirects=False
            ) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("O pacote exige resposta HTTPS 200 sem redirecionamento.")
                total = 0
                with temporary.open("wb") as out:
                    for chunk in response.iter_content(1024 * 1024):
                        total += len(chunk)
                        if total > MAX_PACKAGE:
                            raise ValueError("Download excede o limite do pacote.")
                        hashed.update(chunk)
                        out.write(chunk)
            if hashed.hexdigest() != checksum:
                raise ValueError("Download interrompido ou integridade divergente.")
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    prepared = cache / (checksum + "-ready.json")
    root: Path | None = None
    if prepared.is_file():
        candidate = Path(read_json(prepared)["root"])
        if candidate.resolve().is_relative_to(cache.resolve()):
            try:
                verify_release(candidate / "payload")
                root = candidate
            except (OSError, ValueError):
                pass
    if root is None:
        root = prepare_zip(paths, archive, checksum)
        atomic_json(prepared, {"root": str(root), "sha256": checksum})
    record = verify_release(root / "payload")
    if record["version"] != feed["version"]:
        raise ValueError("Versão do pacote diverge do feed.")
    return {
        "available": True,
        "version": record["version"],
        "package": str(root),
        "sha256": checksum,
    }


def open_wizard(paths: Paths, package: Path | None = None, backup: Path | None = None) -> None:
    if sys.platform != "win32":
        raise RuntimeError("O wizard WinForms exige Windows.")
    native = package / "payload/native" if package else source_root().parent / "native"
    script = native / ("Update.ps1" if package or backup else "wizard.ps1")
    if not script.is_file():
        raise ValueError("Wizard nativo não encontrado nesta distribuição.")
    import psutil

    start = psutil.Process().create_time()
    arguments = [
        str(Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"),
        "-NoProfile",
        "-NonInteractive",
        "-STA",
        "-ExecutionPolicy",
        "Bypass",
        "-WindowStyle",
        "Hidden",
        "-File",
        str(script),
        "-DataRoot",
        str(paths.root),
        "-OwnerPid",
        str(os.getpid()),
        "-OwnerStarted",
        str(start),
    ]
    if package:
        arguments += ["-PackageRoot", str(package)]
    if backup:
        arguments += ["-Backup", str(backup)]
    spawn(arguments, cwd=str(script.parent))


def is_native(paths: Paths) -> bool:
    pointer = paths.root / "installation.json"
    return pointer.is_file() and read_json(pointer).get("distribution") == "native-scripts"
