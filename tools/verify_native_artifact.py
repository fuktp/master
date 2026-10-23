"""Verify the generated ZIP as data; never execute its Windows binaries."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(source))
    from orquestrador_app.io import digest
    from orquestrador_app.native_install import verify_release
    from orquestrador_app.native_updates import prepare_zip
    from orquestrador_app.paths import Paths

    root = prepare_zip(Paths.user(args.scratch), args.archive, digest(args.archive))
    release = root / "payload"
    record = verify_release(release)
    if list(root.rglob("Orquestrador.exe")):
        raise ValueError("Foi encontrado o executável personalizado anterior.")
    for path in (source / "orquestrador_app").glob("*.py"):
        if digest(path) != digest(release / "src/orquestrador_app" / path.name):
            raise ValueError("Código empacotado diverge do fonte: " + path.name)
    for path in (source / "native").iterdir():
        if path.suffix in {".ps1", ".vbs", ".bat"}:
            packaged = release / "native" / path.name
            if path.read_text(encoding="utf-8-sig") != packaged.read_text(encoding="utf-8-sig"):
                raise ValueError("Script empacotado diverge do fonte: " + path.name)
    entries = {p.name for p in root.iterdir() if p.is_file()}
    from orquestrador_app.uninstallation import PUBLIC_ENTRIES, render_entries

    if entries != {
        "00 - Read Me.md",
        "01 - Instalar.vbs",
        "01 - Instalar(alt).bat",
        *PUBLIC_ENTRIES,
    }:
        raise ValueError("Entradas do ZIP não seguem a sequência numerada.")
    if digest(source / "README.md") != digest(root / "00 - Read Me.md"):
        raise ValueError("Guia empacotado diverge da documentação vigente.")
    for name in ("01 - Instalar.vbs", "01 - Instalar(alt).bat"):
        if "payload\\native\\wizard.ps1" not in (root / name).read_text():
            raise ValueError("Lançador numerado aponta para caminho inválido.")
    for name, expected in render_entries(release / "native").items():
        if (root / name).read_bytes() != expected:
            raise ValueError("Entrada de abertura/desinstalação divergente: " + name)
    import pefile

    from orquestrador_app.windows_hosts import HOST_DESCRIPTIONS

    original_hash = digest(release / "runtime/pythonw.exe")
    original = pefile.PE(str(release / "runtime/pythonw.exe"))
    if not original.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size:
        raise ValueError("O runtime original não contém a assinatura upstream esperada.")
    original.close()
    for name in HOST_DESCRIPTIONS:
        if digest(release / "runtime" / name) != original_hash:
            raise ValueError("Host CAIO alterou bytes/assinatura do Python original: " + name)
    for name in ("locales.json",):
        if digest(source / "orquestrador_app" / name) != digest(
            release / "src/orquestrador_app" / name
        ):
            raise ValueError("Catálogo empacotado diverge do fonte.")
    if digest(source / "assets/caio.ico") != digest(release / "assets/orquestrador.ico"):
        raise ValueError("Logo incorreta no pacote.")
    for path in (source / "assets").iterdir():
        if path.is_file() and digest(path) != digest(release / "assets" / path.name):
            raise ValueError("Asset empacotado diverge do fonte: " + path.name)
    binary = (release / "runtime/pythonw.exe").read_bytes()
    offset = struct.unpack_from("<I", binary, 0x3C)[0]
    if (
        binary[offset : offset + 4] != b"PE\0\0"
        or struct.unpack_from("<H", binary, offset + 4)[0] != 0x8664
        or struct.unpack_from("<H", binary, offset + 92)[0] != 2
    ):
        raise ValueError("O runtime deve ser Windows x64 gráfico.")
    result = {
        "archive": args.archive.name,
        "sha256": digest(args.archive),
        "payload_files_verified": len(record["files"]),
        "source_matches_package": True,
        "private_runtime": "Windows x64 GUI PE",
        "named_process_hosts": HOST_DESCRIPTIONS,
        "process_hosts_byte_identical_to_original": True,
        "original_interpreter_sha256": original_hash,
        "windows_signature_trust_verified": False,
        "root_open_and_uninstall_entries_verified": True,
        "windows_runtime_executed": False,
        "winforms_executed": False,
        "scheduled_tasks_executed": False,
        "extracted_root": str(root),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
