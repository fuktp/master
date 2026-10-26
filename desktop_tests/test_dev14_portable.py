from __future__ import annotations

import io
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from orquestrador_app import portable, portable_driver
from orquestrador_app.config import load, save
from orquestrador_app.io import BusyError, Lock, atomic_json, digest, read_json
from orquestrador_app.monitor_status import monitor_state
from orquestrador_app.paths import Paths
from orquestrador_app.resources import source_root
from orquestrador_app.store import Store
from orquestrador_app.tasks import NS


def test_import_preserves_origin_rules_wal_and_history_without_browser_profile(
    tmp_path: Path,
) -> None:
    origin = Paths.user(tmp_path / "dev12")
    origin.ensure()
    config = portable.prepare(origin)
    config.email = "teste@example.invalid"
    config.routines[0].schedule.times = ["08:00", "16:00"]
    config.routines[0].package_root = str(tmp_path / "old-code")
    config.routines[0].retries["driver"].attempts = 3
    save(origin, config)
    store = Store(origin.database)
    run = store.begin("batch", config.routines[0].id, "manual", None)
    store.finish(run, "success", 0)
    (Path(config.profile)).mkdir(parents=True)
    (Path(config.profile) / "Cookies").write_bytes(b"private")
    before = digest(origin.config)
    target = Paths.user(tmp_path / "dados")
    preview = portable.import_preview(origin.root, target)
    imported = portable.prepare(target, load(origin))
    portable.initialize(target, imported, origin.root)
    assert digest(origin.config) == before
    assert not preview["browser_profile_copied"]
    assert not (Path(imported.profile) / "Cookies").exists()
    assert load(target).routines[0].schedule.times == ["08:00", "16:00"]
    assert load(target).routines[0].retries["driver"].attempts == 3
    assert Store(target.database).history()[0]["id"] == run
    assert imported.scheduling_paused and not imported.install_schedules
    assert imported.routines[0].package_root == ""
    assert not (target.root / "installation.json").exists()
    with pytest.raises(ValueError, match="configurada"):
        portable.initialize(target, imported)


def test_code_data_separation_and_no_overwrite_of_unrelated_folder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Separe"):
        portable.validate_root(Paths.user(source_root() / "data"))
    target = tmp_path / "other"
    target.mkdir()
    (target / "original.txt").write_text("keep")
    with pytest.raises(ValueError, match="existentes"):
        portable.initialize(Paths.user(target), portable.prepare(Paths.user(target)))
    assert (target / "original.txt").read_text() == "keep"


def test_export_task_disabled_nonresident_original_interpreter(tmp_path: Path) -> None:
    paths = Paths.user(tmp_path)
    target = tmp_path / "task.xml"
    report = portable.export_task(paths, target)
    root = ET.fromstring(target.read_text(encoding="utf-16"))

    def find(path: str) -> Any:
        return root.findtext("/".join("{" + NS + "}" + part for part in path.split("/")))

    assert find("Actions/Exec/Command") == sys.executable
    assert "caio_jobs.py" in find("Actions/Exec/Arguments")
    assert "--tick" in find("Actions/Exec/Arguments")
    assert "--agent" not in target.read_text(encoding="utf-16")
    assert find("Settings/Enabled") == "false" == str(report["enabled"]).lower()
    assert find("Principals/Principal/LogonType") == "InteractiveToken"
    assert find("Principals/Principal/RunLevel") == "LeastPrivilege"
    assert find("Settings/MultipleInstancesPolicy") == "IgnoreNew"
    assert find("Triggers/CalendarTrigger/Repetition/Interval") == "PT1M"
    assert portable.task_name(paths) != "\\CAIO-Scripts-other"


def test_tick_backend_does_not_import_qt_or_start_agent_and_releases_locks(tmp_path: Path) -> None:
    paths = Paths.user(tmp_path / "data")
    config = portable.prepare(paths)
    portable.initialize(paths, config)
    code = "from pathlib import Path; import sys; from orquestrador_app.portable import tick; from orquestrador_app.paths import Paths; assert tick(Paths.user(sys.argv[1])) == 0; assert not any(k.startswith('PySide6') for k in sys.modules)"
    subprocess.run(
        [sys.executable, "-B", "-c", code, str(paths.root)],
        check=True,
        timeout=30,
        cwd=source_root(),
    )
    with Lock(paths.lock), Lock(paths.root / "state/scheduler-tick.lock"):
        pass
    assert read_json(paths.root / "state/scheduler-check.json")["state"] == "complete"
    assert not monitor_state(paths, config)["unexpected_stop"]
    assert monitor_state(paths, config)["last_seen"]


def test_tick_skips_overlap_and_records_real_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = Paths.user(tmp_path)
    save(paths, portable.prepare(paths))
    with Lock(paths.lock):
        assert portable.tick(paths) == 0
    assert read_json(paths.root / "state/scheduler-check.json")["state"] == "busy"
    from orquestrador_app.engine import Engine

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("policy denied")

    monkeypatch.setattr(Engine, "preview", lambda *_, **__: [{"status": "simulation"}])
    monkeypatch.setattr(Engine, "run", fail)
    with pytest.raises(RuntimeError, match="policy denied"):
        portable.tick(paths)
    assert read_json(paths.root / "state/scheduler-check.json")["error"] == "policy denied"


def test_process_commands_use_original_interpreter_and_explicit_scripts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orquestrador_app.processes import command

    monkeypatch.setenv("CAIO_EXECUTION_PROFILE", "portable_gui")
    assert command("--worker", "job") == [
        sys.executable,
        "-B",
        str(source_root() / "caio_jobs.py"),
        "--worker",
        "job",
    ]
    assert command("--data-root", "dados")[2].endswith("caio_gui.py")


def archive_bytes(data: bytes = b"candidate") -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("msedgedriver.exe", data)
    return stream.getvalue()


def driver_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Paths, Any, Any, list[str]]:
    paths = Paths.user(tmp_path)
    paths.ensure()
    config = portable.prepare(paths)
    target = Path(config.driver)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    calls: list[str] = []
    instance = SimpleNamespace(
        edge_policy_status=lambda: {},
        detect_edge_binary=lambda: Path("edge"),
        edge_version=lambda _: (140, 0, 1, 1),
        driver_version=lambda _: (140, 0, 1, 2),
    )
    monkeypatch.setattr(portable_driver, "guard", lambda *_: instance)
    monkeypatch.setattr(
        portable_driver,
        "signed_version",
        lambda _, file: (140, 0, 1, 1) if file.read_bytes() == b"old" else (140, 0, 1, 2),
    )

    def fetch(url: str, maximum: int) -> bytes:
        calls.append(url)
        return b"140.0.1.2" if "LATEST_RELEASE" in url else archive_bytes()

    monkeypatch.setattr(portable_driver, "fetch", fetch)
    return paths, config, instance, calls


def test_driver_update_cache_edge_change_and_previous_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, config, instance, calls = driver_fixture(tmp_path, monkeypatch)
    old = digest(Path(config.driver))
    result = portable_driver.check(paths, config, repair=True)
    assert result["driver_version"] == "140.0.1.2"
    assert len(calls) == 2
    backup = paths.root / "cache/driver/previous" / old / "msedgedriver.exe"
    assert backup.read_bytes() == b"old"
    assert portable_driver.check(paths, config, repair=True)["metadata_cached"]
    assert len(calls) == 2
    instance.edge_version = lambda _: (140, 0, 1, 2)
    portable_driver.check(paths, config, repair=True)
    assert len(calls) == 3
    portable_driver.check(paths, config, repair=True, force=True)
    assert len(calls) == 4


def test_invalid_signature_never_executes_candidate_and_keeps_previous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, config, instance, calls = driver_fixture(tmp_path, monkeypatch)

    def trusted_only_current(_: Any, file: Path) -> tuple[int, ...]:
        if file.read_bytes() != b"old":
            raise RuntimeError("signature denied")
        return (140, 0, 1, 1)

    monkeypatch.setattr(portable_driver, "signed_version", trusted_only_current)
    instance.driver_version = lambda _: pytest.fail("Untrusted candidate executed")
    with pytest.raises(RuntimeError, match="signature denied"):
        portable_driver.check(paths, config, repair=True)
    assert Path(config.driver).read_bytes() == b"old"
    assert len(calls) == 2
    assert read_json(paths.root / "state/portable-driver.json")["status"] == "error"


def test_policy_denial_stops_before_any_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, config, instance, calls = driver_fixture(tmp_path, monkeypatch)
    instance.edge_policy_status = lambda: {"DeveloperToolsAvailability": 2}
    with pytest.raises(RuntimeError, match="política"):
        portable_driver.check(paths, config, repair=True)
    assert calls == []
    assert Path(config.driver).read_bytes() == b"old"


@pytest.mark.parametrize(
    "url",
    [
        "http://msedgedriver.microsoft.com/file",
        "https://evil.invalid/file",
        "https://msedgedriver.microsoft.com.evil.invalid/file",
        "https://user@msedgedriver.microsoft.com/file",
    ],
)
def test_download_redirect_origin_is_restricted(url: str) -> None:
    with pytest.raises(ValueError, match="Origem"):
        portable_driver.official(url)
    portable_driver.official("https://msedgedriver.microsoft.com/140.0.1.2/edgedriver_win64.zip")


def test_driver_activation_defers_while_execution_lock_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from orquestrador_app.gui import MainWindow

    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    paths.ensure()
    save(paths, portable.prepare(paths))
    Store(paths.database)
    window = MainWindow(paths, observe=False)
    operations: list[Any] = []
    monkeypatch.setattr(window, "background", operations.append)
    monkeypatch.setattr(
        portable_driver,
        "check",
        lambda *_, **__: pytest.fail("Update started while a routine owns execution.lock"),
    )
    try:
        window.driver_operation(True)
        with Lock(paths.lock):
            with pytest.raises(BusyError):
                operations[0]()
    finally:
        window.exit_requested = True
        window.close()
        app.processEvents()


def test_graphical_profile_skips_windows_identity_and_installer_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication, QPushButton

    from orquestrador_app import windows_identity
    from orquestrador_app.gui import MainWindow

    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    paths.ensure()
    save(paths, portable.prepare(paths))
    Store(paths.database)
    monkeypatch.setattr(
        windows_identity, "set_process_identity", lambda _: pytest.fail("AppID called")
    )
    window = MainWindow(paths, observe=False)
    try:
        texts = [b.text() for b in window.findChildren(QPushButton)]
        assert "Exportar tarefa para a TI…" in texts
        assert "Instalar/atualizar tarefa" not in texts
        assert "Desinstalar CAIO e preservar dados…" not in texts
        assert "Remover arquivos do CAIO…" in texts
        window.render_monitor(monitor_state(paths, window.config, installed=True))
        assert "sem monitor residente" in window.monitor_status_label.text()
    finally:
        window.exit_requested = True
        window.close()
        app.processEvents()


def test_first_use_inline_validation_and_locale_preserve_values(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from orquestrador_app.i18n import set_language
    from orquestrador_app.portable_gui import SetupDialog

    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path / "dados")
    dialog = SetupDialog(paths)
    try:
        dialog.editor.email.setText("invalid")
        dialog.commit()
        assert dialog.error.text()
        assert not paths.config.exists()
        dialog.editor.email.setText("first@example.invalid")
        dialog.language.setCurrentIndex(1)
        assert dialog.editor.email.text() == "first@example.invalid"
        assert dialog.windowTitle() == "Set up CAIO data"
        dialog.language.setCurrentIndex(2)
        assert dialog.editor.email.text() == "first@example.invalid"
        dialog.editor.email.setText("invalid")
        dialog.commit()
        assert "correo" in dialog.error.text()
    finally:
        dialog.reject()
        app.processEvents()
        set_language("pt-BR")


def test_signed_version_requires_trusted_microsoft_subject_without_executing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    monkeypatch.setattr(portable_driver, "os", SimpleNamespace(name="nt"))
    calls: list[str] = []
    subject = "CN=Microsoft Corporation, O=Microsoft Corporation, C=US"

    def output(command: str, environment: dict[str, str]) -> str:
        calls.append(command)
        assert environment == {"CAIO_DRIVER_FILE": str(tmp_path / "msedgedriver.exe")}
        return json.dumps({"status": "Valid", "subject": subject, "version": "140.0.1.2"})

    instance = SimpleNamespace(_powershell_output=output)
    assert portable_driver.signed_version(instance, tmp_path / "msedgedriver.exe") == (140, 0, 1, 2)
    assert "Get-AuthenticodeSignature" in calls[0]
    assert "Bypass" not in calls[0] and "EncodedCommand" not in calls[0]
    subject = "CN=Unrelated Publisher, O=Microsoft Corporation"
    with pytest.raises(RuntimeError, match="Microsoft"):
        portable_driver.signed_version(instance, tmp_path / "msedgedriver.exe")


def test_zip_version_mismatch_fails_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(portable_driver, "signed_version", lambda *_: (139, 0, 1, 2))
    instance = SimpleNamespace(driver_version=lambda _: pytest.fail("Version mismatch executed"))
    with pytest.raises(ValueError, match="versão assinada"):
        portable_driver.stage(instance, archive_bytes(), (140, 0, 1, 2), tmp_path)


def test_portable_package_contains_no_executable_runtime_or_install_wrappers(
    tmp_path: Path,
) -> None:
    from tools.build_portable_zip import build

    target = tmp_path / "portable.zip"
    report = build(target)
    assert report["private_runtime"] is False
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert all(
            Path(name).suffix.casefold() not in {".exe", ".dll", ".pyd", ".ps1", ".bat", ".vbs"}
            for name in names
        )
        assert any(name.endswith("/caio_gui.py") for name in names)
        assert any(name.endswith("/caio_jobs.py") for name in names)
        assert not any(name.endswith("/agent.py") for name in names)
        for source in (source_root() / "scripts").glob("*.py"):
            name = next(name for name in names if name.endswith("/scripts/" + source.name))
            assert archive.read(name) == source.read_bytes()


def test_expired_driver_metadata_rechecks_and_corrupt_cache_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, config, instance, calls = driver_fixture(tmp_path, monkeypatch)
    portable_driver.check(paths, config, repair=True)
    file = paths.root / "state/portable-driver.json"
    state = read_json(file)
    state["checked_at"] = "2020-01-01T00:00:00+00:00"
    atomic_json(file, state)
    portable_driver.check(paths, config, repair=True)
    assert len(calls) == 3
    file.write_text("damaged metadata")
    portable_driver.check(paths, config, repair=True)
    assert len(calls) == 4 and read_json(file)["status"] == "ready"


def test_legacy_entry_cannot_start_agent_or_uninstall_portable_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orquestrador_app.__main__ import main

    paths = Paths.user(tmp_path)
    paths.ensure()
    save(paths, portable.prepare(paths))
    monkeypatch.setenv("CAIO_EXECUTION_PROFILE", "desktop")
    for argument in ("--agent", "--uninstall", "configure-schedules"):
        with pytest.raises(ValueError, match="modo por scripts"):
            main(["--data-root", str(paths.root), argument])
    assert not (paths.root / "installation.json").exists()
