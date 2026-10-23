"""Fetch and verify the pinned Windows build inputs; never run downloaded scripts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(item: dict[str, Any], cache: Path) -> Path:
    file = cache / item["filename"]
    if not file.is_file() or checksum(file) != item["sha256"]:
        temporary = file.with_suffix(file.suffix + ".partial")
        with (
            urllib.request.urlopen(item["url"], timeout=120) as response,
            temporary.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
        if checksum(temporary) != item["sha256"]:
            temporary.unlink(missing_ok=True)
            raise ValueError(f"Hash inválido: {file.name}")
        temporary.replace(file)
    return file


def unpack(file: Path, destination: Path, wheel: bool = False) -> None:
    with zipfile.ZipFile(file) as archive:
        for entry in archive.infolist():
            name = entry.filename.replace("\\", "/")
            if wheel and ".data/" in name:
                parts = name.split(".data/", 1)[1].split("/", 1)
                if len(parts) != 2 or parts[0] not in {"purelib", "platlib"}:
                    continue
                name = parts[1]
            target = destination / name
            if ":" in name or not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Caminho inválido em dependência.")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "build_inputs/windows-x64.json",
    )
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.output.exists():
        raise ValueError("Escolha uma pasta nova para preparar o runtime de build.")
    args.cache.mkdir(parents=True, exist_ok=True)
    inputs = [manifest["embed"], *manifest["wheels"]]
    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(lambda item: fetch(item, args.cache), inputs))
    args.output.mkdir(parents=True, exist_ok=False)
    unpack(args.cache / manifest["embed"]["filename"], args.output)
    packages = args.output / "Lib/site-packages"
    packages.mkdir(parents=True, exist_ok=True)
    for item in manifest["wheels"]:
        unpack(args.cache / item["filename"], packages, wheel=True)
    (packages / "private-pywin32.pth").write_text("win32\nwin32/lib\nPythonwin\n", encoding="utf-8")
    for file in sorted((packages / "pywin32_system32").glob("*.dll")):
        shutil.copy2(file, args.output / file.name)
    hashes = {item["filename"]: item["sha256"] for item in manifest["wheels"]}
    (args.output / "wheels-sha256.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "python": manifest["python_version"],
                "runtime": str(args.output.resolve()),
                "verified_inputs": len(inputs),
            }
        )
    )


if __name__ == "__main__":
    main()
