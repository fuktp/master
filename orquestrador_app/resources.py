from __future__ import annotations

import sys
from pathlib import Path


def source_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def asset_path(name: str) -> Path:
    for base in (source_root() / "assets", source_root().parent / "assets"):
        path = base / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"Recurso do aplicativo ausente: {name}")


def script_path(value: str) -> Path:
    if value.startswith("bundle:"):
        relative = Path(value.removeprefix("bundle:"))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Caminho de recurso inválido.")
        return source_root() / relative
    return Path(value)
