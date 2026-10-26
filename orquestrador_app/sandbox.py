"""A test installation owns one selected folder and never adopts production paths."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from . import VERSION
from .config import KNOWN, Config, defaults
from .io import atomic_json, read_json
from .paths import Paths
from .resources import source_root

OWNER = "orquestrador-test-v1"
MARKER = "instalacao-teste.json"


def locator() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
    return base / "Orquestrador-Teste" / "ultima-instalacao.json"


def locate() -> Paths:
    file = locator()
    if file.is_file():
        value = read_json(file)
        candidate = Paths.user(value.get("root"))
        marker = candidate.root / MARKER
        if marker.is_file() and read_json(marker).get("owner") == OWNER:
            return candidate
    return Paths.user(file.parent / "launcher")


def remember(paths: Paths) -> None:
    atomic_json(locator(), {"owner": OWNER, "root": str(paths.root), "version": VERSION})


def check_location(folder: Path) -> Paths:
    if not folder.is_absolute() or folder == Path(folder.anchor) or folder == Path.home():
        raise ValueError("Escolha uma pasta exclusiva para a instalação de teste.")
    if folder.is_symlink():
        raise ValueError("A pasta de teste não pode ser um atalho de diretório.")
    folder = folder.expanduser().resolve()
    marker = folder / MARKER
    if folder.exists():
        if not folder.is_dir():
            raise ValueError("O destino não é uma pasta.")
        if marker.is_file():
            if read_json(marker).get("owner") != OWNER:
                raise ValueError("A pasta pertence a outra instalação.")
        elif any(folder.iterdir()):
            raise ValueError(
                "Esta pasta contém arquivos existentes. Selecione uma pasta vazia ou crie "
                "uma subpasta de teste. Os arquivos originais serão preservados."
            )
    return Paths.user(folder)


def confined(paths: Paths, value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    root = paths.root.resolve()
    if not path.is_absolute() or not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise ValueError(f"{label} deve ficar dentro da pasta da instalação de teste: {root}")
    return path


def validate_isolation(paths: Paths, config: Config) -> None:
    if not config.test_mode:
        raise ValueError("Esta edição executa somente configurações de teste isoladas.")
    expected_code = (
        source_root() if config.execution_profile == "portable_gui" else paths.root / "app"
    )
    if Path(config.install_root).resolve() != expected_code.resolve():
        if config.execution_profile == "portable_gui":
            raise ValueError(
                "O caminho dos scripts mudou. Peça à TI para revisar o atalho, a tarefa e a configuração."
            )
        raise ValueError("O aplicativo de teste deve ficar em app na pasta escolhida no wizard.")
    for key in ("profile", "driver", "downloads", "logs"):
        confined(paths, getattr(config, key), key)
    for key in ("managed_path", "selenium_cache", "cache_dir", "backup_dir"):
        if config.driver_options.get(key):
            confined(paths, config.driver_options[key], f"driver.{key}")
    for job in config.routines:
        reserved = {
            "--clients-dir",
            "--procedures-dir",
            "--output-dir",
            "--history-csv",
            "--destination",
            "--work-dir",
            "--user-data-dir",
            "--log-file",
            "--input",
        }
        if job.id in KNOWN and any(
            str(argument).split("=", 1)[0] in reserved
            for argument in [*job.options, *job.arguments]
        ):
            raise ValueError(
                f"Os caminhos de {job.label} são gerenciados pelo ambiente de teste; use os seletores de pastas."
            )
        if job.target:
            confined(paths, job.target, f"Destino de {job.label}")
        if job.working_directory:
            confined(paths, job.working_directory, f"Pasta de trabalho de {job.label}")


def prepare_config(paths: Paths, source: Config | None = None) -> Config:
    config = copy.deepcopy(source or defaults(paths, source_root()))
    config.test_mode = True
    config.install_schedules = False
    config.scheduling_paused = True
    config.install_root = str(
        source_root() if config.execution_profile == "portable_gui" else paths.root / "app"
    )
    config.profile = str(paths.root / "profiles/Edge-Teste")
    config.driver = str(paths.root / "cache/driver/msedgedriver.exe")
    config.driver_options = {
        **config.driver_options,
        "managed_path": config.driver,
        "selenium_cache": str(paths.root / "cache/selenium"),
    }
    config.downloads = str(paths.root / "downloads")
    config.logs = str(paths.root / "logs")
    config.legacy = {"test_import": True} if source and source.legacy else {}
    for job in config.routines:
        known = KNOWN.get(job.id)
        name = known[2] if known else (Path(job.target).name if job.target else "")
        subfolder = known[1] if known else job.id
        if name:
            job.target = str(paths.root / "relatorios" / subfolder / name)
        job.environment = {}
        job.working_directory = ""
        # No profile/destination arguments from a production configuration are carried over.
        if source:
            job.options = []
            job.arguments = []
            if job.id not in KNOWN:
                job.enabled = False
    validate_isolation(paths, config)
    return config


def mark(paths: Paths) -> dict[str, Any]:
    value = {"owner": OWNER, "version": VERSION, "mode": "teste", "root": str(paths.root)}
    atomic_json(paths.root / MARKER, value)
    return value
