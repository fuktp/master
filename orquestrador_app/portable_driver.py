"""Bounded Microsoft-only updates; verify signer and version before executing a driver."""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import Config
from .driver import guard
from .io import Lock, atomic_json, digest, read_json
from .paths import Paths

ORIGIN = "https://msedgedriver.microsoft.com"
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_DRIVER = 200 * 1024 * 1024


def version(text: str) -> tuple[int, ...]:
    value = text.strip().lstrip("\ufeff")
    if not re.fullmatch(r"\d{1,5}(?:\.\d{1,5}){3}", value):
        raise ValueError("Resposta de versão do EdgeDriver inválida.")
    return tuple(map(int, value.split(".")))


def official(url: str) -> None:
    value = urlsplit(url)
    if (
        value.scheme != "https"
        or value.hostname != "msedgedriver.microsoft.com"
        or value.port not in (None, 443)
        or value.username
        or value.password
    ):
        raise ValueError("Origem do EdgeDriver não autorizada.")


class MicrosoftRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        official(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, maximum: int) -> bytes:
    official(url)
    # Default TLS/OS trust and proxy settings; never turn certificate validation off.
    opener = urllib.request.build_opener(MicrosoftRedirect())
    with opener.open(
        urllib.request.Request(url, headers={"User-Agent": "CAIO-scripts"}), timeout=30
    ) as response:
        official(response.geturl())
        if int(response.headers.get("Content-Length", "0")) > maximum:
            raise ValueError("Download do EdgeDriver excede o limite permitido.")
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Download do EdgeDriver excede o limite permitido.")
    return data


def signed_version(instance: Any, path: Path) -> tuple[int, ...]:
    if os.name != "nt":
        raise RuntimeError("A assinatura Microsoft precisa ser verificada no Windows.")
    # Fixed read-only PowerShell; file path is data in an environment variable, never code.
    # Get-AuthenticodeSignature checks Windows trust without starting the target executable.
    output = instance._powershell_output(
        "$ErrorActionPreference='Stop'; "
        "$s=Get-AuthenticodeSignature -LiteralPath $env:CAIO_DRIVER_FILE; "
        "[pscustomobject]@{status=[string]$s.Status;subject=[string]$s.SignerCertificate.Subject;"
        "version=(Get-Item -LiteralPath $env:CAIO_DRIVER_FILE).VersionInfo.ProductVersion} | ConvertTo-Json -Compress",
        {"CAIO_DRIVER_FILE": str(path)},
    )
    value = json.loads(output)
    microsoft = re.search(r"(?:^|,\s*)CN=Microsoft Corporation(?:,|$)", value.get("subject", ""))
    if value.get("status") != "Valid" or not microsoft:
        raise RuntimeError(
            "Assinatura Microsoft do EdgeDriver não aprovada. Encaminhe o diagnóstico à TI."
        )
    return version(value["version"])


def stage(instance: Any, payload: bytes, expected: tuple[int, ...], folder: Path) -> Path:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > 100 or sum(item.file_size for item in entries) > MAX_DRIVER:
            raise ValueError("ZIP do EdgeDriver excede o limite permitido.")
        candidates = [
            item
            for item in entries
            if Path(item.filename.replace("\\", "/")).name == "msedgedriver.exe"
        ]
        if len(candidates) != 1 or candidates[0].file_size > MAX_DRIVER:
            raise ValueError("ZIP do EdgeDriver inválido.")
        candidate = folder / "msedgedriver.exe"
        # Read only the expected member, under its fixed basename; read() checks CRC.
        candidate.write_bytes(archive.read(candidates[0]))
    if signed_version(instance, candidate) != expected:
        raise ValueError("A versão assinada do EdgeDriver diverge do download solicitado.")
    # No downloaded executable is started until both trust and signed version are checked.
    if tuple(instance.driver_version(candidate)) != expected:
        raise ValueError("A versão executada do EdgeDriver diverge da versão assinada.")
    return candidate


def metadata(path: Path) -> dict[str, Any]:
    try:
        value = read_json(path)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def check(
    paths: Paths, config: Config, *, repair: bool, force: bool = False, test_session: bool = False
) -> dict[str, Any]:
    with Lock(paths.root / "state/driver.lock"):
        state_file = paths.root / "state/portable-driver.json"
        try:
            return _check(paths, config, repair=repair, force=force, test_session=test_session)
        except Exception as exc:
            previous = metadata(state_file)
            atomic_json(
                state_file,
                {
                    **previous,
                    "status": "error",
                    "error": str(exc),
                    "attempted_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            )
            raise


def _check(
    paths: Paths, config: Config, *, repair: bool, force: bool, test_session: bool
) -> dict[str, Any]:
    instance = guard(paths, config)
    policies = instance.edge_policy_status()
    if any(value == 2 for value in policies.values()):
        raise RuntimeError("O WebDriver está bloqueado por política. Encaminhe o diagnóstico à TI.")
    edge = tuple(instance.edge_version(instance.detect_edge_binary()))
    target = Path(config.driver)
    expected_target = paths.root / "cache/driver/msedgedriver.exe"
    if target.resolve() != expected_target.resolve():
        raise ValueError("Use o EdgeDriver gerenciado na pasta dos dados.")
    current = signed_version(instance, target) if target.is_file() else None
    compatible = current is not None and current[:3] == edge[:3]
    state_file = paths.root / "state/portable-driver.json"
    state = metadata(state_file)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        fresh = 0 <= (now - dt.datetime.fromisoformat(state["checked_at"])).total_seconds() < 86400
    except (KeyError, ValueError, TypeError):
        fresh = False
    edge_text = ".".join(map(str, edge))
    cached = fresh and state.get("edge_version") == edge_text and state.get("status") == "ready"
    if repair and (force or not cached or not compatible):
        raw = fetch(f"{ORIGIN}/LATEST_RELEASE_{edge[0]}_WINDOWS", 1024)
        text = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        latest = version(text)
        # Microsoft's major channel can already refer to a newer Edge build.
        choices = [edge, *([latest] if latest[:3] == edge[:3] else [])]
        selected = max([*choices, *([current] if compatible and current else [])])
        if not compatible or (current and current < selected):
            selected_text = ".".join(map(str, selected))
            payload = fetch(f"{ORIGIN}/{selected_text}/edgedriver_win64.zip", MAX_ARCHIVE)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="stage-", dir=target.parent) as directory:
                candidate = stage(instance, payload, selected, Path(directory))
                if target.is_file():
                    backup = target.parent / "previous" / digest(target) / "msedgedriver.exe"
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                os.replace(candidate, target)
            current, compatible = selected, True
        state = {"checked_at": now.isoformat(), "edge_version": edge_text, "source": ORIGIN}
    if not compatible:
        raise RuntimeError("EdgeDriver ausente ou incompatível. Use Verificar novamente.")
    result = {
        **state,
        "status": "ready",
        "edge_version": edge_text,
        "driver_version": ".".join(map(str, current or ())),
        "driver_path": str(target),
        "sha256": digest(target),
        "authenticode": "Microsoft / Valid",
        "compatible": True,
        "metadata_cached": bool(cached and not force),
    }
    if test_session:
        # No alternate resolver or repair on policy/session failure.
        result["session"] = instance.test_session()
    atomic_json(state_file, result)
    return result
