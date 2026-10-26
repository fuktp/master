"""Inspect the ZIP, then exercise its own sources in separate offline processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = """
from pathlib import Path
import json, sys
from orquestrador_app.config import Routine, save
from orquestrador_app.engine import Engine
from orquestrador_app.paths import Paths
from orquestrador_app.portable import initialize, prepare
paths = Paths.user(sys.argv[1])
config = prepare(paths)
config.email = 'smoke@example.invalid'
initialize(paths, config)
for job in config.routines:
    job.enabled = False
script = paths.root / 'extras/synthetic.py'
script.write_text("from pathlib import Path\\nimport sys\\nfrom openpyxl import Workbook\\np=Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True)\\nb=Workbook();b.active.append(['Header']);b.active.append(['value']);b.save(p/'saida.xlsx');b.close()\\nprint('Relatório ação concluído.')\\n", encoding='utf-8')
job = Routine(id='synthetic', label='Synthetic offline', script=str(script), command='', options=['{output_dir}'], requires_browser=False, target=str(paths.root/'relatorios/saida.xlsx'), staged_output='saida.xlsx')
config.routines.append(job)
save(paths, config)
result = Engine(paths).run([job.id], force=True)
assert result[0]['status'] == 'success', result
assert Path(job.target).is_file()
assert any('ação' in file.read_text(encoding='utf-8') for file in (paths.root/'logs').glob('*.process.log'))
assert not any(name.startswith('PySide6') for name in sys.modules)
print(json.dumps({'status': result[0]['status'], 'published': True, 'utf8_log': True, 'qt_loaded': False}))
"""


def verify(artifact: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="caio-artifact-") as folder:
        temporary = Path(folder)
        with zipfile.ZipFile(artifact) as archive:
            names = archive.namelist()
            assert archive.testzip() is None
            assert all(
                Path(name).suffix.lower() not in {".exe", ".dll", ".pyd", ".ps1", ".bat", ".vbs"}
                for name in names
            )
            assert all(
                not Path(name).is_absolute() and ".." not in Path(name).parts for name in names
            )
            assert sum(info.file_size for info in archive.infolist()) < 20_000_000
            manifest_name = next(name for name in names if name.endswith("/portable-manifest.json"))
            metadata = json.loads(archive.read(manifest_name))
            prefix = manifest_name.removesuffix("portable-manifest.json")
            for name, expected in metadata["files"].items():
                assert hashlib.sha256(archive.read(prefix + name)).hexdigest() == expected
                assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
            archive.extractall(temporary)
        code = temporary / prefix
        environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1"}
        environment.pop("PYTHONPATH", None)
        health = temporary / "health.json"
        subprocess.run(
            [
                sys.executable,
                "-B",
                str(code / "caio_jobs.py"),
                "--health-check",
                "--health-output",
                str(health),
            ],
            cwd=code,
            env=environment,
            check=True,
            capture_output=True,
            timeout=120,
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", SMOKE, str(temporary / "data")],
            cwd=code,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        return {
            "artifact": str(artifact),
            "bytes": artifact.stat().st_size,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "profile": metadata["profile"],
            "files": len(metadata["files"]),
            "source_matches_package": True,
            "private_runtime": False,
            "executable_payloads": [],
            "extracted_health": json.loads(health.read_text()),
            "extracted_worker": json.loads(result.stdout),
            "network_used": False,
            "windows_homologated": False,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.artifact)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
