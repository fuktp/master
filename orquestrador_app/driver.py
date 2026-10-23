from __future__ import annotations

import ast
import dataclasses
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .config import Config
from .io import Lock, atomic_json
from .paths import Paths
from .resources import script_path


def guard(paths: Paths, config: Config) -> Any:
    import pipefy_orchestrator as legacy

    temporary = paths.root / "cache/driver-compat.config.json"
    atomic_json(
        temporary,
        {
            "schema_version": 1,
            "project_root": str(paths.root / "extras"),
            "output_dir": str(paths.root / "cache/diagnostic"),
            "runtime_dir": str(paths.root / "cache/driver-health"),
            "logs_dir": config.logs,
            "jobs": [],
            "driver": {
                **config.driver_options,
                "managed_path": config.driver,
                "selenium_cache": config.driver_options.get(
                    "selenium_cache", str(paths.root / "cache/selenium")
                ),
                "verify_authenticode": True,
                "adapt_script_driver_paths": False,
            },
        },
    )

    class DesktopGuard(legacy.DriverGuard):
        def _resolve_driver_with_selenium_manager(self, edge: Path) -> Path:
            browser = self.edge_version(edge)
            self.candidates_checked = []
            self.logger.info(
                "Procurando EdgeDriver já instalado e compatível com o Edge %s.", browser
            )
            for candidate in candidates(paths, config):
                try:
                    # Validate trust before running a discovered executable.
                    self.authenticode_status(candidate)
                    version = self.driver_version(candidate)
                    compatible = legacy.versions_compatible(browser, version)
                    self.candidates_checked.append(
                        {"path": str(candidate), "compatible": compatible}
                    )
                    if compatible:
                        self.logger.info("EdgeDriver compatível encontrado: %s", candidate)
                        return candidate
                except Exception as exc:
                    self.candidates_checked.append({"path": str(candidate), "error": str(exc)})
            self.logger.info(
                "Nenhum driver local compatível; obtendo uma versão pelo resolvedor oficial."
            )
            resolved = super()._resolve_driver_with_selenium_manager(edge)
            self.authenticode_status(resolved)
            if not legacy.versions_compatible(browser, self.driver_version(resolved)):
                self.logger.warning(
                    "Resolvedor retornou versão incompatível; consultando o mirror oficial."
                )
                resolved = self._download_driver_from_official_mirror(browser)
                self.authenticode_status(resolved)
            return resolved

        def inspect(self) -> dict[str, Any]:
            # A failed trust check is a repairable condition, not an ignored warning.
            details = super().inspect()
            if os.name == "nt" and details.get("authenticode") != "Valid":
                details["compatible"] = False
            return details

        @staticmethod
        def _powershell_output(command: str, environment: Mapping[str, str]) -> str:
            executable = shutil.which("powershell.exe")
            if not executable:
                raise RuntimeError("PowerShell do Windows indisponível para diagnóstico de versão.")
            result = subprocess.run(
                [executable, "-NoProfile", "-NonInteractive", "-Command", command],
                env={**os.environ, **environment},
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            if result.returncode:
                raise RuntimeError("Falha na consulta de versão pelo Windows.")
            return result.stdout.strip()

        def authenticode_status(self, path: Any) -> Any:
            status = super().authenticode_status(path)
            if os.name == "nt" and status != "Valid":
                raise legacy.OrchestratorError(
                    f"Verificação de assinatura do EdgeDriver não aprovada: {status}"
                )
            return status

    settings = legacy.load_settings(temporary)
    settings = dataclasses.replace(settings, python_executable="")
    return DesktopGuard(settings, logging.getLogger("desktop.driver"))


def candidates(paths: Paths, config: Config) -> list[Path]:
    """Search configured locations, PATH, Selenium caches and common user folders.

    ponytail: bounded local search, no whole-disk/network scan; add a search root
    in driver_options.search_paths for a nonstandard installation.
    """
    found = [Path(config.driver)] if config.driver else []
    for name in ("MSEDGEDRIVER_PATH", "PIPEFY_EDGE_DRIVER_PATH", "SE_EDGEDRIVER"):
        if os.environ.get(name):
            found.append(Path(os.environ[name]))
    in_path = shutil.which("msedgedriver.exe")
    if in_path:
        found.append(Path(in_path))
    script_roots = []
    for job in config.routines:
        source = script_path(job.script)
        script_roots.append(source.parent)
        if source.is_file():
            try:
                tree = ast.parse(source.read_text(encoding="utf-8-sig"))
                found.extend(
                    Path(node.value)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value.casefold().endswith("msedgedriver.exe")
                )
            except (OSError, UnicodeError, SyntaxError):
                logging.getLogger("desktop.driver").debug(
                    "Sem caminhos literais de driver em %s", source
                )
    roots = [
        *[Path(p) for p in config.driver_options.get("search_paths", [])],
        *script_roots,
        paths.root / "cache",
        Path(config.driver_options.get("selenium_cache", str(paths.root / "cache/selenium"))),
        Path.home() / ".cache/selenium",
        Path.home() / "Downloads",
        Path.home() / "Desktop",
    ]
    if os.name == "nt":
        drive = Path(os.environ.get("SystemDrive", "C:") + "/")
        roots += [
            drive / name
            for name in ("WebDriver", "WebDrivers", "Selenium", "Drivers", "msedgedriver")
        ]
        for key in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
            if os.environ.get(key):
                roots += [Path(os.environ[key]) / "Desktop", Path(os.environ[key]) / "Downloads"]
    for root in dict.fromkeys(roots):
        if str(root).startswith(("\\\\", "//")):
            continue
        if root.is_file():
            found.append(root)
            continue
        visited = 0
        for directory, subdirs, files in os.walk(root, followlinks=False):
            visited += 1
            if visited > 3000:
                break
            subdirs[:] = [
                d
                for d in subdirs
                if not d.startswith(".") and d not in {"node_modules", "__pycache__", ".venv"}
            ]
            if len(Path(directory).relative_to(root).parts) >= 4:
                subdirs.clear()
            found.extend(Path(directory) / f for f in files if f.casefold() == "msedgedriver.exe")
    return list(dict.fromkeys(p.resolve() for p in found if p.is_file()))


def diagnose(
    paths: Paths, config: Config, repair: bool = False, test_session: bool = True
) -> dict[str, Any]:
    with Lock(paths.root / "state/driver.lock"):
        if not config.driver:
            config.driver = str(paths.root / "cache/driver/msedgedriver.exe")
        instance = guard(paths, config)
        details = instance.ensure(repair=repair, test_session=test_session)
        if os.name == "nt":
            instance.authenticode_status(Path(config.driver))
        return {
            **dict(details),
            "candidates": getattr(instance, "candidates_checked", []),
            "status": "ready",
            "automatic_repair": repair,
        }
