"""Build the scripts distribution, excluding every executable and private runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path) -> dict:
    from orquestrador_app import VERSION

    files = [
        *sorted((ROOT / "orquestrador_app").glob("*.py")),
        ROOT / "orquestrador_app/locales.json",
        *sorted((ROOT / "scripts").glob("*.py")),
        *sorted(p for p in (ROOT / "assets").glob("*") if p.is_file()),
        *[
            ROOT / name
            for name in (
                "caio_gui.py",
                "caio_jobs.py",
                "pipefy_orchestrator.py",
                "automation_schedule.py",
                "requirements-corporate.txt",
                "README.md",
                "docs/TECNICO.md",
                "docs/VALIDACAO.md",
            )
        ],
    ]
    # Legacy agent is not part of the supported portable distribution.
    files = [p for p in files if p.name != "agent.py"]
    assert all(
        p.suffix.casefold() in {".py", ".json", ".ico", ".png", ".svg", ".txt", ".md"}
        for p in files
    )
    hashes = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }
    metadata = {
        "version": VERSION,
        "profile": "portable_gui",
        "private_runtime": False,
        "publisher_claim": None,
        "windows_homologated": False,
        "required_python": "CPython 3.13.5 x64, original corporate-approved pythonw.exe",
        "entry": "caio_gui.py",
        "scheduler_entry": "caio_jobs.py --tick",
        "files": hashes,
    }
    prefix = f"CAIO_Portatil_Scripts_{VERSION}/"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in files:
            archive.write(file, prefix + file.relative_to(ROOT).as_posix())
        archive.writestr(
            prefix + "portable-manifest.json",
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        )
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name, expected in hashes.items():
            assert hashlib.sha256(archive.read(prefix + name)).hexdigest() == expected
    return {
        "artifact": str(output),
        "bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "files": len(files),
        "profile": "portable_gui",
        "private_runtime": False,
        "executable_payloads": [],
        "source_matches_package": True,
        "windows_homologated": False,
    }


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
