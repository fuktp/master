"""Three local UI catalogs. Configuration keys and user-authored script/log content stay unchanged."""

from __future__ import annotations

import json
import re
from functools import lru_cache
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
    _translate.cache_clear()


def tr(text: str) -> str:
    if _language == "pt-BR" or not isinstance(text, str):
        return text
    return _translate(_language, text)


@lru_cache(maxsize=1)
def _templates() -> list[tuple[re.Pattern[str], list[str]]]:
    result = []
    for source, translations in _catalog.items():
        if not re.search(r"\{\d+\}", source):
            continue
        pieces = re.split(r"(\{\d+\})", source)
        value_pattern = ".*?" if "\n" in source else r"[^\r\n]*?"
        pattern = "".join(
            f"(?P<v{piece[1:-1]}>{value_pattern})"
            if re.fullmatch(r"\{\d+\}", piece)
            else re.escape(piece)
            for piece in pieces
        )
        result.append((re.compile(pattern, re.IGNORECASE | re.DOTALL), translations))
    return result


@lru_cache(maxsize=2048)
def _translate(language: str, text: str) -> str:
    index = 0 if language == "en" else 1
    values = _catalog.get(text.casefold())
    if values:
        return values[index]
    for pattern, translations in _templates():
        match = pattern.fullmatch(text)
        if match:
            captures: dict[str, str] = match.groupdict()

            def substitute(slot: re.Match[str]) -> str:
                return captures["v" + slot.group(1)]

            return re.sub(r"\{(\d+)\}", substitute, translations[index])
    if "\n" in text or "\r" in text:
        return "".join(
            _translate(language, line.rstrip("\r\n")) + line[len(line.rstrip("\r\n")) :]
            for line in text.splitlines(keepends=True)
        )
    return text


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
        QGroupBox,
        QLabel,
        QLineEdit,
        QTableWidget,
        QTabWidget,
        QWidget,
        QWizardPage,
    )

    for widget in [root, *root.findChildren(QWidget)]:
        if isinstance(widget, (QLabel, QAbstractButton)) and not widget.property(
            "preserveUserText"
        ):
            widget.setText(tr(widget.text()))
        if isinstance(widget, QGroupBox):
            widget.setTitle(tr(widget.title()))
        if isinstance(widget, QWizardPage):
            widget.setTitle(tr(widget.title()))
            widget.setSubTitle(tr(widget.subTitle()))
        for action in widget.actions():
            action.setText(tr(action.text()))
            action.setToolTip(tr(action.toolTip()))
        if widget.accessibleName():
            widget.setAccessibleName(tr(widget.accessibleName()))
        if widget.accessibleDescription():
            widget.setAccessibleDescription(tr(widget.accessibleDescription()))
        if widget.toolTip():
            widget.setToolTip(tr(widget.toolTip()))
        if isinstance(widget, QLineEdit):
            widget.setPlaceholderText(tr(widget.placeholderText()))
        if (
            isinstance(widget, QComboBox)
            and not widget.isEditable()
            and not widget.property("preserveUserText")
        ):
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
    from PySide6.QtCore import QEvent, QLibraryInfo, QLocale, QObject, QTranslator

    set_language(language)
    locale = QLocale({"pt-BR": "pt_BR", "en": "en_US", "es": "es_ES"}.get(language, "pt_BR"))
    QLocale.setDefault(locale)
    old = getattr(app, "_caio_qt_translation", None)
    if old is not None:
        app.removeTranslator(old)
        old.deleteLater()
    translator = QTranslator(app)
    if translator.load(
        locale, "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ):
        app.installTranslator(translator)
    app._caio_qt_translation = translator
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
