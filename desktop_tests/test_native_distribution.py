from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path
from typing import Any, Callable

import pytest

from orquestrador_app.config import load, save
from orquestrador_app.io import BusyError, Lock, atomic_json, digest, read_json
from orquestrador_app.native_bridge import preview
from orquestrador_app.native_install import (
    PACKAGE_OWNER,
    NativeInstaller,
    validate_health_report,
    verify_release,
)
from orquestrador_app.native_updates import check_feed, https_host, prepare_zip
from orquestrador_app.paths import Paths
from orquestrador_app.sandbox import prepare_config
from orquestrador_app.store import Store
from orquestrador_app.tasks import NS, xml


class FakeTasks:
    def __init__(self) -> None:
        self.value: str | None = None

    def export(self) -> str | None:
        return self.value

    def install(self, executable: Path, user: str) -> None:
        self.value = str(executable) + user

    def register_xml(self, value: str) -> None:
        self.value = value

    def remove(self) -> None:
        self.value = None


class FakeLinks:
    def __init__(self) -> None:
        self.value = "old links"

    def snapshot(self, folder: Path) -> None:
        (folder / "fixture-links.txt").write_text(self.value)

    def install(self) -> None:
        self.value = "new links"

    def restore(self, folder: Path) -> None:
        file = folder / "fixture-links.txt"
        self.value = file.read_text() if file.is_file() else ""


def make_payload(folder: Path, version: str = "2.0.0.dev99") -> Path:
    folder.mkdir(parents=True)
    for name in (
        "runtime/pythonw.exe",
        "src/desktop_entry.py",
        "native/wizard.ps1",
        "native/Update.ps1",
        "native/Iniciar.vbs",
        "native/Abrir.ps1",
        "assets/orquestrador.ico",
    ):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture only; not a Windows executable: " + name)
    record = {
        "owner": PACKAGE_OWNER,
        "distribution": "native-scripts",
        "version": version,
        "files": {
            p.relative_to(folder).as_posix(): digest(p) for p in folder.rglob("*") if p.is_file()
        },
    }
    atomic_json(folder / "release.json", record)
    return folder


@pytest.fixture
def native(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, ...]:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local app data"))
    payload = make_payload(tmp_path / "input/payload")
    paths = Paths.user(tmp_path / "João e Maria/teste separado")
    config = prepare_config(paths)
    tasks, links = FakeTasks(), FakeLinks()
    installer = NativeInstaller(paths, tasks=tasks, links=links, health=lambda _: None)
    return installer, paths, config, payload, tasks, links


def test_install_private_runtime_without_global_python_or_original_replacement(
    native: tuple[Any, ...], tmp_path: Path
) -> None:
    installer, paths, config, payload, _, links = native
    original = tmp_path / "produção/original.xlsx"
    original.parent.mkdir()
    original.write_bytes(b"original report")
    launcher = installer.install(payload, config)
    pointer = read_json(installer.pointer)
    assert pointer["distribution"] == "native-scripts"
    assert Path(pointer["executable"]).is_relative_to(paths.root)
    assert launcher == paths.root / "launch/Iniciar.vbs"
    assert links.value == "new links"
    assert original.read_bytes() == b"original report"
    assert load(paths).scheduling_paused
    assert [j.label for j in load(paths).routines] == [
        "Clientes",
        "Eventos",
        "Procedimentos",
        "KWMS",
        "ATMS",
    ]
    assert verify_release(Path(pointer["release"]))["version"] == "2.0.0.dev99"


@pytest.mark.parametrize("fault", ["copy", "health", "migration", "activation", "post"])
def test_update_failure_restores_runtime_configuration_state_tasks_extras_and_links(
    native: tuple[Any, ...], fault: str
) -> None:
    installer, paths, config, payload, tasks, links = native
    installer.install(payload, config)
    before = read_json(installer.pointer)
    config.email = "anterior@example.invalid"
    save(paths, config)
    extra = paths.root / "extras/adicional.py"
    extra.write_text("print('preservado')")
    with Store(paths.database).connect() as db:
        db.execute("CREATE TABLE native_test(value TEXT)")
        db.execute("INSERT INTO native_test VALUES ('estado anterior')")
    tasks.value, links.value = "tarefa anterior", "atalhos anteriores"
    candidate = copy.deepcopy(config)
    candidate.email = "novo@example.invalid"
    with pytest.raises(RuntimeError, match="induzida"):
        installer.install(payload, candidate, fault=fault)
    assert read_json(installer.pointer) == before
    assert load(paths).email == "anterior@example.invalid"
    assert tasks.value == "tarefa anterior" and links.value == "atalhos anteriores"
    assert extra.read_text() == "print('preservado')"
    with Store(paths.database).connect() as db:
        assert db.execute("SELECT value FROM native_test").fetchone()[0] == "estado anterior"
    assert read_json(installer.journal)["status"] == "rolled_back"
    verify_release(Path(before["release"]))


def test_restart_recovers_interrupted_activation(native: tuple[Any, ...]) -> None:
    installer, paths, config, payload, _, _ = native
    installer.install(payload, config)
    before = read_json(installer.pointer)
    installer.install(payload, config)
    record = read_json(installer.journal)
    record["status"] = "activating"
    atomic_json(installer.journal, record)
    assert "revertida" in installer.recover()
    assert read_json(installer.pointer) == before
    assert installer.recover() == ""


@pytest.mark.parametrize("lock_name", ["execution.lock", "interface.lock", "maintenance.lock"])
def test_active_execution_interface_or_maintenance_prevents_update(
    native: tuple[Any, ...], lock_name: str
) -> None:
    installer, paths, config, payload, _, _ = native
    installer.install(payload, config)
    previous = read_json(installer.pointer)
    with Lock(paths.root / "state" / lock_name), pytest.raises(BusyError):
        installer.install(payload, config)
    assert read_json(installer.pointer) == previous


def test_nonempty_original_folder_is_rejected_before_any_write(
    native: tuple[Any, ...], tmp_path: Path
) -> None:
    _, _, _, payload, tasks, links = native
    original = Paths.user(tmp_path / "produção")
    original.root.mkdir()
    file = original.root / "original.py"
    file.write_bytes(b"original")
    installer = NativeInstaller(original, tasks=tasks, links=links, health=lambda _: None)
    with pytest.raises(ValueError, match="arquivos existentes"):
        installer.install(payload, prepare_config(original))
    assert [p.name for p in original.root.iterdir()] == ["original.py"]
    assert file.read_bytes() == b"original"


def test_backup_failure_blocks_activation(
    native: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, _, config, payload, _, links = native
    installer.install(payload, config)
    before = read_json(installer.pointer)

    def fail(_: Path) -> None:
        raise OSError("backup obrigatório indisponível")

    monkeypatch.setattr(links, "snapshot", fail)
    with pytest.raises(OSError, match="obrigatório"):
        installer.install(payload, config)
    assert read_json(installer.pointer) == before


def test_native_install_with_normalized_task_and_rollback_keeps_mismatch_evidence(
    native: tuple[Any, ...],
    normalized_task_xml: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from orquestrador_app.tasks import WindowsTasks

    installer, paths, config, payload, _, links = native
    backend = WindowsTasks(paths)
    current: list[str | None] = [None]
    fail_once = [False]
    monkeypatch.setattr(backend, "export", lambda: current[0])

    def register(value: str) -> None:
        current[0] = normalized_task_xml(value)
        if fail_once[0]:
            current[0] = current[0].replace("InteractiveToken", "S4U")
            fail_once[0] = False

    monkeypatch.setattr(backend, "register_xml", register)
    monkeypatch.setattr(backend, "_call", lambda *args, **kwargs: current.__setitem__(0, None))
    installer.tasks = backend
    config.install_schedules = True
    installer.install(payload, config)
    before, task_before, links_before = read_json(installer.pointer), current[0], links.value
    assert read_json(installer.journal)["status"] == "committed"
    previous_email = load(paths).email
    config.email = "new@example.invalid"
    fail_once[0] = True
    # An actual drift forces a re-registration, then the simulated policy changes logon type.
    current[0] = current[0].replace("PT60S", "PT2M")
    snapshot_task = current[0]
    with pytest.raises(RuntimeError, match="Principals/Principal/LogonType"):
        installer.install(payload, config)
    assert read_json(installer.pointer) == before and load(paths).email == previous_email
    assert current[0] == snapshot_task and links.value == links_before
    assert task_before != current[0]
    assert read_json(installer.journal)["status"] == "rolled_back"
    report = read_json(paths.root / "state/task-registration-check.json")
    assert not report["matches"] and "Principals/Principal/LogonType" in report["differences"]


def test_fresh_package_repairs_damaged_release_with_backup_of_damaged_files(
    native: tuple[Any, ...],
) -> None:
    installer, _, config, payload, _, _ = native
    installer.install(payload, config)
    old = Path(read_json(installer.pointer)["release"])
    (old / "src/desktop_entry.py").write_text("damaged previous installation")
    installer.install(payload, config)
    current = Path(read_json(installer.pointer)["release"])
    assert current != old
    verify_release(current)
    backup = Path(read_json(installer.pointer)["backup"])
    assert (backup / "release/src/desktop_entry.py").read_text() == "damaged previous installation"
    installer.verify_snapshot(backup)


def test_cancel_at_safe_checkpoint_restores_previous(native: tuple[Any, ...]) -> None:
    installer, _, config, payload, _, _ = native
    installer.install(payload, config)
    before = read_json(installer.pointer)
    requested = False

    def progress(message: str) -> None:
        nonlocal requested
        if "Registrando atalhos" in message:
            requested = True

    with pytest.raises(RuntimeError, match="cancelada"):
        installer.install(payload, config, progress=progress, cancelled=lambda: requested)
    assert read_json(installer.pointer) == before


@pytest.mark.parametrize("change", ["tampered", "extra", "version", "path"])
def test_manifest_corruption_and_path_traversal_are_rejected(
    native: tuple[Any, ...], change: str
) -> None:
    _, _, _, payload, _, _ = native
    if change == "tampered":
        (payload / "src/desktop_entry.py").write_bytes(b"changed")
    elif change == "extra":
        (payload / "undeclared.py").write_bytes(b"extra")
    else:
        record = read_json(payload / "release.json")
        if change == "version":
            record["version"] = "../../produção"
        else:
            record["files"]["../outside"] = "0" * 64
        atomic_json(payload / "release.json", record)
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_release(payload)


def test_preview_has_no_destination_side_effects_and_retains_test_configuration(
    native: tuple[Any, ...],
) -> None:
    installer, paths, config, payload, _, _ = native
    result = preview(paths.root)
    assert result["config"]["test_mode"]
    assert not paths.root.exists()
    installer.install(payload, config)
    assert preview(paths.root)["current"]["distribution"] == "native-scripts"


def test_new_wizard_seeds_days_but_existing_custom_calendar_is_unchanged(
    native: tuple[Any, ...],
) -> None:
    from orquestrador_app.config import from_dict, preset_days

    installer, paths, config, payload, _, _ = native
    config = from_dict(preview(paths.root)["config"])
    for routine in config.routines:
        assert routine.schedule.days == preset_days(
            routine.schedule.frequency, routine.schedule.weekday
        )
        if routine.schedule.frequency == "weekly":
            assert routine.expected_hours == len(routine.schedule.days) * 24
    assert not paths.root.exists()
    config.routines[0].schedule.days = [1, 3]
    config.scheduling_paused = True
    installer.install(payload, config)
    saved = from_dict(preview(paths.root)["config"])
    assert saved.routines[0].schedule.days == [1, 3]
    assert saved.scheduling_paused


def test_add_script_bridge_handles_spaces_accents_and_preserves_source(tmp_path: Path) -> None:
    from orquestrador_app.config import from_dict, to_dict
    from orquestrador_app.native_bridge import main

    script = tmp_path / "rotina diária.py"
    script.write_text("raise AssertionError('registration must not execute scripts')\n")
    original = digest(script)
    config = prepare_config(Paths.user(tmp_path / "instalação"))
    request, result, events = (
        tmp_path / name for name in ("request.json", "result.json", "events.jsonl")
    )

    def register() -> int:
        atomic_json(
            request,
            {
                "action": "add_script",
                "data_root": str(tmp_path / "instalação"),
                "script": str(script),
                "config": to_dict(config),
            },
        )
        return main(["--request", str(request), "--result", str(result), "--events", str(events)])

    assert register() == 0
    config = from_dict(read_json(result)["result"]["config"])
    added = config.routines[-1]
    assert added.id == "rotina_diaria" and added.label == "rotina diária"
    assert added.script == str(script) and not added.enabled and added.command == ""
    assert added.schedule.days == list(range(7))
    assert digest(script) == original
    assert register() == 2
    assert "já cadastrada" in read_json(result)["error"]


def package_zip(payload: Path, archive: Path) -> Path:
    with zipfile.ZipFile(archive, "w") as z:
        for path in payload.rglob("*"):
            if path.is_file():
                z.write(path, "Orquestrador/" + path.relative_to(payload.parent).as_posix())
    return archive


def test_local_zip_uses_verified_payload_without_executing_bootstrap(
    native: tuple[Any, ...], tmp_path: Path
) -> None:
    _, paths, _, payload, _, _ = native
    archive = package_zip(payload, tmp_path / "pacote.zip")
    root = prepare_zip(paths, archive, digest(archive))
    assert verify_release(root / "payload")["version"] == "2.0.0.dev99"


def test_zip_traversal_is_rejected_without_writing_outside(
    native: tuple[Any, ...], tmp_path: Path
) -> None:
    _, paths, _, _, _, _ = native
    archive = tmp_path / "ruim.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../../outside.py", "bad")
    with pytest.raises(ValueError, match="inseguro"):
        prepare_zip(paths, archive)
    assert not (paths.root / "outside.py").exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/feed",
        "https://user:secret@example.invalid/feed",
        "file:///config.json",
    ],
)
def test_feed_rejects_insecure_urls(url: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        https_host(url)


def test_feed_download_hash_version_and_local_staging(
    native: tuple[Any, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths, _, payload, _, _ = native
    archive = package_zip(payload, tmp_path / "pacote.zip")
    feed = {
        "owner": PACKAGE_OWNER,
        "version": "2.0.0.dev99",
        "package_url": "https://updates.example.invalid/app.zip",
        "sha256": digest(archive),
    }
    responses = [json.dumps(feed).encode(), archive.read_bytes()]
    observed = []

    class Response:
        status_code = 200

        def __enter__(self) -> Response:
            self.data = responses.pop(0)
            return self

        def __exit__(self, *_: Any) -> None:
            pass

        def raise_for_status(self) -> None:
            pass

        def iter_content(self, _: int) -> Any:
            yield self.data

    def get(url: str, **kwargs: Any) -> Response:
        observed.append((url, kwargs))
        return Response()

    monkeypatch.setattr("orquestrador_app.native_updates.requests.get", get)
    result = check_feed(paths, "https://updates.example.invalid/feed.json")
    assert result["available"] and result["version"] == "2.0.0.dev99"
    assert len(observed) == 2
    assert all(call[1]["allow_redirects"] is False for call in observed)
    responses.append(json.dumps(feed).encode())
    repeated = check_feed(paths, "https://updates.example.invalid/feed.json")
    assert repeated["package"] == result["package"]
    assert len(observed) == 3  # Only the feed is fetched again; no duplicate download/staging.


def test_native_task_uses_hidden_script_host_and_current_user(native: tuple[Any, ...]) -> None:
    import xml.etree.ElementTree as ET

    _, paths, _, _, _, _ = native
    executable = paths.root / "launch/Iniciar.vbs"
    tree = ET.fromstring(xml(executable, paths, "DOMAIN\\João"))
    command = tree.findtext(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Command")
    arguments = tree.findtext(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments")
    assert command and command.endswith("wscript.exe")
    assert arguments and "--agent" in arguments and "Iniciar.vbs" in arguments
    assert (
        tree.findtext(f"{{{NS}}}Principals/{{{NS}}}Principal/{{{NS}}}LogonType")
        == "InteractiveToken"
    )


@pytest.mark.parametrize(
    "report",
    [{"health": "ok", "version": "outro"}, {"health": "failed", "version": "2.0.0.dev3"}, {}],
)
def test_health_version_mismatch_prevents_activation(report: dict[str, Any]) -> None:
    with pytest.raises(RuntimeError, match="ativação recusada"):
        validate_health_report(report, "2.0.0.dev3")
    validate_health_report({"health": "ok", "version": "2.0.0.dev3"}, "2.0.0.dev3")


def test_recovery_report_identifies_partial_task_failure_and_restores_other_components(
    native: tuple[Any, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer, paths, config, payload, tasks, links = native
    installer.install(payload, config)
    tasks.value = "previous task"
    links.value = "previous links"
    folder = paths.root / "backups/app/report-fixture"
    installer.snapshot(folder)
    config.email = "changed@example.invalid"
    save(paths, config)
    links.value = "changed links"
    monkeypatch.setattr(
        tasks,
        "register_xml",
        lambda _: (_ for _ in ()).throw(PermissionError("scheduler fixture denied")),
    )
    with pytest.raises(RuntimeError, match="Recuperação parcial"):
        installer._restore(folder)
    report = read_json(paths.root / "state/recovery-report.json")
    components = {row["component"]: row for row in report["components"]}
    assert not report["complete"] and components["scheduled_task"]["intervention_required"]
    assert components["configuration"]["restored"] and components["shortcuts"]["restored"]
    assert load(paths).email != "changed@example.invalid" and links.value == "previous links"


class FakeRegistration:
    def __init__(self) -> None:
        self.value: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any] | None:
        return copy.deepcopy(self.value)

    def install(self, version: str) -> None:
        self.value = {"DisplayVersion": version}

    def remove(self) -> None:
        self.value = None

    def restore(self, value: dict[str, Any] | None) -> None:
        self.value = copy.deepcopy(value)


def public_payload(payload: Path) -> None:
    import shutil

    from orquestrador_app.uninstallation import PUBLIC_ENTRIES

    for name in (
        "Entrada.vbs",
        "Entrada.bat",
        "Entrada.ps1",
        "Desinstalar.ps1",
        "Native.Common.ps1",
    ):
        shutil.copy2(Path("native") / name, payload / "native" / name)
    record = read_json(payload / "release.json")
    record["public_entries"] = list(PUBLIC_ENTRIES)
    record["files"] = {
        p.relative_to(payload).as_posix(): digest(p)
        for p in payload.rglob("*")
        if p.is_file() and p.name != "release.json"
    }
    atomic_json(payload / "release.json", record)


def test_public_entries_and_registration_restore_after_update_rollback(
    native: tuple[Any, ...],
) -> None:
    installer, paths, config, payload, tasks, links = native
    public_payload(payload)
    registration = FakeRegistration()
    installer.registration = registration
    installer.install(payload, config)
    before = {p.name: p.read_bytes() for p in paths.root.glob("0[23]*")}
    pointer = read_json(installer.pointer)
    record = read_json(payload / "release.json")
    record["version"] = "2.0.0.dev100"
    atomic_json(payload / "release.json", record)
    with pytest.raises(RuntimeError, match="induzida"):
        installer.install(payload, load(paths), fault="activation")
    assert before == {p.name: p.read_bytes() for p in paths.root.glob("0[23]*")}
    assert read_json(installer.pointer) == pointer and registration.value == {
        "DisplayVersion": "2.0.0.dev99"
    }
    components = read_json(paths.root / "state/recovery-report.json")["components"]
    assert next(row for row in components if row["component"] == "windows_registration")["restored"]


def test_uninstaller_preserves_data_and_only_plans_verified_program_files(
    native: tuple[Any, ...],
) -> None:
    installer, paths, config, payload, tasks, links = native
    public_payload(payload)
    registration = FakeRegistration()
    installer.registration = registration
    installer.install(payload, config)
    saved_config = paths.config.read_bytes()
    report = paths.root / "relatorios/fixture.txt"
    report.parent.mkdir(exist_ok=True)
    report.write_text("user report")
    unrelated = paths.root / "app/versions/not-managed"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("external")
    result = installer.uninstall(remove_program_files=True)
    assert result["status"] == "uninstalled" and result["cleanup_pending"]
    assert not installer.pointer.exists() and registration.value is None and tasks.value is None
    assert paths.config.read_bytes() == saved_config and report.read_text() == "user report"
    assert (
        not (paths.root / "02 - Abrir CAIO.vbs").exists()
        and (paths.root / "03 - Desinstalar CAIO.vbs").exists()
    )
    plan = read_json(paths.root / "state/uninstall-cleanup.json")
    assert str(unrelated) in plan["preserved_unverified"]
    assert all(
        Path(row["path"]).is_relative_to(paths.root / "app/versions") for row in plan["releases"]
    )
    assert all(Path(row["path"]).exists() for row in plan["releases"]), (
        "Deletion waits for Windows host to exit"
    )
    assert Path(result["backup"]).is_dir() and paths.database.is_file()


def test_uninstaller_refuses_open_interface_before_any_mutation(native: tuple[Any, ...]) -> None:
    installer, paths, config, payload, tasks, links = native
    installer.install(payload, config)
    before = installer.pointer.read_bytes()
    with Lock(paths.root / "state/interface.lock"):
        with pytest.raises(BusyError):
            installer.uninstall()
    assert (
        installer.pointer.read_bytes() == before
        and not (paths.root / "state/uninstalled.json").exists()
    )


def test_failed_uninstall_restores_registration_task_links_and_public_entries(
    native: tuple[Any, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    installer, paths, config, payload, tasks, links = native
    public_payload(payload)
    registration = FakeRegistration()
    installer.registration = registration
    installer.install(payload, config)
    before = installer.pointer.read_bytes()
    tasks.value = "task before uninstall"

    def fail_remove() -> None:
        registration.value = None
        raise PermissionError("registry fixture denied")

    monkeypatch.setattr(registration, "remove", fail_remove)
    with pytest.raises(PermissionError, match="fixture"):
        installer.uninstall()
    assert installer.pointer.read_bytes() == before and tasks.value == "task before uninstall"
    assert registration.value == {"DisplayVersion": "2.0.0.dev99"}
    assert (paths.root / "02 - Abrir CAIO.vbs").exists() and not (
        paths.root / "state/uninstalled.json"
    ).exists()
