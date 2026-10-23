"""Owned entry points, Windows registration and safe teardown of one installation."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
from pathlib import Path
from typing import Any

import psutil

from .io import atomic_json, digest, read_json
from .paths import Paths
from .windows_identity import app_id, launch_icon

ENTRY_MARKER = "CAIO managed entry v1"
PUBLIC_ENTRIES = {
    "02 - Abrir CAIO.vbs": "open",
    "02 - Abrir CAIO(alt).bat": "open",
    "03 - Desinstalar CAIO.vbs": "uninstall",
    "03 - Desinstalar CAIO(alt).bat": "uninstall",
}


def render_entries(native: Path) -> dict[str, bytes]:
    return {
        name: (native / ("Entrada" + Path(name).suffix))
        .read_text(encoding="utf-8-sig")
        .replace("__ACTION__", action)
        .replace("\r\n", "\n")
        .replace("\n", "\r\n")
        .encode("ascii")
        for name, action in PUBLIC_ENTRIES.items()
    }


def check_entry(file: Path) -> None:
    if file.exists() and (
        file.is_symlink()
        or ENTRY_MARKER not in file.read_text(encoding="ascii", errors="replace").partition("\n")[0]
    ):
        raise ValueError(
            "Há um arquivo externo com o nome do iniciador; ele foi preservado: " + file.name
        )


def install_entries(paths: Paths, native: Path) -> None:
    values = render_entries(native)
    for name in values:
        check_entry(paths.root / name)
    for name, content in values.items():
        temporary = paths.root / (name + ".new")
        temporary.write_bytes(content)
        temporary.replace(paths.root / name)


def restore_entries(paths: Paths, snapshot: Path) -> None:
    import shutil

    for name in PUBLIC_ENTRIES:
        target = paths.root / name
        saved = snapshot / "root-entries" / name
        if saved.is_file():
            check_entry(target)
            shutil.copy2(saved, target)
        elif target.exists():
            check_entry(target)
            target.unlink()


class WindowsRegistration:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + app_id(paths)

    def snapshot(self) -> dict[str, Any] | None:
        if os.name != "nt":
            return None
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as key:
                values = {
                    winreg.EnumValue(key, index)[0]: winreg.EnumValue(key, index)[1]
                    for index in range(winreg.QueryInfoKey(key)[1])
                }
        except FileNotFoundError:
            return None
        if (
            values.get("CAIOOwner") != "caio-uninstall-v1"
            or Path(values.get("InstallLocation", "")).resolve() != self.paths.root.resolve()
        ):
            raise ValueError(
                "Registro de desinstalação pertence a outra instalação; foi preservado."
            )
        return values

    def write(self, values: dict[str, Any]) -> None:
        if os.name != "nt":
            return
        import winreg

        self.snapshot()  # Refuse to replace an external entry.
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_WRITE) as key:
            for name, value in values.items():
                winreg.SetValueEx(
                    key,
                    name,
                    0,
                    winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ,
                    value,
                )

    def install(self, version: str) -> None:
        self.write(
            {
                "CAIOOwner": "caio-uninstall-v1",
                "DisplayName": "CAIO - Orquestrador (Teste)",
                "DisplayVersion": version,
                "Publisher": "CAIO",
                "InstallLocation": str(self.paths.root),
                "DisplayIcon": str(launch_icon(self.paths)),
                "NoModify": 1,
                "NoRepair": 1,
                "UninstallString": subprocess.list2cmdline(
                    [
                        str(Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32/wscript.exe"),
                        "//Nologo",
                        str(self.paths.root / "03 - Desinstalar CAIO.vbs"),
                    ]
                ),
            }
        )

    def remove(self) -> None:
        if self.snapshot() is not None:
            import winreg

            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key)

    def restore(self, value: dict[str, Any] | None) -> None:
        if value is None:
            self.remove()
        else:
            if (
                value.get("CAIOOwner") != "caio-uninstall-v1"
                or Path(value.get("InstallLocation", "")).resolve() != self.paths.root.resolve()
            ):
                raise ValueError("Registro do backup não pertence a esta instalação.")
            self.write(value)


def stop_monitor(paths: Paths) -> None:
    """Never stop a global Python/browser process: require PID birth, command and managed executable."""
    file = paths.root / "state/monitor-heartbeat.json"
    if not file.is_file():
        return
    value = read_json(file)
    try:
        process = psutil.Process(int(value["pid"]))
        if abs(process.create_time() - float(value["created"])) > 0.01:
            return  # PID was reused.
        arguments = process.cmdline()
        executable = Path(process.exe()).resolve()
        if (
            "--agent" not in arguments
            or "--data-root" not in arguments
            or Path(arguments[arguments.index("--data-root") + 1]).resolve() != paths.root.resolve()
            or not executable.is_relative_to((paths.root / "app/versions").resolve())
        ):
            raise ValueError(
                "O processo observado não é um monitor próprio; encerramento recusado."
            )
        atomic_json(
            paths.root / "state/monitor-stop.json",
            {"pid": process.pid, "created": process.create_time(), "owner": "caio-monitor-stop-v1"},
        )
        try:
            process.wait(timeout=3)
        except psutil.TimeoutExpired:
            # Caller owns execution + maintenance locks: this idle monitor cannot start a new run.
            if abs(process.create_time() - float(value["created"])) < 0.01:
                process.terminate()
                process.wait(timeout=10)
    except psutil.NoSuchProcess:
        pass
    except (KeyError, ValueError, IndexError) as exc:
        raise ValueError(
            "Não foi possível confirmar a identidade do monitor; feche-o antes de desinstalar."
        ) from exc
    value.update(state="stopped", at=dt.datetime.now(dt.timezone.utc).isoformat())
    atomic_json(file, value)


def cleanup_plan(paths: Paths) -> dict[str, Any]:
    from .native_install import verify_release

    releases, preserved = [], []
    folder = paths.root / "app/versions"
    if folder.is_symlink():
        raise ValueError("Link inesperado na pasta de versões; remoção recusada.")
    for release in sorted(folder.iterdir()) if folder.is_dir() else []:
        try:
            if release.is_symlink() or not release.is_dir():
                raise ValueError("Item não gerenciado")
            record = verify_release(release)
            releases.append(
                {
                    "path": str(release),
                    "manifest_sha256": digest(release / "release.json"),
                    "files": record["files"],
                }
            )
        except (ValueError, OSError):
            preserved.append(str(release))
    return {
        "owner": "caio-uninstall-cleanup-v1",
        "root": str(paths.root),
        "releases": releases,
        "preserved_unverified": preserved,
        "created": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
