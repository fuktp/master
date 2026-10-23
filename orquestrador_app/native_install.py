"""Transactional deployment shared by the native wizard and external updater."""

from __future__ import annotations

import datetime as dt
import getpass
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from .config import Config, load, save, validate
from .io import Lock, atomic_json, digest, read_json
from .paths import Paths, check_directory
from .sandbox import MARKER, check_location, mark, remember, validate_isolation
from .store import Store
from .tasks import WindowsTasks, current_user
from .uninstallation import (
    PUBLIC_ENTRIES,
    WindowsRegistration,
    check_entry,
    cleanup_plan,
    install_entries,
    restore_entries,
    stop_monitor,
)
from .windows_hosts import executable

PACKAGE_OWNER = "orquestrador-native-package-v1"
SNAPSHOT_OWNER = "orquestrador-native-backup-v1"
TERMINAL = {"committed", "rolled_back"}


def validate_health_report(value: dict[str, Any], expected_version: str) -> None:
    if value.get("health") != "ok" or value.get("version") != expected_version:
        raise RuntimeError(
            "Health check ou versão do runtime diverge do pacote; ativação recusada."
        )


def verify_release(folder: Path) -> dict[str, Any]:
    folder = folder.resolve()
    record = read_json(folder / "release.json")
    if record.get("owner") != PACKAGE_OWNER or record.get("distribution") != "native-scripts":
        raise ValueError("Pacote de scripts não reconhecido.")
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+-]{0,63}", str(record.get("version", ""))):
        raise ValueError("Versão inválida no manifesto.")
    required = {
        "runtime/pythonw.exe",
        "src/desktop_entry.py",
        "native/wizard.ps1",
        "native/Update.ps1",
    }
    files = record.get("files", {})
    if record.get("windows_process_hosts"):
        from .windows_hosts import HOST_DESCRIPTIONS

        required.update("runtime/" + name for name in HOST_DESCRIPTIONS)
        required.update(
            {
                "native/Entrada.ps1",
                "native/Desinstalar.ps1",
                "native/Entrada.vbs",
                "native/Entrada.bat",
            }
        )
    if record.get("shared_translation_catalog"):
        required.add("native/locales.json")
    if not required.issubset(files) or len(files) > 20000:
        raise ValueError("Pacote incompleto ou com manifesto inválido.")
    for name, expected in files.items():
        path = folder / name
        if (
            ":" in name
            or "\\" in name
            or not path.resolve().is_relative_to(folder)
            or path.is_symlink()
            or digest(path) != expected
        ):
            raise ValueError(f"Integridade do pacote divergente: {name}")
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    if actual != set(files) | {"release.json"}:
        raise ValueError("Arquivos não declarados no pacote.")
    return record


def hidden_run(arguments: list[str], **options: Any) -> subprocess.CompletedProcess[Any]:
    if sys.platform == "win32":
        options["creationflags"] = 0x08000000
    try:
        return subprocess.run(arguments, shell=False, **options)
    except OSError as exc:
        code = getattr(exc, "winerror", None) or exc.errno
        raise RuntimeError(
            f"Falha ao iniciar processo. Código nativo: {code}\n"
            f"Executável: {arguments[0]}\nPasta de trabalho: {options.get('cwd', '')}\n"
            f"Motivo informado pelo sistema: {exc.strerror or exc}\n"
            "Verifique as permissões e os registros de proteção/políticas do Windows para este executável."
        ) from exc


def check_windows_hosts(release: Path) -> None:
    """Probe the declared application hosts without starting the GUI, monitor or extraction."""
    from .windows_hosts import HOST_DESCRIPTIONS

    if sys.platform != "win32":
        raise RuntimeError("A verificação de execução dos hosts exige Windows real.")
    if not read_json(release / "release.json").get("windows_process_hosts"):
        return  # Older packages have only the original interpreter.
    for name in HOST_DESCRIPTIONS:
        result = hidden_run(
            [str(release / "runtime" / name), "-B", "-c", "pass"],
            cwd=release / "src",
            capture_output=True,
            timeout=30,
        )
        if result.returncode:
            raise RuntimeError(
                f"O host {name} não concluiu a verificação de execução "
                f"(código {result.returncode}). Nenhuma extração foi iniciada."
            )


class WindowsLinks:
    def __init__(self, paths: Paths):
        self.paths = paths

    def locations(self) -> list[Path]:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        return [
            Path(shell.SpecialFolders(name)) / "Orquestrador - Teste.lnk"
            for name in ("Desktop", "Programs")
        ]

    def snapshot(self, folder: Path) -> None:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            for index, path in enumerate(self.locations()):
                if path.is_file():
                    shutil.copy2(path, folder / f"shortcut-{index}.lnk")
        finally:
            pythoncom.CoUninitialize()

    def install(self) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            from .windows_identity import launch_icon, set_shortcut_identity

            icon_file = launch_icon(self.paths)
            if not icon_file.is_file():
                raise ValueError("Ícone CAIO ausente no lançador instalado.")
            shell = win32com.client.Dispatch("WScript.Shell")
            for path in self.locations():
                shortcut = shell.CreateShortcut(str(path))
                if path.exists() and shortcut.TargetPath:
                    target = Path(shortcut.TargetPath).resolve()
                    if not target.is_relative_to(self.paths.root.resolve()):
                        raise ValueError(
                            "Há um atalho de outra instalação com o mesmo nome; ele foi preservado."
                        )
                public = self.paths.root / "02 - Abrir CAIO.vbs"
                shortcut.TargetPath = str(
                    public if public.is_file() else self.paths.root / "launch/Iniciar.vbs"
                )
                shortcut.WorkingDirectory = str(self.paths.root)
                shortcut.Description = "Orquestrador • ambiente de teste isolado"
                shortcut.IconLocation = str(icon_file) + ",0"
                shortcut.Save()
                set_shortcut_identity(path, self.paths)
        finally:
            pythoncom.CoUninitialize()

    def restore(self, folder: Path) -> None:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            for index, path in enumerate(self.locations()):
                previous = folder / f"shortcut-{index}.lnk"
                if previous.is_file():
                    shutil.copy2(previous, path)
                elif path.is_file():
                    import win32com.client

                    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
                    if Path(link.TargetPath).resolve().is_relative_to(self.paths.root.resolve()):
                        path.unlink()
        finally:
            pythoncom.CoUninitialize()


class NativeInstaller:
    def __init__(
        self,
        paths: Paths,
        tasks: Any = None,
        links: Any = None,
        health: Callable[[Path], None] | None = None,
    ):
        self.paths = paths
        self.tasks = tasks if tasks is not None else WindowsTasks(paths)
        self.links = links if links is not None else WindowsLinks(paths)
        self.registration = WindowsRegistration(paths)
        self.health = health or self.check_health
        self.pointer = paths.root / "installation.json"
        self.journal = paths.root / "state/native-transaction.json"

    def check_health(self, release: Path) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Health check do runtime Windows exige Windows; não foi simulado.")
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        report = self.paths.root / "cache" / f"health-{uuid.uuid4()}.json"
        try:
            result = hidden_run(
                [
                    str(executable(release)),
                    "-B",
                    "-m",
                    "orquestrador_app",
                    "--health-check",
                    "--health-output",
                    str(report),
                ],
                env=environment,
                capture_output=True,
                timeout=120,
                cwd=release / "src",
            )
            value = read_json(report) if report.is_file() else {}
            if result.returncode or value.get("health") != "ok":
                raise RuntimeError(
                    "Verificação interna falhou: " + str(value.get("error", "relatório ausente"))
                )
            validate_health_report(value, read_json(release / "release.json")["version"])
        finally:
            report.unlink(missing_ok=True)

    def snapshot(self, folder: Path) -> dict[str, Any]:
        folder.mkdir(parents=True, exist_ok=False)
        atomic_json(folder / "uninstall-registration.json", self.registration.snapshot())
        for name in ("uninstalled.json", "uninstall-cleanup.json"):
            source = self.paths.root / "state" / name
            if source.is_file():
                (folder / "uninstall-state").mkdir(exist_ok=True)
                shutil.copy2(source, folder / "uninstall-state" / name)
        for name in PUBLIC_ENTRIES:
            entry = self.paths.root / name
            if entry.is_file():
                (folder / "root-entries").mkdir(exist_ok=True)
                shutil.copy2(entry, folder / "root-entries" / name)
        for name in ("config.json", "installation.json", MARKER, "update.json"):
            if (self.paths.root / name).is_file():
                shutil.copy2(self.paths.root / name, folder / name)
        if self.paths.database.is_file():
            Store(self.paths.database).snapshot(folder / "history.sqlite3")
        for name in ("extras", "launch"):
            source = self.paths.root / name
            if source.exists():
                if (
                    source.is_symlink()
                    or not source.resolve().is_relative_to(self.paths.root.resolve())
                    or any(p.is_symlink() for p in source.rglob("*"))
                ):
                    raise ValueError("Backup recusou link de diretório em componentes gerenciados.")
                shutil.copytree(source, folder / name)
        if self.pointer.is_file():
            pointer = read_json(self.pointer)
            if pointer.get("distribution") == "native-scripts":
                release = Path(pointer["release"])
                if not release.resolve().is_relative_to(
                    (self.paths.root / "app/versions").resolve()
                ) or any(p.is_symlink() for p in release.rglob("*")):
                    raise ValueError("Versão anterior fora do diretório gerenciado.")
                if release.is_dir():
                    shutil.copytree(release, folder / "release")
                else:
                    atomic_json(folder / "release-absent.json", {"release": str(release)})
            elif pointer.get("executable"):
                executable = Path(pointer["executable"])
                if executable.is_file():
                    shutil.copy2(executable, folder / "previous.exe")
        task = self.tasks.export()
        if task:
            (folder / "task.xml").write_text(task, encoding="utf-8")
        self.links.snapshot(folder)
        files = {
            p.relative_to(folder).as_posix(): digest(p) for p in folder.rglob("*") if p.is_file()
        }
        record = {
            "owner": SNAPSHOT_OWNER,
            "files": files,
            "had_task": bool(task),
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        atomic_json(folder / "manifest.json", record)
        self.verify_snapshot(folder)
        return record

    @staticmethod
    def verify_snapshot(folder: Path) -> dict[str, Any]:
        record = read_json(folder / "manifest.json")
        if record.get("owner") != SNAPSHOT_OWNER:
            raise ValueError("Backup de scripts não reconhecido.")
        for name, expected in record["files"].items():
            path = folder / name
            if (
                not path.resolve().is_relative_to(folder.resolve())
                or path.is_symlink()
                or digest(path) != expected
            ):
                raise ValueError("Integridade do backup divergente.")
        return record

    def _restore(self, folder: Path) -> None:
        record = self.verify_snapshot(folder)
        report: dict[str, Any] = {
            "backup": str(folder),
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "components": [],
            "complete": False,
        }
        failures = []
        try:
            for name in ("config.json", "installation.json", MARKER, "update.json"):
                target = self.paths.root / name
                if (folder / name).is_file():
                    atomic_json(target, read_json(folder / name))
                else:
                    target.unlink(missing_ok=True)
            for name in ("uninstalled.json", "uninstall-cleanup.json"):
                saved_state = folder / "uninstall-state" / name
                current_state = self.paths.root / "state" / name
                if saved_state.is_file():
                    atomic_json(current_state, read_json(saved_state))
                else:
                    current_state.unlink(missing_ok=True)
            report["components"].append({"component": "configuration", "restored": True})
        except Exception as exc:
            failures.append("configuration: " + str(exc))
            report["components"].append(
                {
                    "component": "configuration",
                    "restored": False,
                    "error": str(exc),
                    "intervention_required": True,
                }
            )
        try:
            for suffix in ("-wal", "-shm"):
                Path(str(self.paths.database) + suffix).unlink(missing_ok=True)
            if (folder / "history.sqlite3").is_file():
                shutil.copy2(folder / "history.sqlite3", self.paths.database)
            else:
                self.paths.database.unlink(missing_ok=True)
            report["components"].append({"component": "database", "restored": True})
        except Exception as exc:
            failures.append("database: " + str(exc))
            report["components"].append(
                {
                    "component": "database",
                    "restored": False,
                    "error": str(exc),
                    "intervention_required": True,
                }
            )
        try:
            for name in ("extras", "launch"):
                target = self.paths.root / name
                if target.exists():
                    shutil.rmtree(target)
                if (folder / name).is_dir():
                    shutil.copytree(folder / name, target)
            restore_entries(self.paths, folder)
            report["components"].append({"component": "scripts_and_launchers", "restored": True})
        except Exception as exc:
            failures.append("scripts_and_launchers: " + str(exc))
            report["components"].append(
                {
                    "component": "scripts_and_launchers",
                    "restored": False,
                    "error": str(exc),
                    "intervention_required": True,
                }
            )
        try:
            if self.pointer.is_file():
                pointer = read_json(self.pointer)
                if pointer.get("distribution") == "native-scripts":
                    release = Path(pointer["release"])
                    if not release.resolve().is_relative_to(
                        (self.paths.root / "app/versions").resolve()
                    ):
                        raise ValueError("Versão de restauração fora da instalação.")
                    saved = {
                        name.removeprefix("release/"): checksum
                        for name, checksum in record["files"].items()
                        if name.startswith("release/")
                    }
                    intact = release.is_dir() and all(
                        (release / name).is_file() and digest(release / name) == checksum
                        for name, checksum in saved.items()
                    )
                    if not intact and not (folder / "release-absent.json").is_file():
                        if release.exists():
                            shutil.rmtree(release)
                        shutil.copytree(folder / "release", release)
                elif (folder / "previous.exe").is_file():
                    executable = Path(pointer["executable"])
                    executable.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(folder / "previous.exe", executable)
            report["components"].append({"component": "application_version", "restored": True})
        except Exception as exc:
            failures.append("application_version: " + str(exc))
            report["components"].append(
                {
                    "component": "application_version",
                    "restored": False,
                    "error": str(exc),
                    "intervention_required": True,
                }
            )
        try:
            if record["had_task"]:
                self.tasks.register_xml((folder / "task.xml").read_text(encoding="utf-8"))
            else:
                self.tasks.remove()
            report["components"].append({"component": "scheduled_task", "restored": True})
        except Exception as exc:
            failures.append("scheduled_task: " + str(exc))
            report["components"].append(
                {
                    "component": "scheduled_task",
                    "restored": False,
                    "error": str(exc),
                    "intervention_required": True,
                }
            )
        try:
            self.links.restore(folder)
            report["components"].append({"component": "shortcuts", "restored": True})
        except Exception as exc:
            failures.append("shortcuts: " + str(exc))
            report["components"].append(
                {
                    "component": "shortcuts",
                    "restored": False,
                    "error": str(exc),
                    "intervention_required": True,
                }
            )
        try:
            registration = folder / "uninstall-registration.json"
            self.registration.restore(read_json(registration) if registration.is_file() else None)
            report["components"].append({"component": "windows_registration", "restored": True})
        except Exception as exc:
            failures.append("windows_registration: " + str(exc))
            report["components"].append(
                {
                    "component": "windows_registration",
                    "restored": False,
                    "error": str(exc),
                    "intervention_required": True,
                }
            )
        report["complete"] = not failures
        atomic_json(self.paths.root / "state/recovery-report.json", report)
        if failures:
            raise RuntimeError("Recuperação parcial: " + "; ".join(failures))

    def recover(self) -> str:
        if not self.journal.is_file():
            return ""
        state = read_json(self.journal)
        if state["status"] in TERMINAL:
            return ""
        with (
            Lock(self.paths.root / "state/interface.lock"),
            Lock(self.paths.maintenance_lock),
            Lock(self.paths.lock),
        ):
            try:
                self._restore(Path(state["backup"]))
                state["status"] = "rolled_back"
                atomic_json(self.journal, state)
                return "Transação interrompida revertida; versão, configuração, estado, tarefas e atalhos restaurados."
            except Exception as exc:
                state.update(status="rollback_failed", rollback_error=str(exc))
                atomic_json(self.journal, state)
                raise

    def install(
        self,
        source: Path,
        config: Config,
        progress: Callable[[str], None] = lambda _: None,
        fault: str = "",
        cancelled: Callable[[], bool] = lambda: False,
    ) -> Path:
        package = verify_release(source)
        validate(config)
        validate_isolation(self.paths, config)
        check_location(self.paths.root)
        self.paths.ensure()
        if not (self.paths.root / MARKER).is_file():
            mark(self.paths)
        required = sum((source / name).stat().st_size for name in package["files"])
        check_directory(self.paths.root, min_free=required * 3 + 100_000_000)
        identifier = str(uuid.uuid4())
        release = self.paths.root / "app/versions" / f"{package['version']}-{identifier[:8]}"
        backup = self.paths.root / "backups/app" / identifier

        def checkpoint(message: str) -> None:
            progress(message)
            if cancelled():
                raise RuntimeError(
                    "Instalação cancelada no checkpoint seguro; alterações revertidas."
                )

        with (
            Lock(self.paths.root / "state/interface.lock"),
            Lock(self.paths.maintenance_lock),
            Lock(self.paths.lock),
        ):
            if sys.platform == "win32" and package.get("windows_process_hosts"):
                checkpoint("Verificando execução dos hosts CAIO antes de copiar o runtime")
                check_windows_hosts(source)
            if (
                os.name == "nt"
                and config.install_schedules
                and isinstance(self.tasks, WindowsTasks)
            ):
                checkpoint(
                    "Verificando registro, consulta e remoção de uma tarefa temporária desabilitada"
                )
                self.tasks.preflight(current_user())
            checkpoint(
                "Criando backup verificável de versão, configuração, histórico, tarefas e atalhos"
            )
            self.snapshot(backup)
            state = {
                "owner": PACKAGE_OWNER,
                "status": "preparing",
                "id": identifier,
                "backup": str(backup),
                "new": str(release),
                "recovery_release": str(source.resolve()),
            }
            atomic_json(self.journal, state)
            try:
                checkpoint("Copiando o runtime privado e a aplicação para uma nova pasta de versão")
                release.mkdir(parents=True, exist_ok=False)
                entries = [*package["files"], "release.json"]
                for index, name in enumerate(entries):
                    if cancelled():
                        raise RuntimeError(
                            "Instalação cancelada durante cópia; versão anterior preservada."
                        )
                    target = release / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / name, target)
                    if index % 500 == 0:
                        progress(f"Arquivos copiados: {index + 1} / {len(entries)}")
                verify_release(release)
                if fault == "copy":
                    raise RuntimeError("Falha induzida após cópia.")
                checkpoint(
                    "Verificando imports, SQLite, interface e contratos dos cinco extratores; sem rede"
                )
                self.health(release)
                if fault == "health":
                    raise RuntimeError("Falha induzida no health check.")
                checkpoint("Preservando configurações, frequência, scripts adicionais e estado")
                save(self.paths, config)
                from .script_versions import capture

                for routine in config.routines:
                    if not routine.script.startswith("bundle:") and Path(routine.script).is_file():
                        capture(self.paths, routine)
                Store(self.paths.database)
                if fault == "migration":
                    raise RuntimeError("Falha induzida na migração.")
                launch = self.paths.root / "launch"
                launch.mkdir(exist_ok=True)
                for file in (release / "native").iterdir():
                    if file.is_file():
                        temporary = launch / (file.name + ".new")
                        shutil.copy2(file, temporary)
                        temporary.replace(launch / file.name)
                if package.get("public_entries"):
                    install_entries(self.paths, release / "native")
                else:
                    restore_entries(self.paths, release / "no-root-entries")
                shutil.copy2(release / "assets/orquestrador.ico", launch / "orquestrador.ico")
                from .windows_identity import launch_icon

                shutil.copy2(release / "assets/orquestrador.ico", launch_icon(self.paths))
                checkpoint("Registrando atalhos próprios na Área de Trabalho e no Menu Iniciar")
                self.links.install()
                launcher = launch / "Iniciar.vbs"
                user = os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser()
                if config.install_schedules:
                    checkpoint("Registrando e conferindo a tarefa do monitor na sessão do usuário")
                    self.tasks.install(launcher, user)
                elif self.tasks.export():
                    self.tasks.remove()
                state["status"] = "activating"
                atomic_json(self.journal, state)
                atomic_json(
                    self.pointer,
                    {
                        "owner": "orquestrador-app-v1",
                        "distribution": "native-scripts",
                        "version": package["version"],
                        "release": str(release),
                        "executable": str(executable(release)),
                        "launcher": str(launcher),
                        "backup": str(backup),
                        "manifest_sha256": digest(release / "release.json"),
                    },
                )
                if package.get("public_entries"):
                    self.registration.install(str(package["version"]))
                else:
                    self.registration.remove()
                (self.paths.root / "state/uninstalled.json").unlink(missing_ok=True)
                (self.paths.root / "state/uninstall-cleanup.json").unlink(missing_ok=True)
                if fault == "activation":
                    raise RuntimeError("Falha induzida após ativação.")
                checkpoint("Validando configuração, lançamento e tarefa após ativação")
                load(self.paths)
                self.health(release)
                if config.install_schedules and not self.tasks.export():
                    raise RuntimeError("Monitor próprio não encontrado após registro.")
                if fault == "post":
                    raise RuntimeError("Falha induzida na verificação final.")
                atomic_json(
                    self.paths.root / "versionamento" / f"{package['version']}-{identifier}.json",
                    {
                        "version": package["version"],
                        "distribution": "native-scripts",
                        "release": str(release),
                        "manifest_sha256": digest(release / "release.json"),
                        "backup": str(backup),
                        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    },
                )
                state["status"] = "committed"
                atomic_json(self.journal, state)
                remember(self.paths)
                progress("Instalação concluída; versão anterior e dados preservados")
                return launcher
            except Exception as exc:
                progress("Revertendo a transação para a versão e o estado anteriores")
                try:
                    self._restore(backup)
                    state.update(status="rolled_back", error=str(exc))
                except Exception as rollback_error:
                    state.update(
                        status="rollback_failed", error=str(exc), rollback_error=str(rollback_error)
                    )
                atomic_json(self.journal, state)
                if state["status"] == "rollback_failed":
                    raise RuntimeError(
                        "A reversão exige recuperação; backup preservado: " + str(backup)
                    ) from exc
                raise

    def rollback(self, folder: Path) -> None:
        if not folder.resolve().is_relative_to((self.paths.root / "backups/app").resolve()):
            raise ValueError("Backup fora do diretório gerenciado.")
        with (
            Lock(self.paths.root / "state/interface.lock"),
            Lock(self.paths.maintenance_lock),
            Lock(self.paths.lock),
        ):
            checkpoint = self.paths.root / "backups/app" / ("before-rollback-" + str(uuid.uuid4()))
            self.snapshot(checkpoint)
            try:
                self._restore(folder)
            except Exception:
                self._restore(checkpoint)
                raise

    def uninstall(
        self,
        *,
        remove_program_files: bool = False,
        progress: Callable[[str], None] = lambda _: None,
    ) -> dict[str, Any]:
        with (
            Lock(self.paths.root / "state/interface.lock"),
            Lock(self.paths.maintenance_lock),
            Lock(self.paths.lock),
        ):
            if not self.pointer.is_file():
                return {"status": "already_uninstalled"}
            check_location(self.paths.root)
            pointer = read_json(self.pointer)
            if pointer.get("distribution") != "native-scripts":
                raise ValueError("Instalação de scripts não reconhecida.")
            progress("Encerrando somente o monitor desta instalação…")
            stop_monitor(self.paths)
            with Lock(self.paths.root / "state/monitor.lock"):
                return self._uninstall_locked(remove_program_files, progress)

    def _uninstall_locked(
        self, remove_program_files: bool, progress: Callable[[str], None]
    ) -> dict[str, Any]:
        progress("Preservando configuração, histórico, scripts e versão em backup…")
        backup = self.paths.root / "backups/app" / ("before-uninstall-" + str(uuid.uuid4()))
        self.snapshot(backup)
        try:
            plan = cleanup_plan(self.paths) if remove_program_files else None
            progress("Removendo tarefa, atalhos e registro próprios do CAIO…")
            self.tasks.remove()
            empty = self.paths.root / "cache" / str(uuid.uuid4())
            empty.mkdir()
            try:
                self.links.restore(empty)
            finally:
                empty.rmdir()
            self.registration.remove()
            for name, action in PUBLIC_ENTRIES.items():
                if action == "open":
                    check_entry(self.paths.root / name)
                    (self.paths.root / name).unlink(missing_ok=True)
            self.pointer.unlink()
            if plan is not None:
                atomic_json(self.paths.root / "state/uninstall-cleanup.json", plan)
            else:
                (self.paths.root / "state/uninstall-cleanup.json").unlink(missing_ok=True)
            result = {
                "status": "uninstalled",
                "backup": str(backup),
                "cleanup_pending": bool(plan and plan["releases"]),
                "preserved": ["configuration", "history", "reports", "scripts", "backups"],
                "program_files_requested": remove_program_files,
            }
            atomic_json(self.paths.root / "state/uninstalled.json", result)
            return result
        except Exception as exc:
            try:
                self._restore(backup)
            except Exception as recovery_error:
                raise RuntimeError(
                    "Desinstalação incompleta; recuperação exige intervenção. Backup: "
                    + str(backup)
                ) from recovery_error
            raise exc


def installer_for(paths: Paths) -> Any:
    pointer = paths.root / "installation.json"
    if pointer.is_file() and read_json(pointer).get("distribution") == "native-scripts":
        return NativeInstaller(paths)
    from .install import Installer

    return Installer(paths)
