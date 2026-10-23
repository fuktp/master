from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = PACKAGE_ROOT / "scripts"


class ExtractorPathTests(unittest.TestCase):
    def _load(self, filename: str, module_name: str, output: Path, work: Path):
        driver = work / "driver" / "msedgedriver.exe"
        environment = {
            "PIPEFY_OUTPUT_DIR": str(output),
            "PIPEFY_WORK_DIR": str(work),
            "PIPEFY_EDGE_DRIVER_PATH": str(driver),
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            spec = importlib.util.spec_from_file_location(
                module_name,
                SCRIPTS_ROOT / filename,
            )
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        return module, driver

    def test_eventos_uses_existing_history_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "PBi"
            work = root / "extraction" / ".pipefy_orchestrator" / "downloads"
            module, driver = self._load(
                "pipefy_eventos_tool_edge.py",
                "test_eventos_paths",
                output,
                work,
            )
            args = module.build_parser().parse_args(["run"])
            self.assertEqual(
                Path(args.history_csv),
                output / "historico" / "historico_reports.csv",
            )
            self.assertEqual(Path(args.download_dir), work / "eventos")
            self.assertEqual(module.EDGE_DRIVER_PATH, driver)

    def test_clientes_uses_clientes_subfolder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "PBi"
            work = root / "extraction" / ".pipefy_orchestrator" / "downloads"
            module, _ = self._load(
                "pipefy_clientes_tool_edge.py",
                "test_clientes_paths",
                output,
                work,
            )
            args = module.build_parser().parse_args(["run"])
            self.assertEqual(Path(args.clients_dir), output / "clientes")
            self.assertEqual(Path(module.DEFAULT_CLIENTS_STAGING_DIR), work / "clientes")

    def test_procedimentos_uses_procedimentos_subfolder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "PBi"
            work = root / "extraction" / ".pipefy_orchestrator" / "downloads"
            module, _ = self._load(
                "pipefy_procedimentos_tool_edge.py",
                "test_procedimentos_paths",
                output,
                work,
            )
            args = module.build_parser().parse_args(["run"])
            self.assertEqual(Path(args.procedures_dir), output / "procedimentos")
            self.assertEqual(
                Path(module.DEFAULT_PROCEDURES_STAGING_DIR),
                work / "procedimentos",
            )

    def test_all_extractors_isolate_invalid_edge_profile_json(self) -> None:
        filenames = (
            "pipefy_eventos_tool_edge.py",
            "pipefy_clientes_tool_edge.py",
            "pipefy_procedimentos_tool_edge.py",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, filename in enumerate(filenames):
                with self.subTest(filename=filename):
                    output = root / f"PBi-{index}"
                    work = root / f"work-{index}"
                    module, _ = self._load(
                        filename,
                        f"test_profile_repair_{index}",
                        output,
                        work,
                    )
                    profile = root / f"profile-{index}"
                    default = profile / "Default"
                    default.mkdir(parents=True)
                    preferences = default / "Preferences"
                    local_state = profile / "Local State"
                    preferences.write_bytes(b"")
                    local_state.write_bytes(b"{invalid")

                    with mock.patch.object(module.time, "sleep"):
                        backups = module.repair_invalid_edge_profile_json(profile)

                    self.assertEqual(len(backups), 2)
                    self.assertFalse(preferences.exists())
                    self.assertFalse(local_state.exists())
                    self.assertEqual(
                        {backup.read_bytes() for backup in backups},
                        {b"", b"{invalid"},
                    )
                    self.assertTrue(
                        all(".invalid-" in backup.name for backup in backups)
                    )

    def test_profile_repair_preserves_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module, _ = self._load(
                "pipefy_clientes_tool_edge.py",
                "test_profile_valid_json",
                root / "PBi",
                root / "work",
            )
            profile = root / "profile"
            default = profile / "Default"
            default.mkdir(parents=True)
            preferences = default / "Preferences"
            local_state = profile / "Local State"
            preferences.write_text('{"profile": {}}', encoding="utf-8")
            local_state.write_text('{"browser": {}}', encoding="utf-8")

            backups = module.repair_invalid_edge_profile_json(profile)

            self.assertEqual(backups, ())
            self.assertEqual(preferences.read_text(encoding="utf-8"), '{"profile": {}}')
            self.assertEqual(local_state.read_text(encoding="utf-8"), '{"browser": {}}')

    def test_extractor_accepts_scheduled_headless_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module, _ = self._load(
                "pipefy_clientes_tool_edge.py",
                "test_scheduled_headless_command",
                root / "PBi",
                root / "work",
            )
            args = module.build_parser().parse_args(
                [
                    "--log-file",
                    str(root / "clientes.log"),
                    "run",
                    "--headless",
                    "--weekdays-only",
                ]
            )

            self.assertEqual(args.command, "run")
            self.assertTrue(args.headless)
            self.assertTrue(args.weekdays_only)


if __name__ == "__main__":
    unittest.main()
