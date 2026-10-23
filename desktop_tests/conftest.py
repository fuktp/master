from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, Callable

import pytest

from orquestrador_app.config import Config, Routine, save
from orquestrador_app.paths import Paths

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_: Any, **__: Any) -> Any:
        raise AssertionError("Rede bloqueada na suíte padrão.")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)


@pytest.fixture
def environment(tmp_path: Path) -> tuple[Paths, Config]:
    paths = Paths.user(tmp_path / "usuário diferente com acentuação")
    paths.ensure()
    config = Config(
        email="usuario@example.invalid",
        profile=str(paths.root / "profiles/Edge"),
        driver=str(paths.root / "cache/driver.exe"),
        downloads=str(paths.root / "downloads"),
        logs=str(paths.root / "logs"),
        install_root=str(paths.root / "installed"),
    )
    for index, name in enumerate(
        ("pipefy_clientes_tool_edge", "pipefy_eventos_tool_edge", "kwms_alocacoes_tool_edge")
    ):
        config.routines.append(Routine(id=name, label=name, script="not-used.py", order=index))
    save(paths, config)
    return paths, config


@pytest.fixture
def normalized_task_xml() -> Callable[[str], str]:
    """Synthetic XML variants allowed by the Windows schema; not captured from Windows."""
    import xml.etree.ElementTree as ET

    from orquestrador_app.tasks import NS

    def normalize(value: str) -> str:
        root = ET.fromstring(value)
        for parent in root.iter():
            for node in list(parent):
                if node.tag == f"{{{NS}}}Enabled" and node.text in {"true", "1"}:
                    parent.remove(node)
                elif node.text == "false":
                    node.text = "0"
        command = root.find(f"{{{NS}}}Actions/{{{NS}}}Exec/{{{NS}}}Command")
        assert command is not None and command.text
        command.text = '"' + command.text.strip('"').replace("/", "\\").upper() + '"'
        interval = root.find(
            f"{{{NS}}}Triggers/{{{NS}}}CalendarTrigger/{{{NS}}}Repetition/{{{NS}}}Interval"
        )
        duration = root.find(
            f"{{{NS}}}Triggers/{{{NS}}}CalendarTrigger/{{{NS}}}Repetition/{{{NS}}}Duration"
        )
        assert interval is not None and duration is not None
        if interval.text == "PT1M":
            interval.text = "PT60S"
        if duration.text == "P1D":
            duration.text = "PT24H"
        return ET.tostring(root, encoding="unicode")

    return normalize
