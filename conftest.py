"""The default suite cannot access corporate or public network services."""
from __future__ import annotations

import socket
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def offline_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_: Any, **__: Any) -> Any:
        raise AssertionError("Rede externa bloqueada na suíte padrão.")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
