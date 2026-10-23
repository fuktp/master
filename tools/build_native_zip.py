"""Assemble an offline Windows script distribution from verified private runtime inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.file_digest(path.open("rb"), "sha256").hexdigest()


def prune_runtime(runtime: Path) -> None:
    packages = runtime / "Lib/site-packages"
    import pefile

    qt = packages / "PySide6"
    keep = {"QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd"}
    available = {p.name.casefold(): p for p in qt.glob("*.dll")}
    pending = [qt / name for name in keep]
    for name in ("platforms", "imageformats", "styles"):
        pending += list((qt / "plugins" / name).glob("*.dll"))
    while pending:
        path = pending.pop()
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(directories=[1, 13])
        for group in (
            getattr(pe, "DIRECTORY_ENTRY_IMPORT", []),
            getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []),
        ):
            for dependency in group:
                candidate = available.get(dependency.dll.decode().casefold())
                if candidate and candidate.name not in keep:
                    keep.add(candidate.name)
                    pending.append(candidate)
        pe.close()
    for path in sorted(packages.rglob("*"), reverse=True):
        if not path.is_file():
            continue
        relative = path.relative_to(packages)
        remove = any(
            part in {"__pycache__", "tests", "test", ".pytest_cache"} for part in relative.parts
        )
        if relative.parts[0] == "selenium" and any(
            part in {"linux", "macos"} for part in relative.parts
        ):
            remove = True
        if relative.parts[0] == "PySide6":
            parts = relative.parts[1:]
            if len(parts) == 1:
                if path.suffix in {".dll", ".pyd"} and path.name not in keep:
                    remove = True
                if path.suffix not in {".py", ".dll", ".pyd", ".pem", ".txt", ".json"}:
                    remove = True
            elif parts[0] not in {"support", "translations", "plugins"}:
                remove = True
            elif parts[0] == "plugins" and parts[1] not in {"platforms", "imageformats", "styles"}:
                remove = True
        if path.suffix.casefold() in {".chm", ".h", ".lib", ".pdb", ".pyi"}:
            remove = True
        if any(part.casefold() in {"demos", "demo", "examples"} for part in relative.parts):
            remove = True
        if remove:
            path.unlink()
    for path in sorted(packages.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    namespace: dict[str, object] = {}
    exec((source / "orquestrador_app/__init__.py").read_text(), namespace)
    version = str(namespace["VERSION"])
    root = args.output / f"CAIO_{version}"
    if root.exists():
        raise ValueError("Escolha uma área de build nova; resultados anteriores são preservados.")
    payload = root / "payload"
    payload.mkdir(parents=True)
    runtime = payload / "runtime"
    shutil.copytree(args.runtime, runtime)
    prune_runtime(runtime)
    packages = runtime / "Lib/site-packages"
    for pattern in (
        "PyInstaller",
        "_pyinstaller_hooks_contrib",
        "altgraph",
        "altgraph-*.dist-info",
        "pefile.py",
        "pefile-*.dist-info",
        "pyinstaller*.dist-info",
        "pyinstaller_hooks_contrib*.dist-info",
    ):
        for path in packages.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    for cache in runtime.rglob("__pycache__"):
        shutil.rmtree(cache)
    (runtime / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\nLib/site-packages/win32\nLib/site-packages/win32/lib\nLib/site-packages/Pythonwin\n../src\nimport site\n",
        encoding="utf-8",
    )
    application = payload / "src"
    application.mkdir()
    for path in source.glob("*.py"):
        if path.name != "conftest.py":
            shutil.copy2(path, application / path.name)
    for name in ("orquestrador_app", "scripts"):
        shutil.copytree(
            source / name, application / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
    release_tools = application / "release_tools"
    release_tools.mkdir()
    for name in ("validate_windows_release.py", "benchmark_gui.py"):
        shutil.copy2(source / "tools" / name, release_tools / name)
    diagnostics = root / "diagnostics"
    diagnostics.mkdir()
    shutil.copy2(
        source / "tools/validate_windows_release.ps1", diagnostics / "validate_windows_release.ps1"
    )
    native = payload / "native"
    native.mkdir()
    for path in (source / "native").iterdir():
        if path.suffix.lower() in {".ps1", ".vbs", ".bat"}:
            encoding = "utf-8-sig" if path.suffix == ".ps1" else "ascii"
            text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
            data = text.replace("\n", "\r\n").encode(encoding)
            (native / path.name).write_bytes(data)
            if path.name in {"Instalar.vbs", "Instalar.bat"}:
                entry = "01 - Instalar.vbs" if path.suffix == ".vbs" else "01 - Instalar(alt).bat"
                wrapper = text.replace("\\wizard.ps1", "\\payload\\native\\wizard.ps1").replace(
                    "%~dp0wizard.ps1", "%~dp0payload\\native\\wizard.ps1"
                )
                (root / entry).write_bytes(wrapper.replace("\n", "\r\n").encode(encoding))
    shutil.copytree(source / "assets", payload / "assets")
    shutil.copy2(source / "assets/caio.ico", payload / "assets/orquestrador.ico")
    # Top-level scripts are the entry point; the installed launchers are in the manifested payload.
    files = {
        p.relative_to(payload).as_posix(): sha256(p)
        for p in sorted(payload.rglob("*"))
        if p.is_file()
    }
    record = {
        "owner": "orquestrador-native-package-v1",
        "distribution": "native-scripts",
        "version": version,
        "python": "3.13.16",
        "files": files,
        "signature": "unsigned scripts; SHA-256 verifies integrity, not publisher identity",
    }
    (payload / "release.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copy2(source / "README.md", root / "00 - Read Me.md")
    archive = args.output / f"CAIO_{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                z.write(path, root.name + "/" + path.relative_to(root).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise ValueError("O ZIP não passou na verificação CRC.")
        if any(Path(name).name.casefold() == "orquestrador.exe" for name in z.namelist()):
            raise ValueError("A distribuição de scripts não deve conter Orquestrador.exe.")
    print(
        json.dumps(
            {
                "archive": str(archive.resolve()),
                "size": archive.stat().st_size,
                "sha256": sha256(archive),
                "payload_files": len(files),
                "payload_bytes": sum((payload / name).stat().st_size for name in files),
                "runtime": "official Windows CPython with private pinned dependencies",
                "windows_execution": "not executed on this Linux host",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
