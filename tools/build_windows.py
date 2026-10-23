"""Repository/CI command only. The end user receives the resulting executable."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if sys.platform != "win32":
        raise SystemExit(
            "Build Windows não executado: rode este script em um runner Windows. Nenhum .exe foi gerado."
        )
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    manifest = {}
    for path in sorted((root / "scripts").glob("*.py")):
        manifest[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "payload-manifest.json").write_text(
        json.dumps({"files": manifest}, indent=2), encoding="utf-8"
    )
    import PyInstaller.__main__

    PyInstaller.__main__.run(["--clean", "--noconfirm", "Orquestrador.spec"])
    executable = root / "dist/Orquestrador.exe"
    raw = executable.read_bytes()
    offset = int.from_bytes(raw[0x3C:0x40], "little")
    if raw[:2] != b"MZ" or raw[offset : offset + 4] != b"PE\x00\x00":
        raise RuntimeError("Build não produziu um PE Windows válido.")
    subsystem = int.from_bytes(raw[offset + 24 + 68 : offset + 24 + 70], "little")
    if subsystem != 2:
        raise RuntimeError("O executável não está no subsistema gráfico Windows.")
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([str(executable), "--health-check"], env=environment, check=True, timeout=120)
    record = {
        "filename": executable.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "pe_subsystem": "WINDOWS_GUI",
        "signature": "unsigned; certificado não fornecido",
        "health_check": "passed",
        "end_to_end_clean_windows": "NOT_EXECUTED_BY_BUILD",
    }
    (root / "dist/build-evidence.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
