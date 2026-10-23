"""Three local UI catalogs. Configuration keys and user-authored script/log content stay unchanged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_language = "pt-BR"
_catalog: dict[str, list[str]] = {}


def set_language(language: str) -> None:
    global _language, _catalog
    _language = language if language in {"pt-BR", "en", "es"} else "pt-BR"
    if not _catalog:
        catalog = json.loads((Path(__file__).with_name("locales.json")).read_text(encoding="utf-8"))
        _catalog = {key.casefold(): values for key, values in catalog.items()}


def tr(text: str) -> str:
    if _language == "pt-BR" or not isinstance(text, str):
        return text
    values = _catalog.get(text.casefold())
    return values[0 if _language == "en" else 1] if values else text


def display_value(value: str) -> str:
    import datetime as dt

    codes = {
        "daily": "Diária",
        "weekly": "Semanal",
        "weekdays": "Somente dias úteis",
        "every_run": "Todos os horários",
        "same_chain": "Na mesma cadeia",
        "fresh_success": "Sucesso anterior válido",
        "running": "Em execução",
        "success": "Concluída",
        "failed": "Falhou",
        "skipped": "Ignorada; pendente",
        "cancelled": "Cancelada",
        "blocked_dependency": "Bloqueada por dependência",
        "not_eligible": "Não elegível",
        "ignored": "Desabilitada",
        "manual": "Manual",
        "scheduled": "Agendada",
        "extraction": "Extração",
        "local_publication": "Publicação local",
        "eligibility": "Elegibilidade",
        "driver": "Driver",
        "authentication": "Autenticação",
        "vpn": "VPN",
        "server": "Servidor",
        "internet": "Internet",
        "download": "Download",
        "invalid_file": "Arquivo inválido",
        "locked_file": "Arquivo bloqueado",
        "inconclusive": "Inconclusivo",
        "unknown": "Outros erros",
    }
    if value in codes:
        return tr(codes[value])
    if len(value) >= 19 and value[4:5] == "-" and value[10:11] == "T":
        try:
            date = dt.datetime.fromisoformat(value).astimezone()
            return date.strftime(
                "%m/%d/%Y %I:%M:%S %p" if _language == "en" else "%d/%m/%Y %H:%M:%S"
            )
        except ValueError:
            pass
    return tr(value)


def duration(seconds: float) -> str:
    text = f"{seconds:.1f}"
    return (text if _language == "en" else text.replace(".", ",")) + " s"


def translate_tree(root: Any) -> None:
    """Translate presentation properties only; never edit input, identifiers, paths or JSON."""
    from PySide6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QLabel,
        QLineEdit,
        QTableWidget,
        QTabWidget,
        QWidget,
    )

    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, (QLabel, QAbstractButton)):
            widget.setText(tr(widget.text()))
        if widget.toolTip():
            widget.setToolTip(tr(widget.toolTip()))
        if isinstance(widget, QLineEdit):
            widget.setPlaceholderText(tr(widget.placeholderText()))
        if isinstance(widget, QComboBox) and not widget.isEditable():
            widget.blockSignals(True)
            for i in range(widget.count()):
                widget.setItemText(i, tr(widget.itemText(i)))
            widget.blockSignals(False)
        if isinstance(widget, QTabWidget):
            for i in range(widget.count()):
                widget.setTabText(i, tr(widget.tabText(i)))
        if isinstance(widget, QTableWidget):
            for i in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(i)
                if item:
                    item.setText(tr(item.text()))
        if widget.isWindow():
            widget.setWindowTitle(tr(widget.windowTitle()))


def install_translation(app: Any, language: str) -> None:
    from PySide6.QtCore import QEvent, QObject

    set_language(language)
    if getattr(app, "_caio_translation", None):
        return

    class Translation(QObject):
        def eventFilter(self, obj: Any, event: Any) -> bool:
            if event.type() == QEvent.Type.Show and hasattr(obj, "isWindow") and obj.isWindow():
                translate_tree(obj)
            return False

    observer = Translation(app)
    app.installEventFilter(observer)
    app._caio_translation = observer
