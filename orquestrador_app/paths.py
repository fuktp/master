from __future__ import annotations

import getpass
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def user(cls, override: str | Path | None = None) -> Paths:
        if override:
            return cls(Path(override).expanduser().resolve())
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share")))
        return cls(base / "Orquestrador")

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def database(self) -> Path:
        return self.root / "state" / "history.sqlite3"

    @property
    def lock(self) -> Path:
        return self.root / "state" / "execution.lock"

    @property
    def maintenance_lock(self) -> Path:
        return self.root / "state" / "maintenance.lock"

    def ensure(self) -> None:
        for name in ("state", "logs", "cache", "downloads", "profiles", "backups", "extras"):
            (self.root / name).mkdir(parents=True, exist_ok=True)


def identity() -> dict[str, str]:
    return {"user": getpass.getuser(), "computer": platform.node(), "home": str(Path.home())}


def onedrives(environ: dict[str, str] | None = None) -> list[dict[str, str]]:
    env = os.environ if environ is None else environ
    accounts: list[dict[str, str]] = []
    for key, kind in (
        ("OneDriveCommercial", "corporativa"),
        ("OneDriveConsumer", "pessoal"),
        ("OneDrive", "tipo não confirmado"),
    ):
        if env.get(key):
            accounts.append({"path": env[key], "kind": kind, "account": key})
    if os.name == "nt" and environ is None:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\OneDrive\Accounts"
            ) as root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    name = winreg.EnumKey(root, index)
                    with winreg.OpenKey(root, name) as registry_key:
                        try:
                            folder = str(winreg.QueryValueEx(registry_key, "UserFolder")[0])
                            accounts.append(
                                {
                                    "path": folder,
                                    "account": name,
                                    "kind": "pessoal" if name == "Personal" else "corporativa",
                                }
                            )
                        except OSError:
                            continue
        except OSError:
            pass
    unique: dict[str, dict[str, str]] = {}
    for account in accounts:
        unique.setdefault(os.path.normcase(os.path.normpath(account["path"])), account)
    return list(unique.values())


def check_directory(
    path: Path, min_free: int = 100 * 1024 * 1024, create: bool = False
) -> dict[str, Any]:
    if not path.is_absolute():
        raise ValueError("Selecione um caminho absoluto.")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError(f"Pasta indisponível: {path}")
    usage = shutil.disk_usage(path)
    if usage.free < min_free:
        raise ValueError(f"Espaço insuficiente em {path}.")
    fd, name = tempfile.mkstemp(prefix=".orquestrador-probe-", dir=path)
    os.close(fd)
    Path(name).unlink()
    return {
        "path": str(path),
        "writable": True,
        "free_bytes": usage.free,
        "publication": "local; sincronização externa não verificada",
    }
