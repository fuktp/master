#!/usr/bin/env python3
"""Orquestrador das extrações Pipefy com proteção de Edge WebDriver.

O módulo usa apenas a biblioteca padrão durante a orquestração. Selenium é
carregado somente nas operações de diagnóstico, reparo e teste do driver.
"""

from __future__ import annotations

import argparse
import ast
import collections
import contextlib
import ctypes
import dataclasses
import datetime as dt
import hashlib
import io
import json
import logging
import logging.handlers
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from automation_schedule import (
    Schedule, ScheduleError, atomic_json, configure_schedules, due_reason,
    parse_schedule, read_state,
)

APP_VERSION = "1.3.0"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+\.\d+)(?!\d)")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
WINDOWS_ENV_RE = re.compile(r"%([^%]+)%")
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")

DRIVER_ADAPTER_SOURCE = '''\
"""Forca os extratores Pipefy a usar o EdgeDriver gerenciado.

Este modulo e carregado automaticamente pelo Python por meio de PYTHONPATH.
Ele nao altera os arquivos-fonte dos extratores.
"""

from __future__ import annotations

import os


DRIVER_ENV_NAMES = (
    "PIPEFY_EDGE_DRIVER_PATH",
    "PIPEFY_DRIVER_BINARY",
    "MSEDGEDRIVER_PATH",
    "EDGE_DRIVER_PATH",
    "SELENIUM_EDGE_DRIVER",
)


def _managed_driver() -> str:
    for name in DRIVER_ENV_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _patch_edge_service() -> None:
    try:
        from selenium.webdriver.edge.service import Service
    except ImportError:
        return

    original_init = Service.__init__
    if getattr(original_init, "_pipefy_managed_driver", False):
        return

    def managed_init(self, *args, **kwargs):
        driver = _managed_driver()
        if driver:
            if args:
                args = (driver, *args[1:])
            else:
                kwargs["executable_path"] = driver
        return original_init(self, *args, **kwargs)

    managed_init._pipefy_managed_driver = True
    Service.__init__ = managed_init
    os.environ["PIPEFY_DRIVER_ADAPTER_LOADED"] = "1"


_patch_edge_service()
'''

DRIVER_ERROR_MARKERS = (
    "this version of microsoft edge webdriver only supports",
    "this version of msedgedriver only supports",
    "unable to obtain driver for microsoftedge",
    "unable to obtain driver for microsoft edge",
    "msedgedriver.exe não encontrado",
    "msedgedriver v150 ou superior não encontrado",
)

PROFILE_ERROR_MARKERS = (
    "cannot parse internal json template",
    "user data directory is already in use",
    "o perfil dedicado está em uso",
    "devtoolsactiveport",
)


class OrchestratorError(RuntimeError):
    """Erro operacional esperado e exibível sem traceback."""


@dataclasses.dataclass(frozen=True)
class DriverSettings:
    edge_binary: Path | None
    managed_path: Path
    selenium_cache: Path
    driver_mirror_url: str = "https://msedgedriver.microsoft.com"
    auto_repair: bool = True
    verify_authenticode: bool = True
    session_test: bool = True
    session_test_headless: bool = True
    manager_timeout_seconds: int = 300
    keep_backups: int = 3
    force_managed_driver_for_jobs: bool = True
    adapt_script_driver_paths: bool = True


@dataclasses.dataclass(frozen=True)
class Job:
    name: str
    script: Path
    working_directory: Path
    options: tuple[str, ...]
    command: str
    command_arguments: tuple[str, ...]
    log_file: Path
    timeout_minutes: int = 45
    retries: int = 1
    retry_delay_seconds: int = 30
    enabled: bool = True
    environment: Mapping[str, str] = dataclasses.field(default_factory=dict)
    schedule: Schedule = dataclasses.field(default_factory=Schedule)
    skip_exit_codes: tuple[int, ...] = ()


@dataclasses.dataclass(frozen=True)
class Settings:
    config_path: Path
    project_root: Path
    output_dir: Path
    python_executable: str
    runtime_dir: Path
    logs_dir: Path
    orchestration_log: Path
    inter_job_delay_seconds: int
    continue_on_error: bool
    check_driver_before_each_job: bool
    driver: DriverSettings
    jobs: tuple[Job, ...]
    schedules: tuple[str, ...]


@dataclasses.dataclass
class JobResult:
    name: str
    status: str
    exit_code: int | None
    attempts: int
    started_at: str
    finished_at: str
    elapsed_seconds: float
    command: list[str]
    error: str | None = None


def parse_version(text: str) -> tuple[int, int, int, int]:
    match = VERSION_RE.search(text or "")
    if not match:
        raise OrchestratorError(f"Versão não identificada na saída: {text!r}")
    return tuple(int(part) for part in match.group(1).split("."))  # type: ignore[return-value]


def format_version(version: Sequence[int] | None) -> str:
    return ".".join(str(part) for part in version) if version else "não encontrada"


def versions_compatible(
    browser: Sequence[int] | None, driver: Sequence[int] | None
) -> bool:
    """A Microsoft exige igualdade dos três primeiros componentes."""
    return bool(browser and driver and tuple(browser[:3]) == tuple(driver[:3]))


def contains_driver_error(lines: Iterable[str]) -> bool:
    text = "\n".join(lines).casefold()
    return any(marker in text for marker in DRIVER_ERROR_MARKERS)


def contains_profile_error(lines: Iterable[str]) -> bool:
    text = "\n".join(lines).casefold()
    return any(marker in text for marker in PROFILE_ERROR_MARKERS)


def is_driver_path_literal(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    lowered = candidate.casefold()
    if not lowered.endswith(("\\msedgedriver.exe", "/msedgedriver.exe")):
        return False
    return bool(
        WINDOWS_ABSOLUTE_PATH_RE.match(candidate)
        or candidate.startswith(("\\\\", "/", "~", "%", "$", ".\\", "./"))
    )


def rewrite_driver_path_literals(
    source: str,
    managed_driver_path: Path,
) -> tuple[str, int]:
    """Substitui somente strings Python que representam caminhos de msedgedriver."""
    lines = source.splitlines(keepends=True)
    line_offsets: list[int] = []
    total = 0
    for line in lines:
        line_offsets.append(total)
        total += len(line)
    if not lines:
        return source, 0

    def absolute_offset(position: tuple[int, int]) -> int:
        line_number, column = position
        return line_offsets[line_number - 1] + column

    replacements: list[tuple[int, int, str]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.STRING:
                continue
            try:
                literal = ast.literal_eval(token.string)
            except (SyntaxError, ValueError):
                continue
            if not is_driver_path_literal(literal):
                continue
            if str(literal).casefold() == str(managed_driver_path).casefold():
                continue
            replacements.append(
                (
                    absolute_offset(token.start),
                    absolute_offset(token.end),
                    repr(str(managed_driver_path)),
                )
            )
    except tokenize.TokenError as exc:
        raise OrchestratorError(f"Não foi possível analisar o script Python: {exc}") from exc

    rewritten = source
    for start, end, replacement in reversed(replacements):
        rewritten = rewritten[:start] + replacement + rewritten[end:]
    return rewritten, len(replacements)


def signature_status_is_invalid(status: str | None) -> bool:
    """Indisponibilidade da consulta não equivale a assinatura inválida."""
    return bool(status and status != "Valid" and not status.startswith("Unavailable"))


def expand_environment(value: str) -> str:
    """Expande ${VAR}, $VAR e %VAR% de modo consistente em qualquer SO."""
    expanded = os.path.expandvars(os.path.expanduser(value))

    def replace_windows_var(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.environ.get(key, match.group(0))

    return WINDOWS_ENV_RE.sub(replace_windows_var, expanded)


def resolve_path(value: str | Path, base: Path, project_root: Path | None = None) -> Path:
    raw = str(value)
    if project_root is not None:
        raw = raw.replace("{project_root}", str(project_root))
    path = Path(expand_environment(raw))
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)


def _as_nonnegative_int(value: Any, field: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise OrchestratorError(f"Configuração inválida em {field}: {value!r}") from exc
    if result < 0:
        raise OrchestratorError(f"Configuração inválida em {field}: deve ser >= 0")
    return result


def _validate_schedule(value: str) -> str:
    try:
        dt.datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise OrchestratorError(f"Horário inválido em schedules: {value!r}") from exc
    return value


def _build_job(
    raw: Mapping[str, Any],
    project_root: Path,
    logs_dir: Path,
    defaults: Mapping[str, Any] | None = None,
) -> Job:
    merged: dict[str, Any] = dict(defaults or {})
    merged.update(raw)
    name = str(merged.get("name", "")).strip()
    script_value = str(merged.get("script", "")).strip()
    if not name or not script_value:
        raise OrchestratorError("Cada job precisa de name e script.")
    script = resolve_path(script_value, project_root, project_root)
    working_directory = resolve_path(
        merged.get("working_directory", str(project_root)), project_root, project_root
    )
    log_file = resolve_path(
        merged.get("log_file", str(logs_dir / f"{name}.log")), project_root, project_root
    )
    environment = {
        str(key): str(value) for key, value in dict(merged.get("environment", {})).items()
    }
    return Job(
        name=name,
        script=script,
        working_directory=working_directory,
        options=tuple(str(item) for item in merged.get("options", [])),
        command=str(merged.get("command", "run")).strip(),
        command_arguments=tuple(str(item) for item in merged.get("command_arguments", [])),
        log_file=log_file,
        timeout_minutes=_as_nonnegative_int(merged.get("timeout_minutes", 45), f"jobs.{name}.timeout_minutes"),
        retries=_as_nonnegative_int(merged.get("retries", 1), f"jobs.{name}.retries"),
        retry_delay_seconds=_as_nonnegative_int(
            merged.get("retry_delay_seconds", 30), f"jobs.{name}.retry_delay_seconds"
        ),
        enabled=bool(merged.get("enabled", True)),
        environment=environment,
        schedule=parse_schedule(dict(merged.get("schedule", {}))),
        skip_exit_codes=tuple(int(code) for code in merged.get("skip_exit_codes", [])),
    )


def _discover_jobs(
    discovery: Mapping[str, Any], project_root: Path, logs_dir: Path,
    schedule_defaults: Mapping[str, Any] | None = None,
) -> list[Job]:
    if not discovery.get("enabled", False):
        return []
    pattern = str(discovery.get("pattern", "pipefy_*_tool_edge.py"))
    excluded = {str(item).casefold() for item in discovery.get("exclude", [])}
    defaults = {
        "command": discovery.get("command", "run"),
        "command_arguments": discovery.get("command_arguments", []),
        "timeout_minutes": discovery.get("timeout_minutes", 45),
        "retries": discovery.get("retries", 1),
        "retry_delay_seconds": discovery.get("retry_delay_seconds", 30),
        "schedule": discovery.get("schedule", schedule_defaults or {}),
    }
    result: list[Job] = []
    for script in sorted(project_root.glob(pattern), key=lambda item: item.name.casefold()):
        if script.name.casefold() in excluded:
            continue
        name = script.stem
        options = list(discovery.get("options", []))
        if bool(discovery.get("inject_log_file", True)):
            log_path = logs_dir / f"{name}.log"
            options = ["--log-file", str(log_path), *options]
        result.append(
            _build_job(
                {
                    "name": name,
                    "script": str(script),
                    "options": options,
                    "log_file": str(logs_dir / f"{name}.log"),
                },
                project_root,
                logs_dir,
                defaults,
            )
        )
    return result


def load_settings(config_path: Path) -> Settings:
    config_path = config_path.resolve(strict=False)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise OrchestratorError(f"Configuração não encontrada: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise OrchestratorError(
            f"JSON inválido em {config_path}, linha {exc.lineno}, coluna {exc.colno}."
        ) from exc

    if int(raw.get("schema_version", 0)) != 1:
        raise OrchestratorError("schema_version deve ser 1.")

    config_dir = config_path.parent
    project_root = resolve_path(raw.get("project_root", "."), config_dir)
    output_dir = resolve_path(
        raw.get("output_dir", str(config_dir.parent)),
        config_dir,
        project_root,
    )
    runtime_dir = resolve_path(raw.get("runtime_dir", ".pipefy_orchestrator"), project_root, project_root)
    logs_dir = resolve_path(raw.get("logs_dir", "logs"), project_root, project_root)
    orchestration_log = resolve_path(
        raw.get("orchestration_log", str(logs_dir / "pipefy_orchestrator.log")),
        project_root,
        project_root,
    )

    driver_raw = dict(raw.get("driver", {}))
    managed_value = str(driver_raw.get("managed_path", "")).strip()
    if not managed_value:
        raise OrchestratorError("driver.managed_path é obrigatório.")
    edge_value = str(driver_raw.get("edge_binary", "")).strip()
    driver_mirror_url = str(
        driver_raw.get("driver_mirror_url", "https://msedgedriver.microsoft.com")
    ).rstrip("/")
    if not driver_mirror_url.startswith("https://"):
        raise OrchestratorError("driver.driver_mirror_url deve usar HTTPS.")
    driver = DriverSettings(
        edge_binary=(
            resolve_path(edge_value, project_root, project_root) if edge_value else None
        ),
        managed_path=resolve_path(managed_value, project_root, project_root),
        selenium_cache=resolve_path(
            driver_raw.get("selenium_cache", str(runtime_dir / "selenium-cache")),
            project_root,
            project_root,
        ),
        driver_mirror_url=driver_mirror_url,
        auto_repair=bool(driver_raw.get("auto_repair", True)),
        verify_authenticode=bool(driver_raw.get("verify_authenticode", True)),
        session_test=bool(driver_raw.get("session_test", True)),
        session_test_headless=bool(driver_raw.get("session_test_headless", True)),
        manager_timeout_seconds=_as_nonnegative_int(
            driver_raw.get("manager_timeout_seconds", 300),
            "driver.manager_timeout_seconds",
        ),
        keep_backups=_as_nonnegative_int(
            driver_raw.get("keep_backups", 3), "driver.keep_backups"
        ),
        force_managed_driver_for_jobs=bool(
            driver_raw.get("force_managed_driver_for_jobs", True)
        ),
        adapt_script_driver_paths=bool(
            driver_raw.get("adapt_script_driver_paths", True)
        ),
    )

    schedule_defaults = dict(raw.get("schedule_defaults", {}))
    explicit_jobs = [
        _build_job(item, project_root, logs_dir, {"schedule": schedule_defaults})
        for item in raw.get("jobs", [])
    ]
    discovered_jobs = _discover_jobs(dict(raw.get("discovery", {})), project_root, logs_dir, schedule_defaults)
    jobs_by_name: dict[str, Job] = {}
    for job in discovered_jobs:
        jobs_by_name[job.name.casefold()] = job
    for job in explicit_jobs:
        jobs_by_name[job.name.casefold()] = job
    for name, override in raw.get("job_schedules", {}).items():
        key = str(name).casefold()
        if key not in jobs_by_name:
            continue
        job = jobs_by_name[key]
        values = dict(override)
        enabled = values.pop("enabled", job.enabled)
        if not isinstance(enabled, bool):
            raise OrchestratorError(f"job_schedules.{name}.enabled deve ser true ou false.")
        jobs_by_name[key] = dataclasses.replace(
            job, enabled=enabled,
            schedule=parse_schedule({**dataclasses.asdict(job.schedule), **values}),
        )

    schedules = tuple(_validate_schedule(str(item)) for item in raw.get("schedules", []))
    return Settings(
        config_path=config_path,
        project_root=project_root,
        output_dir=output_dir,
        python_executable=str(raw.get("python_executable", "py")),
        runtime_dir=runtime_dir,
        logs_dir=logs_dir,
        orchestration_log=orchestration_log,
        inter_job_delay_seconds=_as_nonnegative_int(
            raw.get("inter_job_delay_seconds", 300), "inter_job_delay_seconds"
        ),
        continue_on_error=bool(raw.get("continue_on_error", False)),
        check_driver_before_each_job=bool(
            raw.get("check_driver_before_each_job", True)
        ),
        driver=driver,
        jobs=tuple(jobs_by_name.values()),
        schedules=schedules,
    )


def configure_logging(log_file: Path | None = None, debug: bool = False) -> logging.Logger:
    logger = logging.getLogger("pipefy_orchestrator")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger


@contextlib.contextmanager
def temporary_environment(updates: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class RunLock:
    def __init__(self, path: Path):
        self.path = path
        self.acquired = False

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError as exc:
                try:
                    current_pid = int(self.path.read_text(encoding="ascii").strip())
                except (OSError, ValueError):
                    current_pid = -1
                if attempt == 0 and not self._pid_is_alive(current_pid):
                    self.path.unlink(missing_ok=True)
                    continue
                raise OrchestratorError(
                    f"Já existe uma execução ativa do orquestrador (PID {current_pid})."
                ) from exc
            else:
                with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                    handle.write(str(os.getpid()))
                self.acquired = True
                return self
        raise OrchestratorError("Não foi possível adquirir o lock de execução.")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)


class DriverGuard:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.config = settings.driver
        self.logger = logger
        self.edge_binary: Path | None = None

    def detect_edge_binary(self) -> Path:
        if self.edge_binary and self.edge_binary.is_file():
            return self.edge_binary
        candidates: list[Path] = []
        if self.config.edge_binary:
            candidates.append(self.config.edge_binary)
        for key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(key)
            if root:
                candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        found = shutil.which("msedge.exe") or shutil.which("msedge")
        if found:
            candidates.append(Path(found))
        for candidate in candidates:
            if candidate.is_file():
                self.edge_binary = candidate.resolve(strict=False)
                return self.edge_binary
        checked = ", ".join(str(item) for item in candidates) or "nenhum caminho"
        raise OrchestratorError(f"Microsoft Edge não encontrado. Caminhos verificados: {checked}")

    @staticmethod
    def _powershell_output(command: str, environment: Mapping[str, str]) -> str:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
        if not powershell:
            raise OrchestratorError("PowerShell não encontrado para consultar o executável.")
        env = os.environ.copy()
        env.update(environment)
        completed = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
            env=env,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise OrchestratorError(f"Falha ao consultar PowerShell: {detail}")
        return completed.stdout.strip()

    def edge_version(self, edge_binary: Path | None = None) -> tuple[int, int, int, int]:
        edge_binary = edge_binary or self.detect_edge_binary()
        if os.name == "nt":
            output = self._powershell_output(
                "(Get-Item -LiteralPath $env:PIPEFY_EDGE_BINARY).VersionInfo.ProductVersion",
                {"PIPEFY_EDGE_BINARY": str(edge_binary)},
            )
            return parse_version(output)
        completed = subprocess.run(
            [str(edge_binary), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return parse_version(f"{completed.stdout}\n{completed.stderr}")

    @staticmethod
    def driver_version(driver_path: Path) -> tuple[int, int, int, int]:
        if not driver_path.is_file():
            raise OrchestratorError(f"msedgedriver não encontrado: {driver_path}")
        try:
            completed = subprocess.run(
                [str(driver_path), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                check=False,
            )
        except OSError as exc:
            raise OrchestratorError(
                f"msedgedriver não pôde ser executado: {driver_path}: {exc}"
            ) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise OrchestratorError(f"msedgedriver inválido: {detail}")
        return parse_version(f"{completed.stdout}\n{completed.stderr}")

    def authenticode_status(self, path: Path) -> str | None:
        if not self.config.verify_authenticode or os.name != "nt":
            return None
        try:
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            class WINTRUST_FILE_INFO(ctypes.Structure):
                _fields_ = [
                    ("cbStruct", wintypes.DWORD),
                    ("pcwszFilePath", wintypes.LPCWSTR),
                    ("hFile", wintypes.HANDLE),
                    ("pgKnownSubject", ctypes.c_void_p),
                ]

            class WINTRUST_DATA(ctypes.Structure):
                _fields_ = [
                    ("cbStruct", wintypes.DWORD),
                    ("pPolicyCallbackData", ctypes.c_void_p),
                    ("pSIPClientData", ctypes.c_void_p),
                    ("dwUIChoice", wintypes.DWORD),
                    ("fdwRevocationChecks", wintypes.DWORD),
                    ("dwUnionChoice", wintypes.DWORD),
                    ("pFile", ctypes.POINTER(WINTRUST_FILE_INFO)),
                    ("dwStateAction", wintypes.DWORD),
                    ("hWVTStateData", wintypes.HANDLE),
                    ("pwszURLReference", wintypes.LPCWSTR),
                    ("dwProvFlags", wintypes.DWORD),
                    ("dwUIContext", wintypes.DWORD),
                    ("pSignatureSettings", ctypes.c_void_p),
                ]

            action = GUID(
                0x00AAC56B,
                0xCD44,
                0x11D0,
                (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE),
            )
            file_info = WINTRUST_FILE_INFO(
                ctypes.sizeof(WINTRUST_FILE_INFO),
                str(path),
                None,
                None,
            )
            trust_data = WINTRUST_DATA()
            trust_data.cbStruct = ctypes.sizeof(WINTRUST_DATA)
            trust_data.dwUIChoice = 2  # WTD_UI_NONE
            trust_data.fdwRevocationChecks = 0  # WTD_REVOKE_NONE
            trust_data.dwUnionChoice = 1  # WTD_CHOICE_FILE
            trust_data.pFile = ctypes.pointer(file_info)
            trust_data.dwStateAction = 0  # WTD_STATEACTION_IGNORE
            trust_data.dwProvFlags = 0x00001000  # WTD_CACHE_ONLY_URL_RETRIEVAL

            wintrust = ctypes.WinDLL("wintrust", use_last_error=True)
            verify = wintrust.WinVerifyTrust
            verify.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(GUID),
                ctypes.POINTER(WINTRUST_DATA),
            ]
            verify.restype = wintypes.LONG
            result = verify(None, ctypes.byref(action), ctypes.byref(trust_data))
            if result == 0:
                return "Valid"
            code = ctypes.c_uint32(result).value
            labels = {
                0x800B0100: "NotSigned",
                0x80096010: "HashMismatch",
                0x800B0101: "Expired",
                0x800B0109: "UntrustedRoot",
                0x800B010A: "ChainFailure",
                0x800B010C: "Revoked",
                0x800B0111: "ExplicitDistrust",
            }
            return labels.get(code, f"Invalid (0x{code:08X})")
        except Exception as exc:
            return f"Unavailable (WinVerifyTrust: {exc})"

    @staticmethod
    def edge_policy_status() -> dict[str, int]:
        if os.name != "nt":
            return {}
        try:
            import winreg
        except ImportError:
            return {}
        result: dict[str, int] = {}
        locations = (
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Policies\Microsoft\Edge", "HKCU"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Edge", "HKLM"),
        )
        for hive, subkey, label in locations:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    value, _ = winreg.QueryValueEx(key, "DeveloperToolsAvailability")
            except OSError:
                continue
            result[f"{label}\\{subkey}\\DeveloperToolsAvailability"] = int(value)
        return result

    def inspect(self) -> dict[str, Any]:
        edge = self.detect_edge_binary()
        browser_version = self.edge_version(edge)
        driver_version: tuple[int, int, int, int] | None = None
        driver_error: str | None = None
        if self.config.managed_path.is_file():
            try:
                driver_version = self.driver_version(self.config.managed_path)
            except OrchestratorError as exc:
                driver_error = str(exc)
        signature: str | None = None
        if self.config.managed_path.is_file():
            try:
                signature = self.authenticode_status(self.config.managed_path)
            except OrchestratorError as exc:
                signature = f"consulta falhou: {exc}"
        return {
            "edge_binary": str(edge),
            "edge_version": browser_version,
            "driver_path": str(self.config.managed_path),
            "driver_version": driver_version,
            "driver_error": driver_error,
            "compatible": versions_compatible(browser_version, driver_version),
            "authenticode": signature,
            "policies": self.edge_policy_status(),
        }

    @staticmethod
    def _driver_archive_name() -> str:
        machine = platform.machine().casefold()
        if machine in {"arm64", "aarch64"}:
            return "edgedriver_arm64.zip"
        if machine in {"x86", "i386", "i686"}:
            return "edgedriver_win32.zip"
        return "edgedriver_win64.zip"

    def _download_bytes(self, url: str, maximum_bytes: int) -> bytes:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"pipefy-orchestrator/{APP_VERSION}"},
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.manager_timeout_seconds,
            ) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_size = int(content_length)
                    except ValueError:
                        declared_size = 0
                    if declared_size > maximum_bytes:
                        raise OrchestratorError(
                            f"Download excede o limite permitido: {content_length} bytes."
                        )
                payload = response.read(maximum_bytes + 1)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            raise OrchestratorError(f"Falha no download de {url}: {exc}") from exc
        if len(payload) > maximum_bytes:
            raise OrchestratorError(
                f"Download excede o limite permitido de {maximum_bytes} bytes."
            )
        return payload

    def _download_driver_from_official_mirror(
        self,
        browser_version: tuple[int, int, int, int],
    ) -> Path:
        mirror = self.config.driver_mirror_url
        browser_text = format_version(browser_version)
        versions = [browser_text]
        release_url = f"{mirror}/LATEST_RELEASE_{browser_version[0]}_WINDOWS"
        try:
            release_text = self._download_bytes(release_url, 4096).decode(
                "utf-8", errors="replace"
            ).strip()
            release_version = format_version(parse_version(release_text))
            if release_version not in versions:
                versions.append(release_version)
        except OrchestratorError as exc:
            self.logger.warning("Consulta da versão mais recente falhou: %s", exc)

        archive_name = self._driver_archive_name()
        errors: list[str] = []
        for version_text in versions:
            try:
                candidate_version = parse_version(version_text)
            except OrchestratorError as exc:
                errors.append(str(exc))
                continue
            if not versions_compatible(browser_version, candidate_version):
                errors.append(
                    f"versão publicada incompatível: {version_text} para Edge {browser_text}"
                )
                continue
            url = f"{mirror}/{version_text}/{archive_name}"
            self.logger.info(
                "Baixando msedgedriver %s do mirror oficial da Microsoft.",
                version_text,
            )
            try:
                archive = self._download_bytes(url, 100 * 1024 * 1024)
                with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                    members = [
                        item
                        for item in bundle.infolist()
                        if Path(item.filename).name.casefold() == "msedgedriver.exe"
                    ]
                    if len(members) != 1:
                        raise OrchestratorError(
                            "Pacote do driver não contém exatamente um msedgedriver.exe."
                        )
                    member = members[0]
                    if member.file_size > 100 * 1024 * 1024:
                        raise OrchestratorError("Executável do driver excede o limite permitido.")
                    cache_dir = self.config.selenium_cache / "official-mirror" / version_text
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    target = cache_dir / "msedgedriver.exe"
                    temporary = target.with_suffix(f".exe.{os.getpid()}.tmp")
                    temporary.unlink(missing_ok=True)
                    with bundle.open(member) as source, temporary.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    os.replace(temporary, target)
                downloaded_version = self.driver_version(target)
                if not versions_compatible(browser_version, downloaded_version):
                    target.unlink(missing_ok=True)
                    raise OrchestratorError(
                        "Driver baixado é incompatível: "
                        f"Edge {browser_text}, driver {format_version(downloaded_version)}."
                    )
                return target.resolve(strict=False)
            except (OrchestratorError, zipfile.BadZipFile, OSError) as exc:
                errors.append(f"{version_text}: {exc}")
        raise OrchestratorError(
            "O mirror oficial não forneceu um driver compatível. " + " | ".join(errors)
        )

    def _resolve_driver_with_selenium_manager(self, edge: Path) -> Path:
        try:
            import selenium
            from selenium.webdriver.common.selenium_manager import SeleniumManager
        except ImportError as exc:
            raise OrchestratorError(
                "Selenium não instalado. Execute: py -m pip install -r requirements.txt"
            ) from exc

        self.config.selenium_cache.mkdir(parents=True, exist_ok=True)
        mirror = self.config.driver_mirror_url
        environment = {
            "SE_CACHE_PATH": str(self.config.selenium_cache),
            "SE_EDGE_PATH": str(edge),
            "SE_DRIVER_MIRROR_URL": mirror,
            "SE_MSEDGEDRIVER_MIRROR_URL": mirror,
            "SE_EDGE_MIRROR_URL": mirror,
            "SE_SKIP_DRIVER_IN_PATH": "true",
            "SE_AVOID_BROWSER_DOWNLOAD": "true",
            "SE_AVOID_STATS": "true",
            "SE_TIMEOUT": str(self.config.manager_timeout_seconds),
            "SE_TTL": "0",
        }
        args = [
            "--browser",
            "MicrosoftEdge",
            "--browser-path",
            str(edge),
            "--driver-mirror-url",
            mirror,
            "--skip-driver-in-path",
            "--avoid-browser-download",
            "--avoid-stats",
            "--timeout",
            str(self.config.manager_timeout_seconds),
            "--ttl",
            "0",
        ]
        self.logger.info("Resolvendo driver compatível com Selenium %s.", selenium.__version__)
        try:
            with temporary_environment(environment):
                output = SeleniumManager().binary_paths(args)
        except Exception as exc:
            self.logger.warning(
                "Selenium Manager não obteve o driver; usando download direto. Detalhe: %s",
                exc,
            )
            return self._download_driver_from_official_mirror(self.edge_version(edge))
        driver_path = Path(str(output.get("driver_path", "")))
        if not driver_path.is_file():
            self.logger.warning(
                "Selenium Manager retornou caminho inválido; usando download direto: %s",
                driver_path,
            )
            return self._download_driver_from_official_mirror(self.edge_version(edge))
        return driver_path.resolve(strict=False)

    def _prune_backups(self) -> None:
        keep = self.config.keep_backups
        pattern = f"{self.config.managed_path.name}.backup-*"
        backups = sorted(
            self.config.managed_path.parent.glob(pattern),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old in backups[keep:]:
            old.unlink(missing_ok=True)

    def repair(self) -> dict[str, Any]:
        edge = self.detect_edge_binary()
        browser_version = self.edge_version(edge)
        source = self._resolve_driver_with_selenium_manager(edge)
        source_version = self.driver_version(source)
        if not versions_compatible(browser_version, source_version):
            raise OrchestratorError(
                "Selenium Manager retornou versão incompatível: "
                f"Edge {format_version(browser_version)}, driver {format_version(source_version)}."
            )

        target = self.config.managed_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source == target.resolve(strict=False):
            self.logger.info("Driver gerenciado já está no caminho de destino.")
            return self.inspect()

        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        backup: Path | None = None
        temporary.unlink(missing_ok=True)
        shutil.copy2(source, temporary)
        copied_version = self.driver_version(temporary)
        if not versions_compatible(browser_version, copied_version):
            temporary.unlink(missing_ok=True)
            raise OrchestratorError("A cópia temporária do driver falhou na validação de versão.")
        signature = self.authenticode_status(temporary)
        if signature_status_is_invalid(signature):
            temporary.unlink(missing_ok=True)
            raise OrchestratorError(
                f"Assinatura Authenticode do driver não é válida: {signature or 'sem status'}."
            )
        if signature and signature.startswith("Unavailable"):
            self.logger.warning(
                "Assinatura Authenticode não pôde ser consultada; seguindo com validação "
                "de versão e teste real de sessão: %s",
                signature,
            )

        timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            if target.exists():
                backup = target.with_name(f"{target.name}.backup-{timestamp}")
                os.replace(target, backup)
            os.replace(temporary, target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            if backup and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise OrchestratorError(
                "Não foi possível substituir o driver. Confirme que não há extração ou "
                f"msedgedriver em execução. Detalhe: {exc}"
            ) from exc
        self._prune_backups()
        self.logger.info(
            "Driver atualizado: Edge %s, msedgedriver %s.",
            format_version(browser_version),
            format_version(copied_version),
        )
        return self.inspect()

    def test_session(self) -> dict[str, str]:
        try:
            from selenium import webdriver
            from selenium.webdriver.edge.options import Options
            from selenium.webdriver.edge.service import Service
        except ImportError as exc:
            raise OrchestratorError(
                "Selenium não instalado. Execute: py -m pip install -r requirements.txt"
            ) from exc

        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        driver_log = self.settings.logs_dir / "edge_driver_health.log"
        driver_log.parent.mkdir(parents=True, exist_ok=True)
        edge = self.detect_edge_binary()
        service = Service(
            executable_path=str(self.config.managed_path),
            log_output=str(driver_log),
            service_args=["--verbose"],
        )
        options = Options()
        options.binary_location = str(edge)
        if self.config.session_test_headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--log-level=3")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        options.add_argument("--window-size=800,600")

        try:
            with tempfile.TemporaryDirectory(
                prefix="edge-health-",
                dir=self.settings.runtime_dir,
                ignore_cleanup_errors=True,
            ) as profile:
                options.add_argument(f"--user-data-dir={profile}")
                driver = webdriver.Edge(service=service, options=options)
                try:
                    driver.get("data:text/html,<title>pipefy-driver-ok</title>")
                    title = driver.title
                    browser_version = str(driver.capabilities.get("browserVersion", ""))
                finally:
                    driver.quit()
        except Exception as exc:
            raise OrchestratorError(
                "Teste real de sessão do Edge falhou. "
                f"Consulte {driver_log}. Detalhe: {exc}"
            ) from exc
        if title != "pipefy-driver-ok":
            raise OrchestratorError("Sessão iniciou, mas o teste interno do navegador falhou.")
        return {"browser_version": browser_version, "driver_log": str(driver_log)}

    def ensure(self, repair: bool, test_session: bool | None = None) -> dict[str, Any]:
        details = self.inspect()
        browser_version = details["edge_version"]
        driver_version = details["driver_version"]
        signature = details["authenticode"]
        blocked_policies = {
            key: value for key, value in details["policies"].items() if value == 2
        }
        if blocked_policies:
            locations = ", ".join(blocked_policies)
            raise OrchestratorError(
                "Edge WebDriver bloqueado pela política DeveloperToolsAvailability=2: "
                f"{locations}."
            )

        invalid_signature = signature_status_is_invalid(signature)
        if signature and signature.startswith("Unavailable"):
            self.logger.warning(
                "Assinatura Authenticode indisponível; versão e sessão permanecem obrigatórias: %s",
                signature,
            )
        needs_repair = not details["compatible"] or invalid_signature
        if needs_repair:
            reason = (
                f"Edge {format_version(browser_version)}, "
                f"driver {format_version(driver_version)}, assinatura {signature or 'não consultada'}"
            )
            if not repair:
                raise OrchestratorError(f"Driver precisa de reparo: {reason}.")
            self.logger.warning("Driver ausente, incompatível ou inválido: %s.", reason)
            details = self.repair()

        should_test = self.config.session_test if test_session is None else test_session
        if should_test:
            try:
                details["session"] = self.test_session()
            except OrchestratorError:
                if not repair:
                    raise
                self.logger.warning("A sessão falhou; renovando o driver e testando novamente.")
                details = self.repair()
                details["session"] = self.test_session()
        return details


class Orchestrator:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger
        self.driver_guard = DriverGuard(settings, logger)

    def selected_jobs(self, names: Sequence[str] | None) -> list[Job]:
        enabled = [job for job in self.settings.jobs if job.enabled]
        if not names:
            return enabled
        requested = {name.casefold() for name in names}
        selected = [job for job in enabled if job.name.casefold() in requested]
        missing = requested - {job.name.casefold() for job in selected}
        if missing:
            raise OrchestratorError(
                "Jobs não encontrados ou desabilitados: " + ", ".join(sorted(missing))
            )
        return selected

    def command_for(self, job: Job, action_override: str | None = None) -> list[str]:
        def expand(item: str) -> str:
            return (
                item.replace("{project_root}", str(self.settings.project_root))
                .replace("{output_dir}", str(self.settings.output_dir))
                .replace("{log_file}", str(job.log_file))
                .replace("{driver_path}", str(self.settings.driver.managed_path))
            )

        options = [expand(item) for item in job.options]
        command = action_override or job.command
        result = [self.settings.python_executable, str(job.script), *options]
        if command:
            result.append(command)
        if action_override is None or action_override == job.command:
            result.extend(expand(item) for item in job.command_arguments)
        return result

    def _ensure_driver_adapter(self) -> Path:
        adapter_dir = self.settings.runtime_dir / "driver_adapter"
        adapter_path = adapter_dir / "sitecustomize.py"
        adapter_dir.mkdir(parents=True, exist_ok=True)
        try:
            current = adapter_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        if current != DRIVER_ADAPTER_SOURCE:
            temporary = adapter_path.with_suffix(f".py.{os.getpid()}.tmp")
            temporary.write_text(DRIVER_ADAPTER_SOURCE, encoding="utf-8")
            os.replace(temporary, adapter_path)
        return adapter_dir.resolve(strict=False)

    def _adapt_job_driver_paths(self, jobs: Sequence[Job]) -> int:
        if not self.settings.driver.adapt_script_driver_paths:
            return 0
        backup_dir = self.settings.runtime_dir / "script_backups"
        changed_scripts = 0
        seen: set[Path] = set()
        for job in jobs:
            script = job.script.resolve(strict=False)
            if script in seen or not script.is_file():
                continue
            seen.add(script)
            try:
                raw = script.read_bytes()
                encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
                source = raw.decode(encoding)
                rewritten, replacements = rewrite_driver_path_literals(
                    source,
                    self.settings.driver.managed_path,
                )
            except (OSError, UnicodeError, SyntaxError) as exc:
                raise OrchestratorError(
                    f"Falha ao analisar o caminho do driver em {script}: {exc}"
                ) from exc
            if not replacements:
                continue
            try:
                compile(rewritten, str(script), "exec")
            except SyntaxError as exc:
                raise OrchestratorError(
                    f"A adaptação automática tornaria {script.name} inválido: {exc}"
                ) from exc

            backup_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(raw).hexdigest()[:12]
            backup = backup_dir / f"{script.stem}.{digest}{script.suffix}"
            temporary = script.with_name(f".{script.name}.{os.getpid()}.tmp")
            try:
                if not backup.exists():
                    shutil.copy2(script, backup)
                temporary.write_bytes(rewritten.encode(encoding))
                shutil.copymode(script, temporary)
                os.replace(temporary, script)
            except OSError as exc:
                temporary.unlink(missing_ok=True)
                raise OrchestratorError(
                    "Não foi possível atualizar o caminho antigo do driver em "
                    f"{script}. Detalhe: {exc}"
                ) from exc
            changed_scripts += 1
            self.logger.info(
                "Caminho do driver atualizado em %s (%s ocorrência(s)); backup: %s",
                script.name,
                replacements,
                backup,
            )
        return changed_scripts

    def _job_environment(self, job: Job) -> dict[str, str]:
        environment = os.environ.copy()
        driver_path = str(self.settings.driver.managed_path)
        environment.update(
            {
                "MSEDGEDRIVER_PATH": driver_path,
                "EDGE_DRIVER_PATH": driver_path,
                "PIPEFY_EDGE_DRIVER_PATH": driver_path,
                "PIPEFY_DRIVER_BINARY": driver_path,
                "PIPEFY_OUTPUT_DIR": str(self.settings.output_dir),
                "PIPEFY_WORK_DIR": str(self.settings.runtime_dir / "downloads"),
                "SELENIUM_EDGE_DRIVER": driver_path,
                "MSEDGEDRIVER_TELEMETRY_OPTOUT": "1",
                "SE_CACHE_PATH": str(self.settings.driver.selenium_cache),
                "SE_DRIVER_MIRROR_URL": self.settings.driver.driver_mirror_url,
                "SE_MSEDGEDRIVER_MIRROR_URL": self.settings.driver.driver_mirror_url,
                "SE_EDGE_MIRROR_URL": self.settings.driver.driver_mirror_url,
                "SE_AVOID_STATS": "true",
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
        )
        for key, value in job.environment.items():
            environment[key] = expand_environment(
                value.replace("{project_root}", str(self.settings.project_root))
                .replace("{output_dir}", str(self.settings.output_dir))
                .replace("{driver_path}", driver_path)
            )
        if self.settings.driver.force_managed_driver_for_jobs:
            adapter_dir = str(self._ensure_driver_adapter())
            python_path = environment.get("PYTHONPATH", "")
            environment["PYTHONPATH"] = os.pathsep.join(
                item for item in (adapter_dir, python_path) if item
            )
            current_path = environment.get("PATH", "")
            driver_dir = str(self.settings.driver.managed_path.parent)
            environment["PATH"] = os.pathsep.join(
                item for item in (driver_dir, current_path) if item
            )
            environment["PIPEFY_DRIVER_ADAPTER_DIR"] = adapter_dir
        return environment

    def _run_process(self, job: Job, command: list[str]) -> tuple[int, list[str], bool]:
        tail: collections.deque[str] = collections.deque(maxlen=250)
        timed_out = False
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            process = subprocess.Popen(
                command,
                cwd=job.working_directory,
                env=self._job_environment(job),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise OrchestratorError(f"Falha ao iniciar {job.name}: {exc}") from exc

        def consume_output() -> None:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = ANSI_RE.sub("", raw_line.rstrip())
                if line:
                    tail.append(line)
                    self.logger.info("[%s] %s", job.name, line)

        reader = threading.Thread(target=consume_output, daemon=True)
        reader.start()
        timeout_seconds = job.timeout_minutes * 60 if job.timeout_minutes else None
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.logger.error(
                "[%s] Tempo limite de %s minutos excedido.",
                job.name,
                job.timeout_minutes,
            )
            self._terminate_process_tree(process)
            try:
                return_code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=15)
        except KeyboardInterrupt:
            self._terminate_process_tree(process)
            raise
        reader.join(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        return return_code, list(tail), timed_out

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    def _run_job(self, job: Job, action_override: str | None = None) -> JobResult:
        command = self.command_for(job, action_override)
        started = dt.datetime.now(dt.timezone.utc)
        started_monotonic = time.monotonic()
        last_error: str | None = None
        attempts = job.retries + 1
        exit_code: int | None = None

        for attempt in range(1, attempts + 1):
            self.logger.info(
                "Iniciando %s, tentativa %s de %s.", job.name, attempt, attempts
            )
            if not job.script.is_file():
                last_error = f"Script não encontrado: {job.script}"
                exit_code = None
            elif not job.working_directory.is_dir():
                last_error = f"Diretório de trabalho não encontrado: {job.working_directory}"
                exit_code = None
            else:
                try:
                    exit_code, output_tail, timed_out = self._run_process(job, command)
                except OrchestratorError as exc:
                    last_error = str(exc)
                    output_tail = [last_error]
                    timed_out = False
                if exit_code == 0:
                    finished = dt.datetime.now(dt.timezone.utc)
                    return JobResult(
                        name=job.name,
                        status="success",
                        exit_code=0,
                        attempts=attempt,
                        started_at=started.isoformat(),
                        finished_at=finished.isoformat(),
                        elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
                        command=command,
                    )
                if exit_code in job.skip_exit_codes and not timed_out:
                    return JobResult(
                        name=job.name, status="skipped", exit_code=exit_code,
                        attempts=attempt, started_at=started.isoformat(),
                        finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                        elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
                        command=command,
                        error="Rotina ignorada; o lote continuará. " + (output_tail[-1] if output_tail else f"Código {exit_code}."),
                    )
                if timed_out:
                    last_error = f"Tempo limite de {job.timeout_minutes} minutos excedido."
                else:
                    last_error = f"Processo terminou com código {exit_code}."
                if attempt < attempts and contains_profile_error(output_tail):
                    self.logger.warning(
                        "[%s] Falha relacionada ao perfil do Edge detectada; "
                        "o driver já aprovado não será reinstalado.",
                        job.name,
                    )
                elif attempt < attempts and contains_driver_error(output_tail):
                    self.logger.warning(
                        "[%s] Falha relacionada ao driver detectada; executando reparo.",
                        job.name,
                    )
                    self.driver_guard.ensure(
                        repair=self.settings.driver.auto_repair,
                        test_session=True,
                    )

            if attempt < attempts:
                self.logger.info(
                    "[%s] Nova tentativa em %s segundos.",
                    job.name,
                    job.retry_delay_seconds,
                )
                time.sleep(job.retry_delay_seconds)

        finished = dt.datetime.now(dt.timezone.utc)
        return JobResult(
            name=job.name,
            status="failed",
            exit_code=exit_code,
            attempts=attempts,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            elapsed_seconds=round(time.monotonic() - started_monotonic, 3),
            command=command,
            error=last_error,
        )

    def _write_summary(self, action: str, results: Sequence[JobResult]) -> Path:
        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            "orchestrator_version": APP_VERSION,
            "action": action,
            "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "success": all(item.status != "failed" for item in results),
            "has_warnings": any(item.status == "skipped" for item in results),
            "jobs": [dataclasses.asdict(item) for item in results],
        }
        last_run = self.settings.runtime_dir / "last_run.json"
        temporary = last_run.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, last_run)
        history = self.settings.runtime_dir / "run_history.jsonl"
        with history.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False) + "\n")
        return last_run

    def run(
        self,
        job_names: Sequence[str] | None,
        delay_seconds: int | None,
        skip_driver_check: bool,
        dry_run: bool,
        action_override: str | None = None,
        first_only: bool = False,
        force: bool = False,
    ) -> int:
        jobs = self.selected_jobs(job_names)
        if first_only and jobs:
            jobs = jobs[:1]
        if not jobs:
            raise OrchestratorError(
                "Nenhum job habilitado. Ajuste jobs ou discovery na configuração."
            )
        if dry_run:
            self.logger.info(
                "DRY-RUN | arquivos finais em %s",
                self.settings.output_dir,
            )
            state = read_state(self.settings.runtime_dir / "job_schedule_state.json")
            now = dt.datetime.now().astimezone()
            for job in jobs:
                due, reason = due_reason(job.schedule, state["jobs"].get(job.name.casefold(), {}).get("last_success_at"), now)
                if force or action_override or due:
                    self.logger.info("DRY-RUN | %s", subprocess.list2cmdline(self.command_for(job, action_override)))
                else:
                    self.logger.info("DRY-RUN | %s | %s", job.name, reason)
            return 0

        wait_seconds = (
            self.settings.inter_job_delay_seconds
            if delay_seconds is None
            else _as_nonnegative_int(delay_seconds, "delay_seconds")
        )
        results: list[JobResult] = []
        lock_path = self.settings.runtime_dir / "orchestrator.lock"
        with RunLock(lock_path):
            state_path = self.settings.runtime_dir / "job_schedule_state.json"
            state = read_state(state_path)
            pending_jobs = []
            now = dt.datetime.now().astimezone()
            for job in jobs:
                due, reason = due_reason(job.schedule, state["jobs"].get(job.name.casefold(), {}).get("last_success_at"), now)
                if force or action_override or due:
                    pending_jobs.append(job)
                else:
                    self.logger.info("%s: %s", job.name, reason)
                    results.append(JobResult(job.name, "not_due", None, 0, now.isoformat(),
                                             now.isoformat(), 0.0, [], reason))
            jobs = pending_jobs
            if not jobs:
                summary_path = self._write_summary(action_override or "run", results)
                self.logger.info("Nenhuma rotina pendente. Resumo: %s", summary_path)
                return 0
            self.logger.info(
                "Arquivos finais serão publicados em %s.",
                self.settings.output_dir,
            )
            if not skip_driver_check:
                details = self.driver_guard.ensure(
                    repair=self.settings.driver.auto_repair,
                    test_session=True,
                )
                self.logger.info(
                    "Pré-checagem concluída: Edge %s, driver %s.",
                    format_version(details["edge_version"]),
                    format_version(details["driver_version"]),
                )
            changed_scripts = self._adapt_job_driver_paths(jobs)
            if changed_scripts:
                self.logger.info(
                    "%s extrator(es) adaptado(s) para o driver gerenciado.",
                    changed_scripts,
                )
            for index, job in enumerate(jobs):
                if (
                    not skip_driver_check
                    and self.settings.check_driver_before_each_job
                    and index > 0
                ):
                    self.driver_guard.ensure(
                        repair=self.settings.driver.auto_repair,
                        test_session=False,
                    )
                result = self._run_job(job, action_override)
                results.append(result)
                if result.status == "skipped":
                    self.logger.warning("%s: %s", job.name, result.error)
                    continue
                if result.status == "failed":
                    self.logger.error("Job %s falhou: %s", job.name, result.error)
                    if not self.settings.continue_on_error:
                        break
                else:
                    if action_override is None:
                        state["jobs"][job.name.casefold()] = {
                            "last_success_at": dt.datetime.now().astimezone().isoformat(),
                        }
                        atomic_json(state_path, state)
                    self.logger.info(
                        "Job %s concluído em %.1f segundos.",
                        job.name,
                        result.elapsed_seconds,
                    )
                if index < len(jobs) - 1 and wait_seconds:
                    self.logger.info("Próximo job em %s segundos.", wait_seconds)
                    time.sleep(wait_seconds)

            summary_path = self._write_summary(action_override or "run", results)
        failed = [item.name for item in results if item.status == "failed"]
        if failed:
            self.logger.error(
                "Lote concluído com falhas: %s. Resumo: %s",
                ", ".join(failed),
                summary_path,
            )
            return 1
        if any(item.status == "skipped" for item in results):
            self.logger.warning("Lote concluído com aviso de rotina ignorada. Resumo: %s", summary_path)
        else:
            self.logger.info("Lote concluído com sucesso. Resumo: %s", summary_path)
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orquestra extrações Pipefy e protege a compatibilidade Edge/driver."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("pipefy_orchestrator.config.json"),
        help="Arquivo JSON de configuração.",
    )
    parser.add_argument("--debug", action="store_true", help="Exibe logs de diagnóstico.")
    parser.add_argument("--version", action="version", version=APP_VERSION)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    doctor = subparsers.add_parser("doctor", help="Verifica Edge, driver, política e sessão.")
    doctor.add_argument("--repair", action="store_true", help="Repara o driver se necessário.")
    doctor.add_argument(
        "--no-session-test", action="store_true", help="Não abre a sessão isolada de teste."
    )

    run = subparsers.add_parser("run", help="Executa o lote de extrações.")
    run.add_argument("--job", action="append", dest="jobs", help="Executa somente o job indicado.")
    run.add_argument("--delay-seconds", type=int, help="Substitui o intervalo entre jobs.")
    run.add_argument("--skip-driver-check", action="store_true")
    run.add_argument("--dry-run", action="store_true", help="Mostra comandos sem executá-los.")
    run.add_argument("--force", action="store_true", help="Ignora a frequência nesta execução, mantendo as rotinas desabilitadas fora do lote.")

    login = subparsers.add_parser("login", help="Executa o login em um extrator.")
    login.add_argument("--job", dest="job", help="Job que abrirá o login; usa o primeiro se omitido.")
    login.add_argument("--skip-driver-check", action="store_true")
    login.add_argument("--dry-run", action="store_true")

    subparsers.add_parser("list-jobs", help="Lista jobs, scripts e horários configurados.")
    configure = subparsers.add_parser("configure-schedules", help="Abre o formulário de frequência por automação.")
    configure.add_argument("--if-needed", action="store_true", help="Abre somente se a configuração inicial ainda não foi concluída.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logger = configure_logging(debug=args.debug)
    try:
        settings = load_settings(args.config)
        logger = configure_logging(settings.orchestration_log, debug=args.debug)
        if args.subcommand == "configure-schedules":
            saved = configure_schedules(settings.config_path, settings.jobs, if_needed=args.if_needed)
            logger.info("Frequências salvas." if saved else "Configuração cancelada; nenhuma automação foi iniciada.")
            return 0 if saved else 3
        orchestrator = Orchestrator(settings, logger)

        if args.subcommand == "doctor":
            details = orchestrator.driver_guard.ensure(
                repair=args.repair,
                test_session=not args.no_session_test,
            )
            logger.info("Edge: %s", details["edge_binary"])
            logger.info("Versão do Edge: %s", format_version(details["edge_version"]))
            logger.info("Driver: %s", details["driver_path"])
            logger.info("Versão do driver: %s", format_version(details["driver_version"]))
            if details.get("authenticode"):
                logger.info("Assinatura do driver: %s", details["authenticode"])
            if details.get("session"):
                logger.info("Teste de sessão: aprovado.")
            return 0

        if args.subcommand == "list-jobs":
            if not settings.jobs:
                logger.warning("Nenhum job localizado.")
            for index, job in enumerate(settings.jobs, start=1):
                state = "habilitado" if job.enabled else "desabilitado"
                logger.info("%02d | %s | %s | %s %s %s | %s", index, job.name, state,
                            job.schedule.frequency, job.schedule.weekday if job.schedule.frequency == "weekly" else "",
                            job.schedule.time, job.script)
            logger.info("Destino dos arquivos finais: %s", settings.output_dir)
            logger.info("Horários: %s", ", ".join(settings.schedules) or "não configurados")
            return 0

        if args.subcommand == "run":
            return orchestrator.run(
                job_names=args.jobs,
                delay_seconds=args.delay_seconds,
                skip_driver_check=args.skip_driver_check,
                dry_run=args.dry_run,
                force=args.force,
            )

        if args.subcommand == "login":
            names = [args.job] if args.job else None
            return orchestrator.run(
                job_names=names,
                delay_seconds=0,
                skip_driver_check=args.skip_driver_check,
                dry_run=args.dry_run,
                action_override="login",
                first_only=args.job is None,
            )
        parser.error("Subcomando inválido.")
    except KeyboardInterrupt:
        logger.error("Execução interrompida pelo usuário.")
        return 130
    except (OrchestratorError, ScheduleError) as exc:
        logger.error("Falha: %s", exc)
        if args.debug:
            logger.exception("Detalhes")
        return 2
    except Exception as exc:
        logger.error("Falha inesperada: %s", exc)
        if args.debug:
            logger.exception("Detalhes")
        return 2
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(main())
