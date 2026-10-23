"""Assemble the official Windows bootloader with an explicit Windows-only runtime.

This fallback does not perform PyInstaller's platform-dependent Analysis. It includes
the private standard library and complete runtime packages, with a checked Qt DLL
closure. The produced PE must still pass execution checks on Windows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.archive.writers import CArchiveWriter, ZlibArchiveWriter

BOOTSTRAP = """import sys, os
root = sys._MEIPASS
sys.frozen = True
sys.prefix = sys.exec_prefix = sys.base_prefix = sys.base_exec_prefix = root
packages = os.path.join(root, "Lib", "site-packages")
sys.path[:] = [root, os.path.join(root, "base_library.zip"), packages]
os.environ.pop("PYTHONHOME", None)
os.environ.pop("PYTHONPATH", None)
os.environ.pop("VIRTUAL_ENV", None)
os.environ["QT_PLUGIN_PATH"] = os.path.join(packages, "PySide6", "plugins")
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(packages, "PySide6", "plugins", "platforms")
import site
site.addsitedir(packages)
if sys.platform == "win32":
    _dll_directories = [os.add_dll_directory(folder) for folder in
        [root, os.path.join(packages,"PySide6"), os.path.join(packages,"shiboken6"), os.path.join(packages,"pywin32_system32")]
        if os.path.isdir(folder)]
from orquestrador_app.__main__ import entry
raise SystemExit(entry())
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pe_gui(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    offset = int.from_bytes(data[0x3C:0x40], "little")
    if data[:2] != b"MZ" or data[offset : offset + 4] != b"PE\0\0":
        raise ValueError("Bootloader não é um PE Windows.")
    machine = int.from_bytes(data[offset + 4 : offset + 6], "little")
    subsystem = int.from_bytes(data[offset + 92 : offset + 94], "little")
    if machine != 0x8664 or subsystem != 2:
        raise ValueError("É necessário um bootloader Windows x64 gráfico.")
    return {"machine": machine, "subsystem": subsystem}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--wheels", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    root = Path(__file__).resolve().parents[1]
    packages = runtime / "Lib/site-packages"
    # A Windows Python DLL plus exact bytecode compiler version are mandatory.
    major, minor = sys.version_info[:2]
    dll_name = f"python{major}{minor}.dll"
    if not (runtime / dll_name).is_file():
        raise ValueError("A versão do compilador não corresponde ao runtime Windows.")
    inputs = json.loads(args.input_manifest.read_text())
    for name, expected in inputs.items():
        if sha(args.wheels / name) != expected:
            raise ValueError(f"Wheel divergiu do manifesto: {name}")
        if "manylinux" in name or "macosx" in name or "win32." in name:
            raise ValueError("Dependência incompatível com Windows x64.")
    bootloader = packages / "PyInstaller/bootloader/Windows-64bit-intel/runw.exe"
    header = pe_gui(bootloader)
    work = root / "build/windows-payload"
    work.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, Path] = {}
    names: set[str] = set()

    def add(name: str, source: Path) -> None:
        key = name.replace("\\", "/")
        if key.casefold() in names:
            raise ValueError(f"Nome duplicado: {key}")
        names.add(key.casefold())
        mapping[key] = source

    for path in sorted(runtime.iterdir()):
        if path.is_file() and path.suffix.lower() in {".dll", ".pyd", ".txt"}:
            add(path.name, path)
    library = runtime / f"python{major}{minor}.zip"
    add("base_library.zip", library)
    qt_modules = {"QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtTest.pyd"}
    qt_binaries: set[str] = set(qt_modules)
    qt = packages / "PySide6"
    # Read PE imports without loading foreign code. Include dependent Qt/MSVC DLLs.
    sys.path.insert(0, str(packages))
    import pefile

    available = {p.name.casefold(): p for p in qt.glob("*.dll")}
    pending = [qt / name for name in qt_modules]
    pending += list((qt / "plugins/platforms").glob("*.dll"))
    pending += list((qt / "plugins/imageformats").glob("*.dll"))
    pending += list((qt / "plugins/styles").glob("*.dll"))
    while pending:
        file = pending.pop()
        pe = pefile.PE(str(file), fast_load=True)
        pe.parse_data_directories(directories=[1, 13])
        for group in (
            getattr(pe, "DIRECTORY_ENTRY_IMPORT", []),
            getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []),
        ):
            for dependency in group:
                candidate = available.get(dependency.dll.decode().casefold())
                if candidate and candidate.name not in qt_binaries:
                    qt_binaries.add(candidate.name)
                    pending.append(candidate)
        pe.close()
    for path in sorted(packages.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(packages)
        if any(
            part in {"__pycache__", "tests", "test", ".pytest_cache"} for part in relative.parts
        ):
            continue
        if relative.parts[0] in {"PyInstaller", "_pyinstaller_hooks_contrib"}:
            continue
        if relative.parts[:2] in {("selenium", "webdriver")} and any(
            part in {"linux", "macos"} for part in relative.parts
        ):
            continue
        if relative.parts[0] == "PySide6":
            parts = relative.parts[1:]
            if len(parts) == 1:
                if path.suffix in {".dll", ".pyd"} and path.name not in qt_binaries:
                    continue
                if path.suffix not in {".py", ".dll", ".pyd", ".pem", ".txt", ".json"}:
                    continue
            elif parts[0] not in {"support", "translations", "plugins"}:
                continue
            elif parts[0] == "plugins" and parts[1] not in {"platforms", "imageformats", "styles"}:
                continue
        add("Lib/site-packages/" + relative.as_posix(), path)
    for directory in ("orquestrador_app", "scripts"):
        for path in sorted((root / directory).rglob("*.py")):
            if "__pycache__" not in path.parts:
                add(path.relative_to(root).as_posix(), path)
    for name in ("pipefy_orchestrator.py", "automation_schedule.py"):
        add(name, root / name)
    manifest = {name: sha(path) for name, path in mapping.items()}
    manifest_path = work / "payload-manifest.json"
    manifest_path.write_text(json.dumps({"files": manifest}, indent=2), encoding="utf-8")
    add("payload-manifest.json", manifest_path)
    startup = work / "orquestrador_bootstrap.py"
    startup.write_text(BOOTSTRAP, encoding="utf-8")
    empty_pyz = work / "PYZ.pyz"
    ZlibArchiveWriter(str(empty_pyz), [])
    entries = [
        (name.replace("/", "\\"), str(path), True, "b" if path.suffix in {".dll", ".pyd"} else "x")
        for name, path in mapping.items()
    ]
    entries += [
        ("PYZ.pyz", str(empty_pyz), False, "z"),
        ("orquestrador_bootstrap", str(startup), True, "s"),
    ]
    archive = work / "payload.pkg"
    CArchiveWriter._COMPRESSION_LEVEL = 3
    CArchiveWriter(str(archive), entries, dll_name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as target:
        target.write(bootloader.read_bytes())
        with archive.open("rb") as source:
            shutil.copyfileobj(source, target)
    # Validate every archived byte against its source, independently of extraction.
    reader = CArchiveReader(str(args.output))
    for name, path in mapping.items():
        if hashlib.sha256(reader.extract(name.replace("/", "\\"))).hexdigest() != sha(path):
            raise ValueError(f"Integridade do arquivo empacotado divergiu: {name}")
    result = {
        "file": args.output.name,
        "version": "2.0.0.dev2",
        "bytes": args.output.stat().st_size,
        "sha256": sha(args.output),
        "pe": header,
        "method": "official Windows PyInstaller bootloader + explicit Windows embedded runtime and wheels; CArchive assembly",
        "compiler_python": sys.version,
        "packaged_files": len(mapping),
        "uncompressed_bytes": sum(p.stat().st_size for p in mapping.values()),
        "archive_integrity": "every payload file verified",
        "signature": "unsigned",
        "windows_execution": "NOT_EXECUTED",
    }
    args.output.with_suffix(".build.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
