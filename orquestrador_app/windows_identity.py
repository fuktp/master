"""One Windows identity and icon for shortcuts, windows and taskbar relaunch."""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .io import digest
from .paths import Paths
from .resources import asset_path


def app_id(paths: Paths) -> str:
    key = hashlib.sha256(str(paths.root.resolve()).casefold().encode()).hexdigest()[:12]
    return "CAIO.Orquestrador." + key


def launch_icon(paths: Paths) -> Path:
    return paths.root / "launch" / ("caio-" + digest(asset_path("caio.ico"))[:12] + ".ico")


def set_process_identity(paths: Paths) -> None:
    if sys.platform != "win32":
        return
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    setter = shell.SetCurrentProcessExplicitAppUserModelID
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_long
    if setter(app_id(paths)) != 0:
        raise RuntimeError("O Windows não aceitou a identificação do aplicativo CAIO.")


def set_shortcut_identity(shortcut: Path, paths: Paths) -> None:
    from win32com.propsys import propsys, pscon
    from win32com.shell import shellcon

    store = propsys.SHGetPropertyStoreFromParsingName(str(shortcut), None, shellcon.GPS_READWRITE)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(app_id(paths)))
    store.Commit()


def set_window_identity(window: Any, paths: Paths) -> None:
    if sys.platform != "win32":
        return
    from win32com.propsys import propsys, pscon

    store = propsys.SHGetPropertyStoreForWindow(int(window.winId()))
    launcher = paths.root / "launch/Iniciar.vbs"
    if launcher.is_file():
        command = subprocess.list2cmdline(
            [str(Path(os.environ["WINDIR"]) / "System32/wscript.exe"), "//Nologo", str(launcher)]
        )
        for key, value in (
            (pscon.PKEY_AppUserModel_RelaunchCommand, command),
            (pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, "CAIO"),
            (pscon.PKEY_AppUserModel_RelaunchIconResource, str(launch_icon(paths)) + ",0"),
        ):
            store.SetValue(key, propsys.PROPVARIANTType(value))
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(app_id(paths)))
