"""Opt-in real Windows checks using the package's private runtime and disposable data."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise RuntimeError("This check requires real Windows; mocks are not accepted.")
    from orquestrador_app import VERSION
    from orquestrador_app.config import load
    from orquestrador_app.io import digest, read_json
    from orquestrador_app.native_install import NativeInstaller, WindowsLinks, verify_release
    from orquestrador_app.paths import Paths
    from orquestrador_app.sandbox import prepare_config
    from orquestrador_app.tasks import WindowsTasks, current_user
    from orquestrador_app.windows_identity import app_id, launch_icon

    payload = args.payload.resolve()
    if not Path(sys.executable).resolve().is_relative_to(payload / "runtime"):
        raise RuntimeError("Run this tool using the supplied private runtime.")
    result: dict[str, Any] = {
        "version": VERSION,
        "platform": platform.platform(),
        "runtime": sys.executable,
        "at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scenarios": [],
        "manual_pending": [
            "WinForms wizard navigation",
            "desktop/taskbar pinned icon and notifications",
            "Narrator, high contrast and DPI 100/125/150/200%",
            "corporate Edge/SSO/VPN",
        ],
        "host_without_global_python": "NOT_PROVEN: run on a clean VM and record its image; this tool never invokes global Python",
    }

    def check(name: str, callback: Any) -> None:
        started = time.perf_counter()
        try:
            callback()
        except Exception as exc:
            result["scenarios"].append(
                {
                    "name": name,
                    "passed": False,
                    "error": str(exc),
                    "seconds": time.perf_counter() - started,
                }
            )
            raise
        result["scenarios"].append(
            {"name": name, "passed": True, "seconds": time.perf_counter() - started}
        )

    try:
        verify_release(payload)
        # Only this tool's freshly created directory, shortcuts and UUID-derived task are touched.
        with tempfile.TemporaryDirectory(prefix="CAIO-homologacao-") as temporary:
            paths = Paths.user(Path(temporary) / "instalacao com acentos ç")

            class IsolatedLinks(WindowsLinks):
                def locations(self) -> list[Path]:
                    folder = paths.root / "validation-shortcuts"
                    folder.mkdir(parents=True, exist_ok=True)
                    return [folder / "Desktop.lnk", folder / "Programs.lnk"]

            tasks = WindowsTasks(paths)
            installer = NativeInstaller(paths, links=IsolatedLinks(paths))
            config = prepare_config(paths)
            config.install_schedules = False
            for job in config.routines:
                job.enabled = False
            try:
                check(
                    "scheduler create/query/delete disabled probe",
                    lambda: tasks.preflight(current_user()),
                )
                check(
                    "install private runtime and offline health",
                    lambda: installer.install(payload, config),
                )
                previous = read_json(installer.pointer)
                check(
                    "update preserving configuration",
                    lambda: installer.install(payload, load(paths)),
                )
                check(
                    "repair by reinstalling verified components",
                    lambda: installer.install(payload, load(paths)),
                )
                before = digest(paths.config), read_json(installer.pointer)
                cancelled = False

                def progress(message: str) -> None:
                    nonlocal cancelled
                    if message.startswith("Arquivos copiados:"):
                        cancelled = True

                def cancellation() -> None:
                    try:
                        installer.install(
                            payload, load(paths), progress=progress, cancelled=lambda: cancelled
                        )
                    except RuntimeError:
                        if not cancelled:
                            raise
                    else:
                        raise AssertionError("Cancellation was not exercised")
                    assert (digest(paths.config), read_json(installer.pointer)) == before
                    assert read_json(paths.root / "state/recovery-report.json")["complete"]

                check("cancel during copy and verify rollback", cancellation)

                def rollback() -> None:
                    try:
                        installer.install(payload, load(paths), fault="health")
                    except RuntimeError as exc:
                        if "induzida" not in str(exc):
                            raise
                    else:
                        raise AssertionError("Failure injection did not run")
                    assert (digest(paths.config), read_json(installer.pointer)) == before
                    assert read_json(paths.root / "state/recovery-report.json")["complete"]

                check("rollback after health failure", rollback)

                def shortcut() -> None:
                    import pythoncom
                    import win32com.client
                    from win32com.propsys import propsys, pscon
                    from win32com.shell import shellcon

                    pythoncom.CoInitialize()
                    try:
                        for file in installer.links.locations():
                            link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(
                                str(file)
                            )
                            assert Path(link.TargetPath).resolve().is_relative_to(paths.root)
                            assert str(launch_icon(paths)) in link.IconLocation
                            properties = propsys.SHGetPropertyStoreFromParsingName(
                                str(file), None, shellcon.GPS_DEFAULT
                            )
                            assert properties.GetValue(
                                pscon.PKEY_AppUserModel_ID
                            ).GetValue() == app_id(paths)
                    finally:
                        pythoncom.CoUninitialize()

                check("shortcut icon and common AppUserModelID metadata", shortcut)

                def scheduled() -> None:
                    marker = paths.root / "scheduled.txt"
                    launcher = paths.root / "validation-task.vbs"
                    launcher.write_text(
                        'Set fs = CreateObject("Scripting.FileSystemObject")\nSet output = fs.CreateTextFile("'
                        + str(marker)
                        + '", True, True)\noutput.WriteLine "OK"\noutput.Close\n',
                        encoding="utf-16",
                    )
                    assert tasks.export() is None
                    tasks.install(launcher, current_user())
                    tasks.start()
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        if marker.is_file() and marker.read_text(encoding="utf-16").strip() == "OK":
                            return
                        time.sleep(0.1)
                    raise AssertionError("Scheduled marker did not execute")

                check("real scheduled execution in user session", scheduled)
                result["private_installation_executable"] = previous["executable"]
                result["recovery"] = read_json(paths.root / "state/recovery-report.json")
            finally:
                tasks.remove()
    except Exception as exc:
        result["error"] = str(exc)
    result["passed"] = (
        bool(result["scenarios"])
        and not result.get("error")
        and all(row["passed"] for row in result["scenarios"])
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
