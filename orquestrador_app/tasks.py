from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import ntpath
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path
from typing import Any

from .io import atomic_json
from .paths import Paths

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
ET.register_namespace("", NS)


def current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    return (domain + "\\" if domain else "") + getpass.getuser()


def task_name(paths: Paths) -> str:
    key = hashlib.sha256(str(paths.root.resolve()).encode()).hexdigest()[:12]
    if (paths.root / "instalacao-teste.json").is_file():
        return rf"\Orquestrador-Teste-{key}"
    return rf"\Orquestrador-{key}"


def xml(executable: Path, paths: Paths, user: str) -> str:
    root = ET.Element(f"{{{NS}}}Task", version="1.2")

    def element(parent: ET.Element, name: str, text: str | None = None, **attrs: str) -> ET.Element:
        node = ET.SubElement(parent, f"{{{NS}}}{name}", attrs)
        node.text = text
        return node

    registration = element(root, "RegistrationInfo")
    element(registration, "Author", "Orquestrador")
    element(registration, "URI", task_name(paths))
    element(
        registration,
        "Description",
        "Monitor do Orquestrador; horários próprios e notificações na sessão do usuário.",
    )
    triggers = element(root, "Triggers")
    logon = element(triggers, "LogonTrigger")
    element(logon, "Enabled", "true")
    element(logon, "UserId", user)
    calendar = element(triggers, "CalendarTrigger")
    repetition = element(calendar, "Repetition")
    element(repetition, "Interval", "PT1M")
    element(repetition, "Duration", "P1D")
    element(repetition, "StopAtDurationEnd", "false")
    element(calendar, "StartBoundary", "2026-01-01T00:00:00")
    element(calendar, "Enabled", "true")
    days = element(calendar, "ScheduleByDay")
    element(days, "DaysInterval", "1")
    principals = element(root, "Principals")
    principal = element(principals, "Principal", id="Author")
    element(principal, "UserId", user)
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")
    settings = element(root, "Settings")
    for key, value in {
        "MultipleInstancesPolicy": "IgnoreNew",
        "DisallowStartIfOnBatteries": "false",
        "StopIfGoingOnBatteries": "false",
        "StartWhenAvailable": "true",
        "RunOnlyIfNetworkAvailable": "false",
        "Enabled": "true",
        "ExecutionTimeLimit": "PT0S",
        "Priority": "7",
    }.items():
        element(settings, key, value)
    actions = element(root, "Actions", Context="Author")
    action = element(actions, "Exec")
    native = executable.suffix.casefold() == ".vbs"
    native_host = str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/wscript.exe")
    element(action, "Command", native_host if native else str(executable))
    element(
        action,
        "Arguments",
        subprocess.list2cmdline(
            ["//B", "//Nologo", str(executable), "--agent"]
            if native
            else ["--data-root", str(paths.root), "--agent"]
        ),
    )
    element(action, "WorkingDirectory", str(executable.parent))
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + ET.tostring(root, encoding="unicode")


# Windows schema defaults and the principal's default least-privilege level.
TASK_FIELDS = {
    "RegistrationInfo/URI": "",
    "Actions/Exec/Command": "",
    "Actions/Exec/Arguments": "",
    "Actions/Exec/WorkingDirectory": "",
    "Principals/Principal/LogonType": "",
    "Principals/Principal/RunLevel": "LeastPrivilege",
    "Triggers/CalendarTrigger/Repetition/Interval": "",
    "Triggers/CalendarTrigger/Repetition/Duration": "",
    "Triggers/CalendarTrigger/Repetition/StopAtDurationEnd": "false",
    "Triggers/CalendarTrigger/StartBoundary": "",
    "Triggers/CalendarTrigger/ScheduleByDay/DaysInterval": "",
    "Triggers/CalendarTrigger/Enabled": "true",
    "Triggers/LogonTrigger/Enabled": "true",
    "Settings/Enabled": "true",
    "Settings/MultipleInstancesPolicy": "IgnoreNew",
    "Settings/ExecutionTimeLimit": "PT72H",
    "Settings/DisallowStartIfOnBatteries": "true",
    "Settings/StopIfGoingOnBatteries": "true",
    "Settings/StartWhenAvailable": "false",
    "Settings/RunOnlyIfNetworkAvailable": "false",
}


def task_path(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return ntpath.normcase(ntpath.normpath(ntpath.expandvars(value))) if value else ""


def task_value(field: str, value: str) -> Any:
    if field.endswith(("/Command", "/WorkingDirectory", "/URI")):
        return task_path(value)
    if field.endswith(
        (
            "/Enabled",
            "/StopAtDurationEnd",
            "/DisallowStartIfOnBatteries",
            "/StopIfGoingOnBatteries",
            "/StartWhenAvailable",
            "/RunOnlyIfNetworkAvailable",
        )
    ):
        return {"true": True, "1": True, "false": False, "0": False}.get(value, value)
    if field.endswith(("/Interval", "/Duration", "/ExecutionTimeLimit")):
        match = re.fullmatch(
            r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", value
        )
        if match and any(part is not None for part in match.groups()):
            return sum(
                Decimal(part or "0") * unit
                for part, unit in zip(match.groups(), (86400, 3600, 60, 1))
            )
    if field.endswith("/DaysInterval") and value.isdecimal():
        return int(value)
    if field.endswith("/StartBoundary") and value:
        try:
            when = dt.datetime.fromisoformat(value)
            if when.tzinfo:
                when = when.astimezone().replace(tzinfo=None)
            return when
        except ValueError:
            pass
    return value


def compare_tasks(actual: str | None, expected: str) -> dict[str, Any]:
    trees = [ET.fromstring(value) if value else None for value in (actual, expected)]
    checks = []
    for field, default in TASK_FIELDS.items():
        path = "/".join("{" + NS + "}" + part for part in field.split("/"))
        raw = [tree.findtext(path) if tree is not None else None for tree in trees]
        effective = [value.strip() if value is not None else default for value in raw]
        checks.append(
            {
                "field": field,
                "actual": raw[0],
                "expected": raw[1],
                "effective_actual": effective[0],
                "effective_expected": effective[1],
                "matches": bool(actual)
                and task_value(field, effective[0]) == task_value(field, effective[1]),
            }
        )
    # Extra actions/triggers cannot hide behind matching first children.
    for field in ("Actions", "Triggers", "Principals"):
        nodes = [tree.find("{" + NS + "}" + field) if tree is not None else None for tree in trees]
        counts = [len(node) if node is not None else 0 for node in nodes]
        checks.append(
            {
                "field": field + "/count",
                "actual": counts[0],
                "expected": counts[1],
                "effective_actual": counts[0],
                "effective_expected": counts[1],
                "matches": bool(actual) and counts[0] == counts[1],
            }
        )
    differences = [check["field"] for check in checks if not check["matches"]]
    return {
        "installed": bool(actual),
        "matches": bool(actual) and not differences,
        "differences": differences,
        "checks": checks,
        "actual": actual,
        "expected": expected,
    }


class WindowsTasks:
    def __init__(self, paths: Paths):
        self.paths = paths

    def _call(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        if os.name != "nt":
            raise RuntimeError("Agendador real disponível somente no Windows.")
        result = subprocess.run(
            ["schtasks.exe", *arguments],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            creationflags=0x08000000,
        )
        if check and result.returncode:
            raise RuntimeError("Falha no Agendador do Windows: " + result.stdout + result.stderr)
        return result

    def export(self, name: str | None = None) -> str | None:
        if os.name != "nt":
            raise RuntimeError("Agendador real disponível somente no Windows.")
        import pythoncom
        import pywintypes
        import win32com.client

        pythoncom.CoInitialize()
        try:
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()
            folder = service.GetFolder("\\")
            try:
                task = folder.GetTask(name or task_name(self.paths))
            except pywintypes.com_error as exc:
                code = exc.hresult & 0xFFFFFFFF
                # IDispatch can wrap the actual Scheduler HRESULT in EXCEPINFO.scode.
                if code == 0x80020009 and exc.excepinfo and isinstance(exc.excepinfo[5], int):
                    code = exc.excepinfo[5] & 0xFFFFFFFF
                if code == 0x80070002:
                    return None
                raise RuntimeError(
                    "Não foi possível consultar a tarefa do Windows: " + str(exc)
                ) from exc
            return str(task.Xml)
        finally:
            pythoncom.CoUninitialize()

    def owned(self, value: str) -> bool:
        root = ET.fromstring(value)
        return task_path(root.findtext(f"{{{NS}}}RegistrationInfo/{{{NS}}}URI") or "") == task_path(
            task_name(self.paths)
        )

    def register_xml(self, value: str, name: str | None = None) -> None:
        if name is None and not self.owned(value):
            raise ValueError("XML não pertence a este produto/instalação.")
        if os.name != "nt":
            raise RuntimeError("Agendador real disponível somente no Windows.")
        if name is not None:
            # Preserve the legacy named-task restore contract.
            path = self.paths.root / "cache/task.xml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-16")
            try:
                self._call("/Create", "/TN", name, "/XML", str(path), "/F")
            finally:
                path.unlink(missing_ok=True)
            return
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()
            definition = service.NewTask(0)
            definition.XmlText = value
            # Use the XML principal's explicit logon type: InteractiveToken=3 for our monitor.
            service.GetFolder("\\").RegisterTaskDefinition(
                task_name(self.paths),
                definition,
                6,
                None,
                None,
                int(definition.Principal.LogonType),
            )
        finally:
            pythoncom.CoUninitialize()

    def install(self, executable: Path, user: str) -> dict[str, Any]:
        current = self.export()
        if current and not self.owned(current):
            raise ValueError("Nome de tarefa em conflito; tarefa externa preservada.")
        value = xml(executable, self.paths, user)
        if not compare_tasks(current, value)["matches"]:
            self.register_xml(value)
        result = self.differences(executable, user)
        diagnostic = self.paths.root / "state/task-registration-check.json"
        atomic_json(
            diagnostic,
            {
                "task": task_name(self.paths),
                "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                **result,
            },
        )
        if not result["matches"]:
            detail = "; ".join(
                f"{check['field']}: recebido={check['actual']!r}, esperado={check['expected']!r}"
                for check in [check for check in result["checks"] if not check["matches"]][:6]
            )
            raise RuntimeError(
                "A tarefa não corresponde à configuração após o registro. "
                + detail
                + " Diagnóstico local: "
                + str(diagnostic)
            )
        return {"action": "installed", "task": task_name(self.paths), **result}

    def preflight(self, user: str) -> dict[str, Any]:
        """Create/query/delete a disabled, randomly named probe; never execute it."""
        if os.name != "nt":
            raise RuntimeError("A pré-verificação do Agendador exige Windows.")
        import uuid

        import pythoncom
        import win32com.client

        name = r"\CAIO-Probe-" + str(uuid.uuid4())
        root = ET.fromstring(xml(Path(os.environ["WINDIR"]) / "System32/cmd.exe", self.paths, user))
        root.find(f"{{{NS}}}RegistrationInfo/{{{NS}}}URI").text = name  # type: ignore[union-attr]
        root.find(f"{{{NS}}}RegistrationInfo/{{{NS}}}Author").text = "CAIO-Probe"  # type: ignore[union-attr]
        root.find(f"{{{NS}}}Settings/{{{NS}}}Enabled").text = "false"  # type: ignore[union-attr]
        root.find(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments").text = "/c exit 0"  # type: ignore[union-attr]
        triggers = root.find(f"{{{NS}}}Triggers")
        assert triggers is not None
        triggers.clear()
        expected = ET.tostring(root, encoding="unicode")
        created = False
        result: dict[str, Any] = {
            "task": name,
            "registered": False,
            "queried": False,
            "removed": False,
            "executed": False,
        }
        pythoncom.CoInitialize()
        try:
            service = win32com.client.Dispatch("Schedule.Service")
            service.Connect()
            folder = service.GetFolder("\\")
            definition = service.NewTask(0)
            definition.XmlText = expected
            folder.RegisterTaskDefinition(
                name, definition, 2, None, None, 3
            )  # TASK_CREATE: never overwrite.
            created = True
            result["registered"] = True
            actual = folder.GetTask(name).Xml
            result["queried"] = compare_tasks(actual, expected)["matches"]
            if not result["queried"]:
                raise RuntimeError("A tarefa temporária divergiu após registro.")
        finally:
            try:
                if created:
                    actual = ET.fromstring(folder.GetTask(name).Xml)
                    if (
                        actual.findtext(f"{{{NS}}}RegistrationInfo/{{{NS}}}URI") != name
                        or actual.findtext(f"{{{NS}}}RegistrationInfo/{{{NS}}}Author")
                        != "CAIO-Probe"
                    ):
                        raise RuntimeError(
                            "A tarefa temporária mudou de proprietário; remoção recusada: " + name
                        )
                    folder.DeleteTask(name, 0)
                    result["removed"] = self.export(name) is None
                    if not result["removed"]:
                        raise RuntimeError("A tarefa temporária não foi removida: " + name)
            finally:
                pythoncom.CoUninitialize()
                atomic_json(self.paths.root / "state/scheduler-preflight.json", result)
        return result

    def remove(self) -> dict[str, Any]:
        current = self.export()
        if current:
            if not self.owned(current):
                raise ValueError("Recusa de remover tarefa externa.")
            self._call("/Delete", "/TN", task_name(self.paths), "/F")
        if self.export():
            raise RuntimeError("A tarefa ainda existe após a remoção.")
        return {
            "action": "removed" if current else "already_absent",
            "task": task_name(self.paths),
            "installed": False,
        }

    def start(self) -> None:
        self._call("/Run", "/TN", task_name(self.paths))

    def legacy(self, config_path: str) -> dict[str, str]:
        if not config_path:
            return {}
        if os.name != "nt":
            raise RuntimeError("Inventário de tarefas legadas requer Windows.")
        import win32com.client

        service = win32com.client.Dispatch("Schedule.Service")
        service.Connect()
        folder = service.GetFolder("\\")
        matches = {}
        for task in folder.GetTasks(1):
            value = str(task.Xml)
            tree = ET.fromstring(value)
            arguments = tree.findtext(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Arguments") or ""
            if (
                str(task.Name).startswith("Pipefy_Orquestrador-")
                and config_path.casefold() in arguments.casefold()
                and "pipefy_orchestrator.py" in arguments.casefold()
            ):
                matches[str(task.Path)] = value
        return matches

    def disable_legacy(self, name: str, original: str) -> None:
        if (
            not name.startswith("\\Pipefy_Orquestrador-")
            or "pipefy_orchestrator.py" not in original
        ):
            raise ValueError("Tarefa não reconhecida como legado revisado.")
        self._call("/Change", "/TN", name, "/Disable")

    def differences(self, executable: Path, user: str) -> dict[str, Any]:
        return compare_tasks(self.export(), xml(executable, self.paths, user))
