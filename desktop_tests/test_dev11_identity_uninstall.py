from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pefile
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from desktop_tests.ui_helpers import settle
from orquestrador_app.config import save
from orquestrador_app.gui import MainWindow
from orquestrador_app.io import atomic_json, digest
from orquestrador_app.observation import LogTail
from orquestrador_app.paths import Paths
from orquestrador_app.processes import command, spawn
from orquestrador_app.runtime import decode_log_bytes
from orquestrador_app.sandbox import prepare_config
from orquestrador_app.uninstall_gui import UninstallDialog
from orquestrador_app.uninstallation import (
    PUBLIC_ENTRIES,
    WindowsRegistration,
    install_entries,
    render_entries,
    restore_entries,
    stop_monitor,
)
from orquestrador_app.windows_hosts import HOST_DESCRIPTIONS, ROUTINE_HOSTS, executable, host_for
from tools.brand_windows_hosts import brand


@pytest.mark.parametrize("name,description", list(HOST_DESCRIPTIONS.items()))
def test_windows_hosts_have_real_image_identity_icon_and_original_interpreter_code(
    tmp_path: Path, name: str, description: str
) -> None:
    original = Path(__file__).parent / "fixtures/pythonw-original.exe"
    checksum = digest(original)
    target = tmp_path / name
    brand(
        original,
        target,
        name=name,
        description=description,
        version="2.0.0.dev11",
        icon=Path("assets/caio.ico"),
    )
    pe = pefile.PE(str(target))
    before = pefile.PE(str(original))
    strings = next(
        table.entries
        for group in pe.FileInfo
        for item in group
        if hasattr(item, "StringTable")
        for table in item.StringTable
    )
    assert strings[b"FileDescription"].decode() == description
    assert strings[b"OriginalFilename"].decode() == name
    assert strings[b"ProductVersion"] == b"2.0.0.dev11"
    assert pe.OPTIONAL_HEADER.Subsystem == 2 and pe.FILE_HEADER.Machine == 0x8664
    assert pe.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size == 0 and pe.verify_checksum()
    for old in before.sections:
        if old.Name.rstrip(b"\0") != b".rsrc":
            assert old.get_data() == next(
                section.get_data() for section in pe.sections if section.Name == old.Name
            )
    assert pe.OPTIONAL_HEADER.AddressOfEntryPoint == before.OPTIONAL_HEADER.AddressOfEntryPoint
    kinds = {entry.id for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
    assert {3, 14, 16, 24} <= kinds
    assert digest(original) == checksum
    pe.close()
    before.close()


def test_worker_routes_to_matching_branded_image_only_in_packaged_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from orquestrador_app import processes, resources

    root = tmp_path / "release"
    (root / "runtime").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "release.json").write_text("{}")
    for name in HOST_DESCRIPTIONS:
        (root / "runtime" / name).write_bytes(b"fixture")
    monkeypatch.setattr(processes.sys, "platform", "win32")
    monkeypatch.setattr(resources, "source_root", lambda: root / "src")
    for job, name in ROUTINE_HOSTS.items():
        assert Path(command("--worker", job)[0]).name == name
    assert Path(command("--agent")[0]).name == "CAIO-Monitor.exe"
    assert Path(command("--uninstall")[0]).name == "CAIO-Desinstalador.exe"
    assert Path(command()[0]).name == "CAIO-Orquestrador.exe"
    assert host_for(("--worker", "custom")) == "CAIO-Rotina.exe"
    assert executable(tmp_path / "old").name == "pythonw.exe"


def test_root_entries_dispatch_explicit_action_and_preserve_external_files(tmp_path: Path) -> None:
    paths = Paths.user(tmp_path)
    native = Path("native")
    values = render_entries(native)
    assert set(values) == set(PUBLIC_ENTRIES)
    assert all(b"__ACTION__" not in value for value in values.values())
    for name, action in PUBLIC_ENTRIES.items():
        assert action.encode() in values[name]
    foreign = paths.root / "02 - Abrir CAIO.vbs"
    foreign.write_text("external file")
    with pytest.raises(ValueError, match="externo"):
        install_entries(paths, native)
    assert foreign.read_text() == "external file"
    foreign.unlink()
    install_entries(paths, native)
    restore_entries(paths, tmp_path / "old-snapshot")
    assert not any((paths.root / name).exists() for name in values)


def test_utf8_output_is_correct_even_with_legacy_environment_and_reconfigured_stream(
    tmp_path: Path,
) -> None:
    file = tmp_path / "accented.log"
    script = "from pathlib import Path; import sys; from orquestrador_app.runtime import capture_windowed_streams; sys.stdout.reconfigure(encoding='cp1252'); capture_windowed_streams(Path(sys.argv[1])); print('ação, café, início, São Paulo, €')"
    environment = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"}
    with file.open("wb") as output:
        child = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path)],
            env=environment,
            stdout=output,
            stderr=subprocess.PIPE,
            check=True,
        )
    assert file.read_text(encoding="utf8").strip() == "ação, café, início, São Paulo, €"
    assert child.returncode == 0
    second = tmp_path / "spawn.log"
    with second.open("wb") as output:
        process = spawn([sys.executable, "-c", "print('ã é í ç')"], env=environment, stdout=output)
        assert process.wait(timeout=10) == 0
    assert second.read_text(encoding="utf8").strip() == "ã é í ç"


def test_log_tail_reads_legacy_ansi_and_utf8_across_chunk_boundaries(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.log"
    legacy.write_bytes("Extração concluída: ação, café, início.\n".encode("cp1252"))
    before = legacy.read_bytes()
    assert "Extração concluída" in LogTail().read(legacy)["text"]
    assert decode_log_bytes(before).startswith("Extração") and legacy.read_bytes() == before
    text = "ç" * 40000 + "\n"
    current = tmp_path / "utf8.log"
    current.write_bytes(text.encode("utf8"))
    result = LogTail().read(current)["text"]
    assert "�" not in result and "Ã" not in result and result.endswith("\n")


def test_test_installation_footer_stays_one_line_with_full_path_in_tooltip(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path / ("pasta longa com acentuação " * 7))
    paths.ensure()
    save(paths, prepare_config(paths))
    window = MainWindow(paths)
    settle(window)
    window.timer.stop()
    window.dev_panel.timer.stop()
    window.resize(980, 720)
    window.show()
    app.processEvents()
    try:
        label = window.installation_banner
        assert not label.wordWrap()
        assert label.height() <= label.fontMetrics().height() + 6
        assert window.statusBar().height() <= label.height() + 6
        assert str(paths.root) in label.toolTip() and str(paths.root) in label.accessibleName()
        assert window.width() == 980 and "\n" not in label.text()
    finally:
        window.exit_requested = True
        window.close()
        settle(window)


def test_uninstall_confirmation_is_cancellable_and_does_not_modify_installation(
    tmp_path: Path,
) -> None:
    QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    paths.ensure()
    save(paths, prepare_config(paths))
    before = paths.config.read_bytes()
    dialog = UninstallDialog(paths)
    dialog.show()
    QApplication.processEvents()
    assert dialog.cancel.isDefault() and dialog.remove_files.isChecked()
    dialog.cancel.click()
    assert dialog.result() == QDialog.DialogCode.Rejected and before == paths.config.read_bytes()


def test_owned_monitor_stop_refuses_an_unrelated_process(tmp_path: Path) -> None:
    import psutil

    paths = Paths.user(tmp_path)
    paths.ensure()
    process = psutil.Process()
    atomic_json(
        paths.root / "state/monitor-heartbeat.json",
        {"pid": process.pid, "created": process.create_time()},
    )
    with pytest.raises(ValueError, match="identidade|próprio"):
        stop_monitor(paths)
    assert process.is_running()


def test_registration_uses_per_installation_owner_and_blocks_external_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import orquestrador_app.uninstallation as module

    values: dict[str, Any] = {}

    class Key:
        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def open_key(*args: Any) -> Key:
        if not values:
            raise FileNotFoundError()
        return Key()

    api = SimpleNamespace(
        HKEY_CURRENT_USER=1,
        KEY_WRITE=2,
        REG_DWORD=4,
        REG_SZ=1,
        OpenKey=open_key,
        QueryInfoKey=lambda _: (0, len(values), 0),
        EnumValue=lambda _, i: (list(values)[i], list(values.values())[i], 1),
        CreateKeyEx=lambda *args: Key(),
        SetValueEx=lambda _, name, reserved, kind, value: values.__setitem__(name, value),
        DeleteKey=lambda *args: values.clear(),
    )
    monkeypatch.setitem(sys.modules, "winreg", api)
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt", environ={"WINDIR": r"C:\Windows"}))
    paths = Paths.user(tmp_path)
    registry = WindowsRegistration(paths)
    registry.install("2.0.0.dev11")
    assert "03 - Desinstalar CAIO.vbs" in values["UninstallString"]
    assert values["DisplayVersion"] == "2.0.0.dev11" and values["InstallLocation"] == str(
        paths.root
    )
    saved = registry.snapshot()
    registry.remove()
    assert not values
    registry.restore(saved)
    assert values
    values["InstallLocation"] = str(tmp_path / "external")
    with pytest.raises(ValueError, match="outra instalação"):
        registry.remove()
    assert values
