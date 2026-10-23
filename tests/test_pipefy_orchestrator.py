from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import logging
import io
import subprocess
import zipfile
from unittest import mock
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

import pipefy_orchestrator as module


class VersionTests(unittest.TestCase):
    def test_package_version(self) -> None:
        self.assertEqual(module.APP_VERSION, "1.3.0")

    def test_parse_version_from_driver_output(self) -> None:
        self.assertEqual(
            module.parse_version("MSEdgeDriver 152.0.4191.41"),
            (152, 0, 4191, 41),
        )

    def test_compatibility_uses_first_three_components(self) -> None:
        self.assertTrue(
            module.versions_compatible(
                (152, 0, 4191, 53),
                (152, 0, 4191, 41),
            )
        )
        self.assertFalse(
            module.versions_compatible(
                (152, 0, 4191, 53),
                (150, 0, 4078, 105),
            )
        )

    def test_driver_error_detection(self) -> None:
        self.assertTrue(
            module.contains_driver_error(
                [
                    "session not created",
                    "This version of Microsoft Edge WebDriver only supports "
                    "Microsoft Edge version 152",
                ]
            )
        )
        self.assertFalse(
            module.contains_driver_error(
                ["session not created", "cannot parse internal JSON template"]
            )
        )
        self.assertFalse(module.contains_driver_error(["Falha HTTP 500 do Pipefy"]))

    def test_profile_error_detection(self) -> None:
        self.assertTrue(
            module.contains_profile_error(
                ["session not created", "cannot parse internal JSON template"]
            )
        )
        self.assertTrue(
            module.contains_profile_error(
                ["user data directory is already in use"]
            )
        )
        self.assertFalse(
            module.contains_profile_error(
                ["This version of Microsoft Edge WebDriver only supports 152"]
            )
        )

    def test_unavailable_signature_is_not_invalid(self) -> None:
        self.assertFalse(
            module.signature_status_is_invalid("Unavailable (WinVerifyTrust: blocked)")
        )
        self.assertFalse(module.signature_status_is_invalid("Valid"))
        self.assertTrue(module.signature_status_is_invalid("HashMismatch"))

    def test_rewrite_only_absolute_driver_path_literals(self) -> None:
        source = (
            "DRIVER = r'C:\\\\Users\\\\user\\\\Downloads\\\\old\\\\msedgedriver.exe'\n"
            "NAME = 'msedgedriver.exe'\n"
            "MESSAGE = 'Use o arquivo msedgedriver.exe'\n"
        )
        managed = Path(r"C:\Users\user\Downloads\new\msedgedriver.exe")
        rewritten, replacements = module.rewrite_driver_path_literals(source, managed)
        self.assertEqual(replacements, 1)
        namespace: dict[str, str] = {}
        exec(rewritten, namespace)
        self.assertEqual(namespace["DRIVER"], str(managed))
        self.assertEqual(namespace["NAME"], "msedgedriver.exe")
        self.assertEqual(namespace["MESSAGE"], "Use o arquivo msedgedriver.exe")


class ConfigTests(unittest.TestCase):
    def test_packaged_discovery_runs_headless_on_weekdays(self) -> None:
        config = json.loads(
            (PACKAGE_ROOT / "pipefy_orchestrator.config.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            config["discovery"]["command_arguments"],
            ["--headless", "--weekdays-only"],
        )
        self.assertEqual(config["discovery"]["options"], [])

    def test_run_arguments_follow_subcommand_and_are_omitted_for_login(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "pipefy_dummy_tool_edge.py"
            script.write_text("pass\n", encoding="utf-8")
            config = {
                "schema_version": 1,
                "project_root": ".",
                "driver": {"managed_path": "driver/msedgedriver.exe"},
                "discovery": {
                    "enabled": True,
                    "pattern": "pipefy_*_tool_edge.py",
                    "inject_log_file": True,
                    "options": [],
                    "command": "run",
                    "command_arguments": ["--headless", "--weekdays-only"],
                },
            }
            config_path = root / "pipefy_orchestrator.config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = module.load_settings(config_path)
            orchestrator = module.Orchestrator(
                settings,
                logging.getLogger("pipefy_command_order_test"),
            )

            run_command = orchestrator.command_for(settings.jobs[0])
            login_command = orchestrator.command_for(
                settings.jobs[0],
                action_override="login",
            )

            self.assertEqual(
                run_command[-3:],
                ["run", "--headless", "--weekdays-only"],
            )
            self.assertEqual(login_command[-1], "login")
            self.assertNotIn("--headless", login_command)
            self.assertNotIn("--weekdays-only", login_command)

    def test_task_installer_does_not_resolve_script_root_in_param_block(self) -> None:
        installer = (PACKAGE_ROOT / "install_tasks.ps1").read_text(encoding="utf-8")
        param_block, body = installer.split(")\n\n", 1)
        self.assertNotIn("$PSScriptRoot", param_block)
        self.assertIn("$MyInvocation.MyCommand.Path", body)
        self.assertIn("Join-Path -Path $ScriptRoot", body)

    def test_discovery_and_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pipefy_eventos_tool_edge.py").write_text("pass\n", encoding="utf-8")
            config = {
                "schema_version": 1,
                "project_root": ".",
                "driver": {"managed_path": "driver/msedgedriver.exe"},
                "discovery": {
                    "enabled": True,
                    "pattern": "pipefy_*_tool_edge.py",
                    "inject_log_file": True,
                    "command": "run",
                },
                "jobs": [
                    {
                        "name": "pipefy_eventos_tool_edge",
                        "script": "pipefy_eventos_tool_edge.py",
                        "command": "extract",
                        "options": ["--custom"],
                    }
                ],
                "schedules": ["08:30"],
            }
            path = root / "pipefy_orchestrator.config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            settings = module.load_settings(path)
            self.assertEqual(len(settings.jobs), 1)
            self.assertEqual(settings.jobs[0].command, "extract")
            self.assertEqual(settings.jobs[0].options, ("--custom",))
            self.assertEqual(
                settings.driver.driver_mirror_url,
                "https://msedgedriver.microsoft.com",
            )

    def test_windows_environment_syntax(self) -> None:
        previous = os.environ.get("PIPEFY_TEST_ROOT")
        os.environ["PIPEFY_TEST_ROOT"] = "C:\\Pipefy"
        try:
            self.assertEqual(
                module.expand_environment("%PIPEFY_TEST_ROOT%\\logs"),
                "C:\\Pipefy\\logs",
            )
        finally:
            if previous is None:
                os.environ.pop("PIPEFY_TEST_ROOT", None)
            else:
                os.environ["PIPEFY_TEST_ROOT"] = previous

    def test_driver_mirror_requires_https(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "schema_version": 1,
                "driver": {
                    "managed_path": "driver/msedgedriver.exe",
                    "driver_mirror_url": "http://example.test",
                },
            }
            path = root / "pipefy_orchestrator.config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(module.OrchestratorError):
                module.load_settings(path)

    def test_output_directory_is_available_to_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "dummy.py"
            script.write_text("pass\n", encoding="utf-8")
            config = {
                "schema_version": 1,
                "project_root": ".",
                "output_dir": "data",
                "runtime_dir": "state",
                "driver": {"managed_path": "driver/msedgedriver.exe"},
                "jobs": [
                    {
                        "name": "dummy",
                        "script": "dummy.py",
                        "command": "run",
                        "command_arguments": ["--output", "{output_dir}"],
                        "environment": {"CUSTOM_OUTPUT": "{output_dir}"},
                    }
                ],
            }
            config_path = root / "pipefy_orchestrator.config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = module.load_settings(config_path)
            orchestrator = module.Orchestrator(
                settings,
                logging.getLogger("pipefy_output_dir_test"),
            )
            command = orchestrator.command_for(settings.jobs[0])
            environment = orchestrator._job_environment(settings.jobs[0])
            expected = str((root / "data").resolve())
            self.assertEqual(str(settings.output_dir), expected)
            self.assertEqual(command[-1], expected)
            self.assertEqual(environment["PIPEFY_OUTPUT_DIR"], expected)
            self.assertEqual(environment["CUSTOM_OUTPUT"], expected)


class OrchestrationTests(unittest.TestCase):
    def test_profile_failure_does_not_reinstall_approved_driver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extractor = root / "dummy_extractor.py"
            extractor.write_text("raise SystemExit(1)\n", encoding="utf-8")
            config = {
                "schema_version": 1,
                "project_root": ".",
                "runtime_dir": "state",
                "driver": {"managed_path": "driver/msedgedriver.exe"},
                "jobs": [
                    {
                        "name": "dummy",
                        "script": "dummy_extractor.py",
                        "command": "",
                        "retries": 1,
                        "retry_delay_seconds": 0,
                    }
                ],
            }
            config_path = root / "pipefy_orchestrator.config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = module.load_settings(config_path)
            logger = logging.getLogger("pipefy_profile_classification_test")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            orchestrator = module.Orchestrator(settings, logger)

            with mock.patch.object(
                orchestrator,
                "_run_process",
                return_value=(
                    1,
                    [
                        "session not created",
                        "cannot parse internal JSON template",
                    ],
                    False,
                ),
            ), mock.patch.object(orchestrator.driver_guard, "ensure") as ensure:
                result = orchestrator._run_job(settings.jobs[0])

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.attempts, 2)
            ensure.assert_not_called()

    def test_official_mirror_fallback_extracts_driver(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = {
                "schema_version": 1,
                "project_root": ".",
                "runtime_dir": "state",
                "logs_dir": "logs",
                "driver": {
                    "managed_path": "driver/msedgedriver.exe",
                    "selenium_cache": "cache",
                    "verify_authenticode": False,
                },
            }
            config_path = root / "pipefy_orchestrator.config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = module.load_settings(config_path)
            logger = logging.getLogger("pipefy_driver_fallback_test")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            guard = module.DriverGuard(settings, logger)
            archive_buffer = io.BytesIO()
            with zipfile.ZipFile(archive_buffer, "w") as archive:
                archive.writestr("Driver_Notes/notes.txt", "test")
                archive.writestr("msedgedriver.exe", b"MZ-fake-driver")

            def fake_download(url: str, maximum_bytes: int) -> bytes:
                if "LATEST_RELEASE" in url:
                    return b"152.0.4191.53"
                return archive_buffer.getvalue()

            with mock.patch.object(guard, "_download_bytes", side_effect=fake_download), mock.patch.object(
                guard,
                "driver_version",
                return_value=(152, 0, 4191, 53),
            ):
                driver = guard._download_driver_from_official_mirror(
                    (152, 0, 4191, 53)
                )
            self.assertTrue(driver.is_file())
            self.assertEqual(driver.read_bytes(), b"MZ-fake-driver")

    def test_end_to_end_without_driver_precheck(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extractor = root / "dummy_extractor.py"
            extractor.write_text(
                "import sys\nprint('dummy ok')\nraise SystemExit(0)\n",
                encoding="utf-8",
            )
            config = {
                "schema_version": 1,
                "project_root": ".",
                "python_executable": sys.executable,
                "runtime_dir": "state",
                "logs_dir": "logs",
                "driver": {"managed_path": "driver/msedgedriver.exe"},
                "jobs": [
                    {
                        "name": "dummy",
                        "script": "dummy_extractor.py",
                        "command": "",
                        "retries": 0,
                    }
                ],
            }
            config_path = root / "pipefy_orchestrator.config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = module.load_settings(config_path)
            logger = logging.getLogger("pipefy_orchestrator_test")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            result = module.Orchestrator(settings, logger).run(
                job_names=None,
                delay_seconds=0,
                skip_driver_check=True,
                dry_run=False,
            )
            self.assertEqual(result, 0)
            summary = json.loads(
                (root / "state" / "last_run.json").read_text(encoding="utf-8")
            )
            self.assertTrue(summary["success"])
            self.assertEqual(summary["jobs"][0]["name"], "dummy")

    def test_script_adapter_replaces_old_path_and_keeps_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extractor = root / "dummy_extractor.py"
            extractor.write_text(
                "DRIVER = r'C:\\\\Users\\\\user\\\\Downloads\\\\old\\\\msedgedriver.exe'\n",
                encoding="utf-8",
            )
            config = {
                "schema_version": 1,
                "project_root": ".",
                "runtime_dir": "state",
                "driver": {"managed_path": "driver/msedgedriver.exe"},
                "jobs": [
                    {
                        "name": "dummy",
                        "script": "dummy_extractor.py",
                        "command": "",
                    }
                ],
            }
            config_path = root / "pipefy_orchestrator.config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = module.load_settings(config_path)
            logger = logging.getLogger("pipefy_script_adapter_test")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            orchestrator = module.Orchestrator(settings, logger)
            changed = orchestrator._adapt_job_driver_paths(settings.jobs)
            self.assertEqual(changed, 1)
            namespace: dict[str, str] = {}
            exec(extractor.read_text(encoding="utf-8"), namespace)
            self.assertEqual(namespace["DRIVER"], str(settings.driver.managed_path))
            backups = list((root / "state" / "script_backups").glob("dummy_extractor.*.py"))
            self.assertEqual(len(backups), 1)
            self.assertIn("old", backups[0].read_text(encoding="utf-8"))

    def test_sitecustomize_forces_service_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_modules = root / "fake_modules"
            service_module = fake_modules / "selenium" / "webdriver" / "edge"
            service_module.mkdir(parents=True)
            for package in (
                fake_modules / "selenium",
                fake_modules / "selenium" / "webdriver",
                service_module,
            ):
                (package / "__init__.py").write_text("", encoding="utf-8")
            (service_module / "service.py").write_text(
                "class Service:\n"
                "    def __init__(self, executable_path=None, *args, **kwargs):\n"
                "        self.executable_path = executable_path\n",
                encoding="utf-8",
            )
            extractor = root / "dummy_extractor.py"
            extractor.write_text("raise SystemExit(0)\n", encoding="utf-8")
            config = {
                "schema_version": 1,
                "project_root": ".",
                "runtime_dir": "state",
                "driver": {"managed_path": "driver/msedgedriver.exe"},
                "jobs": [
                    {
                        "name": "dummy",
                        "script": "dummy_extractor.py",
                        "command": "",
                        "environment": {"PYTHONPATH": str(fake_modules)},
                    }
                ],
            }
            config_path = root / "pipefy_orchestrator.config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            settings = module.load_settings(config_path)
            logger = logging.getLogger("pipefy_sitecustomize_test")
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())
            orchestrator = module.Orchestrator(settings, logger)
            environment = orchestrator._job_environment(settings.jobs[0])
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from selenium.webdriver.edge.service import Service; "
                    "print(Service('C:/old/msedgedriver.exe').executable_path)",
                ],
                capture_output=True,
                text=True,
                check=False,
                env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), str(settings.driver.managed_path))
            self.assertTrue((root / "state" / "driver_adapter" / "sitecustomize.py").is_file())


if __name__ == "__main__":
    unittest.main()
