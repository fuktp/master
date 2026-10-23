from __future__ import annotations

import datetime as dt
import getpass
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Callable

from . import VERSION, versioning
from .config import Config, load, save, validate
from .io import Lock, atomic_json, digest, read_json
from .paths import Paths, check_directory
from .resources import script_path
from .store import Store
from .tasks import WindowsTasks


class Installer:
    def __init__(
        self,
        paths: Paths,
        tasks: Any = None,
        health: Callable[[Path], None] | None = None,
        shortcut: Callable[[Path | None], None] | None = None,
    ):
        self.paths = paths
        self.tasks = tasks or WindowsTasks(paths)
        self.health = health or self.check_health
        self.shortcut = shortcut or self.write_shortcut
        self.journal = paths.root / "state/install-transaction.json"
        self.pointer = paths.root / "installation.json"
        self.legacy_source = ""

    def check_health(self, executable: Path) -> None:
        if os.name != "nt" or executable.read_bytes()[:2] != b"MZ":
            raise RuntimeError("A instalação exige um executável Windows gerado e íntegro.")
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        report = self.paths.root / "cache" / f"health-{uuid.uuid4()}.json"
        completed = subprocess.run(
            [str(executable), "--health-check", "--health-output", str(report)],
            env=environment,
            capture_output=True,
            timeout=90,
            creationflags=0x08000000,
        )
        result = read_json(report) if report.is_file() else {}
        report.unlink(missing_ok=True)
        if completed.returncode or result.get("health") != "ok":
            raise RuntimeError(
                "Health check interno da nova versão falhou; atualização revertida. "
                + str(result.get("error", "Resultado estruturado ausente."))
            )

    def write_shortcut(self, executable: Path | None) -> None:
        if os.name != "nt":
            raise RuntimeError("Atalho do produto disponível somente no Windows.")
        import pythoncom
        import win32com.client

        folder = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs"
        link = folder / ("Orquestrador - Teste.lnk" if self.is_test() else "Orquestrador.lnk")
        if executable is None:
            link.unlink(missing_ok=True)
            return
        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(str(link))
            shortcut.TargetPath = str(executable)
            shortcut.Arguments = subprocess.list2cmdline(["--data-root", str(self.paths.root)])
            shortcut.WorkingDirectory = str(executable.parent)
            shortcut.Description = "Orquestrador • versão de teste isolada"
            shortcut.Save()
        finally:
            pythoncom.CoUninitialize()

    def is_test(self) -> bool:
        return (self.paths.root / "instalacao-teste.json").is_file()

    def snapshot(self, folder: Path) -> dict[str, Any]:
        folder.mkdir(parents=True, exist_ok=False)
        files = {}
        for name in ("config.json", "installation.json", "instalacao-teste.json"):
            source = self.paths.root / name
            if source.is_file():
                shutil.copy2(source, folder / name)
                files[name] = digest(folder / name)
        if self.pointer.is_file():
            current = read_json(self.pointer)
            application = Path(current.get("executable", ""))
            if application.is_file():
                (folder / "application").mkdir()
                shutil.copy2(application, folder / "application/Orquestrador.exe")
                files["application/Orquestrador.exe"] = digest(
                    folder / "application/Orquestrador.exe"
                )
        if self.paths.database.is_file():
            Store(self.paths.database).snapshot(folder / "history.sqlite3")
            files["history.sqlite3"] = digest(folder / "history.sqlite3")
        extras = self.paths.root / "extras"
        if extras.is_dir():
            shutil.copytree(extras, folder / "extras", symlinks=False)
            for source in (folder / "extras").rglob("*"):
                if source.is_file():
                    files[str(source.relative_to(folder))] = digest(source)
        task = self.tasks.export()
        if task:
            (folder / "task.xml").write_text(task, encoding="utf-8")
            files["task.xml"] = digest(folder / "task.xml")
        legacy_tasks = self.tasks.legacy(self.legacy_source) if self.legacy_source else {}
        legacy_names = {}
        for index, (name, value) in enumerate(legacy_tasks.items()):
            filename = f"legacy-task-{index}.xml"
            (folder / filename).write_text(value, encoding="utf-8")
            files[filename] = digest(folder / filename)
            legacy_names[name] = filename
        record = {
            "owner": "orquestrador-app-v1",
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "files": files,
            "had_task": bool(task),
            "legacy_tasks": legacy_names,
        }
        atomic_json(folder / "manifest.json", record)
        self.verify_snapshot(folder)
        return record

    @staticmethod
    def verify_snapshot(folder: Path) -> None:
        record = read_json(folder / "manifest.json")
        if record.get("owner") != "orquestrador-app-v1":
            raise ValueError("Backup do aplicativo não reconhecido.")
        for name, expected in record["files"].items():
            path = folder / name
            if not path.resolve().is_relative_to(folder.resolve()) or digest(path) != expected:
                raise ValueError("Backup do aplicativo falhou na verificação de integridade.")

    def _restore(self, folder: Path) -> None:
        self.verify_snapshot(folder)
        record = read_json(folder / "manifest.json")
        for name in ("config.json", "installation.json", "instalacao-teste.json"):
            target = self.paths.root / name
            if (folder / name).is_file():
                value = read_json(folder / name)
                atomic_json(target, value)
            else:
                target.unlink(missing_ok=True)
        database = folder / "history.sqlite3"
        if database.is_file():
            for suffix in ("-wal", "-shm"):
                Path(str(self.paths.database) + suffix).unlink(missing_ok=True)
            shutil.copy2(database, self.paths.database)
        elif self.paths.database.exists():
            self.paths.database.unlink()
        extras = self.paths.root / "extras"
        if (folder / "extras").exists():
            if extras.exists():
                shutil.rmtree(extras)
            shutil.copytree(folder / "extras", extras)
        if record["had_task"]:
            self.tasks.register_xml((folder / "task.xml").read_text(encoding="utf-8"))
        else:
            self.tasks.remove()
        for name, filename in record.get("legacy_tasks", {}).items():
            self.tasks.register_xml((folder / filename).read_text(encoding="utf-8"), name=name)
        previous = read_json(self.pointer) if self.pointer.is_file() else None
        binary = folder / "application/Orquestrador.exe"
        if previous and binary.is_file():
            previous_binary = Path(previous["executable"])
            if not previous_binary.is_file() or digest(previous_binary) != digest(binary):
                previous_binary.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(binary, previous_binary)
        self.shortcut(Path(previous["executable"]) if previous else None)

    def recover(self) -> str:
        if not self.journal.is_file():
            return ""
        state = read_json(self.journal)
        if state["status"] in {"committed", "rolled_back"}:
            return ""
        with Lock(self.paths.lock), Lock(self.paths.maintenance_lock):
            try:
                self._restore(Path(state["backup"]))
                state["status"] = "rolled_back"
                atomic_json(self.journal, state)
                return "Instalação interrompida: versão, configuração, estado e tarefa anteriores restaurados."
            except Exception as exc:
                state["status"] = "rollback_failed"
                state["error"] = str(exc)
                atomic_json(self.journal, state)
                raise RuntimeError(
                    "Recuperação automática incompleta; consulte o backup e o diagnóstico local."
                ) from exc

    def install(
        self,
        executable: Path,
        config: Config,
        progress: Callable[[str], None] = lambda _: None,
        fault: str = "",
    ) -> Path:
        validate(config)
        if config.test_mode:
            from .sandbox import check_location, mark, validate_isolation

            validate_isolation(self.paths, config)
            check_location(self.paths.root)
            self.paths.root.mkdir(parents=True, exist_ok=True)
            mark(self.paths)
        self.paths.ensure()
        root = Path(config.install_root)
        if not root.is_absolute():
            raise ValueError("Escolha uma pasta absoluta de instalação.")
        check_directory(root, min_free=max(executable.stat().st_size * 3, 300_000_000), create=True)
        identifier = str(uuid.uuid4())
        self.legacy_source = "" if config.test_mode else str(config.legacy.get("config_source", ""))
        backup = self.paths.root / "backups/app" / identifier
        backup.parent.mkdir(parents=True, exist_ok=True)
        stage = root / "versions" / f"{VERSION}-{identifier}"
        stage.mkdir(parents=True, exist_ok=False)
        target = stage / "Orquestrador.exe"
        with Lock(self.paths.lock), Lock(self.paths.maintenance_lock):
            progress("Criando e verificando backup do aplicativo, configuração, estado e tarefa")
            self.snapshot(backup)
            journal: dict[str, Any] = {
                "id": identifier,
                "backup": str(backup),
                "status": "preparing",
                "new": str(target),
            }
            atomic_json(self.journal, journal)
            try:
                progress("Preparando nova versão em diretório separado")
                shutil.copy2(executable, target)
                if digest(target) != digest(executable):
                    raise ValueError("Hash do executável copiado divergiu.")
                if fault == "copy":
                    raise RuntimeError("Falha induzida após cópia.")
                progress("Validando runtime privado e smoke test sem rede nem extrações")
                self.health(target)
                if fault == "health":
                    raise RuntimeError("Falha induzida no health check.")
                # External/custom scripts are preserved as data; they are never silently downloaded/executed.
                for job in config.routines:
                    if job.script.startswith("bundle:"):
                        continue
                    source = script_path(job.script)
                    if not source.is_file():
                        if job.enabled:
                            raise ValueError(f"Script habilitado indisponível: {job.label}")
                        continue
                    destination = self.paths.root / "extras" / source.name
                    if source.resolve() != destination.resolve():
                        shutil.copy2(source, destination)
                        job.script = str(destination)
                progress("Aplicando configuração e migrações de estado")
                save(self.paths, config)
                state_path = None if config.test_mode else config.legacy.get("state_path")
                if state_path:
                    Store(self.paths.database).migrate_state(
                        Path(state_path), dt.datetime.now().astimezone().tzinfo or dt.timezone.utc
                    )
                if fault == "migration":
                    raise RuntimeError("Falha induzida durante migração.")
                progress("Registrando componentes próprios da instalação de teste")
                user = (
                    os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser()
                    if os.name == "nt"
                    else getpass.getuser()
                )
                if config.install_schedules:
                    self.tasks.install(target, user)
                elif self.tasks.export():
                    self.tasks.remove()
                snapshot = read_json(backup / "manifest.json")
                for name, filename in snapshot.get("legacy_tasks", {}).items():
                    self.tasks.disable_legacy(name, (backup / filename).read_text(encoding="utf-8"))
                if self.legacy_source:
                    config.legacy["tasks_migrated"] = True
                    save(self.paths, config)
                self.shortcut(target)
                journal["status"] = "activating"
                atomic_json(self.journal, journal)
                atomic_json(
                    self.pointer,
                    {
                        "owner": "orquestrador-app-v1",
                        "version": VERSION,
                        "executable": str(target),
                        "sha256": digest(target),
                        "backup": str(backup),
                    },
                )
                if fault == "activation":
                    raise RuntimeError("Falha induzida após ativação.")
                progress("Verificando configuração, integridade e tarefa após ativação")
                load(self.paths)
                self.health(target)
                if config.install_schedules and not self.tasks.export():
                    raise RuntimeError("Tarefa própria não foi encontrada após a instalação.")
                if fault == "post":
                    raise RuntimeError("Falha induzida na verificação final.")
                versioning.record(self.paths, target, backup)
                journal["status"] = "committed"
                atomic_json(self.journal, journal)
                progress("Instalação concluída; backups e versão anterior preservados")
                return target
            except Exception as exc:
                progress("Falha: restaurando automaticamente versão, configuração, estado e tarefa")
                try:
                    self._restore(backup)
                    journal["status"] = "rolled_back"
                    journal["error"] = str(exc)
                    atomic_json(self.journal, journal)
                except Exception as rollback_exc:
                    journal["status"] = "rollback_failed"
                    journal["error"] = str(exc)
                    journal["rollback_error"] = str(rollback_exc)
                    atomic_json(self.journal, journal)
                    raise RuntimeError(
                        "Falha de atualização e de reversão automática; backup preservado."
                    ) from rollback_exc
                raise

    def rollback(self, folder: Path) -> None:
        allowed = (self.paths.root / "backups/app").resolve()
        if not folder.resolve().is_relative_to(allowed):
            raise ValueError("Backup fora do diretório gerenciado.")
        with Lock(self.paths.lock), Lock(self.paths.maintenance_lock):
            checkpoint = allowed / ("before-rollback-" + str(uuid.uuid4()))
            self.snapshot(checkpoint)
            try:
                self._restore(folder)
            except Exception:
                self._restore(checkpoint)
                raise

    def uninstall(self) -> None:
        with Lock(self.paths.lock), Lock(self.paths.maintenance_lock):
            if not self.pointer.is_file():
                return
            current = read_json(self.pointer)
            if current.get("owner") != "orquestrador-app-v1":
                raise ValueError("Instalação não reconhecida.")
            self.tasks.remove()
            self.shortcut(None)
            executable = Path(current["executable"])
            # Windows cannot delete its running executable. Mark its owned version for next maintenance.
            atomic_json(
                executable.parent / "pending-removal.json", {"owner": "orquestrador-app-v1"}
            )
            self.pointer.unlink()
