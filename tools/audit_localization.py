"""Check owned captions/messages and placeholders without rewriting user data or extractor logs."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEUTRAL = {"CAIO", "OK", "SHA-256", "JSON", "CPU", "PID", "RAM", "Python", "SSO/MFA"}
SINKS = {
    "tr",
    "button",
    "explain",
    "QLabel",
    "QPushButton",
    "QCheckBox",
    "QGroupBox",
    "QAction",
    "InstallPage",
}


def literal(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) else "{" + str(i) + "}"
            for i, v in enumerate(node.values)
        )
    return ""


def audit() -> dict:
    entries = json.loads((ROOT / "orquestrador_app/locales.json").read_text(encoding="utf-8"))
    catalog = {source.casefold(): values for source, values in entries.items()}
    errors = []
    if len(catalog) != len(entries):
        errors.append("Catalog keys collide when case is ignored")
    for source, translations in entries.items():
        expected = sorted(re.findall(r"\{\d+\}", source))
        if len(translations) != 2 or not all(
            isinstance(t, str) and t.strip() for t in translations
        ):
            errors.append("Missing en/es translation: " + source)
        elif any(sorted(re.findall(r"\{\d+\}", t)) != expected for t in translations):
            errors.append("Placeholder mismatch: " + source)
    checked = set()
    for file in sorted((ROOT / "orquestrador_app").glob("*.py")):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else ""
            if name not in SINKS:
                continue
            source = literal(node.args[0])
            if not source or source in NEUTRAL or not re.search(r"[A-Za-zÀ-ÿ]", source):
                continue
            checked.add(source)
            # Dynamic strings composed of translated fragments already have explicit tr() calls.
            if isinstance(node.args[0], ast.JoinedStr) and any(
                isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "tr"
                for v in ast.walk(node.args[0])
            ):
                continue
            if source.casefold() not in catalog:
                errors.append(f"{file.name}:{node.lineno}: Missing owned caption: {source}")
    return {
        "catalog_entries": len(entries),
        "owned_literals_checked": len(checked),
        "errors": errors,
        "scope": "Owned Python captions and catalog placeholder parity; Qt/PowerShell runtime checks complement this audit. User data, technical JSON and external logs are not translated.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return bool(result["errors"])


if __name__ == "__main__":
    raise SystemExit(main())
