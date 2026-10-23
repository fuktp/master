from __future__ import annotations

import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

import pytest

from orquestrador_app.io import read_json
from orquestrador_app.paths import Paths
from orquestrador_app.tasks import NS, WindowsTasks, compare_tasks, xml


def test_registration_accepts_equivalent_xml_and_does_not_register_it_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, normalized_task_xml: Callable[[str], str]
) -> None:
    backend = WindowsTasks(Paths.user(tmp_path))
    current: list[str | None] = [None]
    calls: list[str] = []
    monkeypatch.setattr(backend, "export", lambda: current[0])

    def register(value: str) -> None:
        calls.append(value)
        current[0] = normalized_task_xml(value)

    monkeypatch.setattr(backend, "register_xml", register)
    launcher = tmp_path / "pasta com acentos ç/Iniciar.vbs"
    assert backend.install(launcher, "DOMAIN\\fixture")["matches"]
    assert backend.install(launcher, "DOMAIN\\fixture")["matches"]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,changed",
    [
        ("RegistrationInfo/URI", r"\TarefaExterna"),
        ("Actions/Exec/Command", "outro.exe"),
        ("Actions/Exec/Arguments", "--opcao-incorreta"),
        ("Actions/Exec/WorkingDirectory", r"C:\Outra pasta"),
        ("Principals/Principal/LogonType", "S4U"),
        ("Principals/Principal/RunLevel", "HighestAvailable"),
        ("Triggers/CalendarTrigger/Repetition/Interval", "PT2M"),
        ("Triggers/CalendarTrigger/Repetition/Duration", "PT12H"),
        ("Triggers/CalendarTrigger/Repetition/StopAtDurationEnd", "true"),
        ("Triggers/CalendarTrigger/StartBoundary", "2099-01-01T00:00:00"),
        ("Triggers/CalendarTrigger/ScheduleByDay/DaysInterval", "2"),
        ("Triggers/CalendarTrigger/Enabled", "false"),
        ("Triggers/LogonTrigger/Enabled", "false"),
        ("Settings/Enabled", "false"),
        ("Settings/ExecutionTimeLimit", "PT72H"),
        ("Settings/ExecutionTimeLimit", None),
        ("Settings/MultipleInstancesPolicy", "Parallel"),
        ("Settings/DisallowStartIfOnBatteries", "true"),
        ("Settings/StopIfGoingOnBatteries", "true"),
        ("Settings/StartWhenAvailable", "false"),
    ],
)
def test_real_task_difference_is_not_hidden(
    tmp_path: Path, field: str, changed: str | None
) -> None:
    expected = xml(tmp_path / "Iniciar.vbs", Paths.user(tmp_path), "DOMAIN\\fixture")
    root = ET.fromstring(expected)
    path = "/".join("{" + NS + "}" + part for part in field.split("/"))
    node = root.find(path)
    assert node is not None
    if changed is None:
        parent_path = "/".join("{" + NS + "}" + part for part in field.split("/")[:-1])
        parent = root.find(parent_path)
        assert parent is not None
        parent.remove(node)
    else:
        node.text = changed
    report = compare_tasks(ET.tostring(root, encoding="unicode"), expected)
    assert not report["matches"] and field in report["differences"]


@pytest.mark.parametrize("field", ["Actions", "Triggers", "Principals"])
def test_extra_action_trigger_or_principal_is_rejected(tmp_path: Path, field: str) -> None:
    expected = xml(tmp_path / "Iniciar.vbs", Paths.user(tmp_path), "fixture")
    root = ET.fromstring(expected)
    node = root.find("{" + NS + "}" + field)
    assert node is not None
    node.append(ET.fromstring(ET.tostring(node[0])))
    report = compare_tasks(ET.tostring(root, encoding="unicode"), expected)
    assert not report["matches"] and field + "/count" in report["differences"]


def test_schema_default_is_not_copied_from_expected(tmp_path: Path) -> None:
    expected = xml(tmp_path / "Iniciar.vbs", Paths.user(tmp_path), "fixture")
    root = ET.fromstring(expected)
    for parent in root.iter():
        for child in list(parent):
            if child.tag in {f"{{{NS}}}RunLevel", f"{{{NS}}}MultipleInstancesPolicy"}:
                parent.remove(child)
    assert compare_tasks(ET.tostring(root, encoding="unicode"), expected)["matches"]


def test_mismatch_keeps_field_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = WindowsTasks(Paths.user(tmp_path))
    current: list[str | None] = [None]
    monkeypatch.setattr(backend, "export", lambda: current[0])
    monkeypatch.setattr(
        backend,
        "register_xml",
        lambda value: current.__setitem__(0, value.replace("InteractiveToken", "S4U")),
    )
    with pytest.raises(RuntimeError, match="Principals/Principal/LogonType") as error:
        backend.install(tmp_path / "Iniciar.vbs", "fixture")
    assert "S4U" in str(error.value) and "InteractiveToken" in str(error.value)
    report = read_json(tmp_path / "state/task-registration-check.json")
    assert report["installed"] and not report["matches"]
    assert "Principals/Principal/LogonType" in report["differences"]


@pytest.mark.parametrize("denied", [False, True])
def test_registration_uses_com_explicit_interactive_session_and_releases_com(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, denied: bool
) -> None:
    import orquestrador_app.tasks as tasks

    calls: list[tuple[Any, ...]] = []
    lifecycle: list[str] = []
    definition = SimpleNamespace(XmlText="", Principal=SimpleNamespace(LogonType=3))

    def register(*args: Any) -> None:
        calls.append(args)
        if denied:
            raise PermissionError("fixture: registro negado")

    service = SimpleNamespace(
        Connect=lambda: None,
        NewTask=lambda _: definition,
        GetFolder=lambda _: SimpleNamespace(RegisterTaskDefinition=register),
    )
    client = SimpleNamespace(Dispatch=lambda _: service)
    package = ModuleType("win32com")
    package.client = client
    monkeypatch.setitem(sys.modules, "win32com", package)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        SimpleNamespace(
            CoInitialize=lambda: lifecycle.append("init"),
            CoUninitialize=lambda: lifecycle.append("uninit"),
        ),
    )
    backend = WindowsTasks(Paths.user(tmp_path))
    value = xml(tmp_path / "Iniciar.vbs", backend.paths, "fixture")
    monkeypatch.setattr(tasks, "os", SimpleNamespace(name="nt"))
    if denied:
        with pytest.raises(PermissionError):
            backend.register_xml(value)
    else:
        backend.register_xml(value)
    assert lifecycle == ["init", "uninit"]
    assert definition.XmlText == value and len(calls) == 1
    assert calls[0][1] is definition and calls[0][2:] == (6, None, None, 3)


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("CAIO_TEST_WINDOWS_SCHEDULER") != "1",
    reason="Agendador Windows real exige Windows e opt-in CAIO_TEST_WINDOWS_SCHEDULER=1.",
)
def test_real_windows_scheduler_register_read_run_and_remove(tmp_path: Path) -> None:
    from orquestrador_app.tasks import current_user

    paths = Paths.user(tmp_path / "teste isolado ç")
    paths.ensure()
    (paths.root / "instalacao-teste.json").write_text("{}")
    marker = paths.root / "resultado agendador.txt"
    launcher = paths.root / "Iniciar.vbs"
    launcher.write_text(
        'Set fs = CreateObject("Scripting.FileSystemObject")\n'
        + 'Set output = fs.CreateTextFile("'
        + str(marker)
        + '", True, True)\n'
        + 'output.WriteLine "OK"\noutput.Close\n',
        encoding="utf-16",
    )
    backend = WindowsTasks(paths)
    try:
        assert backend.export() is None
        assert backend.install(launcher, current_user())["matches"]
        assert backend.differences(launcher, current_user())["matches"]
        assert backend.install(launcher, current_user())["matches"]
        backend.start()
        deadline = time.monotonic() + 20
        content = ""
        while time.monotonic() < deadline:
            try:
                content = marker.read_text(encoding="utf-16").strip()
            except (OSError, UnicodeError):
                pass
            if content == "OK":
                break
            time.sleep(0.1)
        assert content == "OK"
    finally:
        backend.remove()
    assert backend.export() is None
