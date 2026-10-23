"""Shared native controls and explicit light palette; no extra UI framework."""

from __future__ import annotations

import json
from functools import cache
from string import Template
from typing import Any

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTime
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .i18n import display_value, tr
from .resources import asset_path

DAYS = (
    "Segunda-feira",
    "Terça-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sábado",
    "Domingo",
)


class SingleLineLabel(QLabel):
    """A bounded footer: elide the visible path, retain the complete accessible text/tooltip."""

    def __init__(self, text: str):
        super().__init__(text)
        self.full_text = text
        self.setProperty("singleLine", True)
        self.setWordWrap(False)
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setMinimumWidth(0)
        self.setMaximumWidth(650)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self.fontMetrics().height() + 6)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.setText(
            self.fontMetrics().elidedText(
                self.full_text, Qt.TextElideMode.ElideMiddle, max(0, self.contentsRect().width())
            )
        )
        super().resizeEvent(event)


@cache
def theme() -> dict[str, Any]:
    return json.loads(asset_path("dashboard-theme.json").read_text(encoding="utf-8"))


def apply_theme(app: QApplication) -> None:
    if not app.property("caioThemeInitialized"):
        app.setStyle("Fusion")
        app.setProperty("caioThemeInitialized", True)
    colors = theme()
    app.setFont(
        QFont(
            colors["textClasses"]["label"]["fontFace"], colors["textClasses"]["label"]["fontSize"]
        )
    )
    palette = QPalette()
    for role, name in {
        QPalette.ColorRole.Window: "backgroundNeutral",
        QPalette.ColorRole.WindowText: "foreground",
        QPalette.ColorRole.Base: "background",
        QPalette.ColorRole.AlternateBase: "backgroundDark",
        QPalette.ColorRole.Text: "foreground",
        QPalette.ColorRole.Button: "backgroundDark",
        QPalette.ColorRole.ButtonText: "firstLevelElements",
        QPalette.ColorRole.Highlight: "accent",
        QPalette.ColorRole.HighlightedText: "foregroundSelected",
        QPalette.ColorRole.ToolTipBase: "background",
        QPalette.ColorRole.ToolTipText: "foregroundDark",
        QPalette.ColorRole.PlaceholderText: "foregroundNeutralSecondary",
    }.items():
        palette.setColor(QPalette.ColorGroup.All, role, QColor(colors[name]))
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled, role, QColor(colors["foregroundNeutralSecondaryAlt"])
        )
    app.setPalette(palette)
    stylesheet = Template("""
        QWidget { font-family: "$font"; font-size: ${bodySize}pt; color: $foreground; }
        QMainWindow, QDialog, QWizard, QScrollArea { background: $backgroundNeutral; }
        QLabel { background: transparent; color: $foreground; }
        QLabel[role="title"] { font-family: "$headingFont"; font-size: ${titleSize}pt; font-weight: 600; color: $firstLevelElements; }
        QLabel[role="section"] { font-family: "$headingFont"; font-size: ${sectionSize}pt; font-weight: 600; color: $firstLevelElements; }
        QLabel[role="muted"] { color: $foregroundNeutralSecondary; }
        QLabel[role="metric"] { font-size: 28pt; font-weight: 600; color: $firstLevelElements; }
        QFrame[role="summary"] { background: $background; border: 1px solid $shapeStroke; border-top: 3px solid $center; border-radius: ${radius}px; }
        QFrame#navigation { background: $firstLevelElements; border: none; }
        QFrame#navigation QLabel { color: $foregroundLight; }
        QFrame#navigation QLabel[role="brand"] { font-size: 22pt; font-weight: 600; }
        QListWidget#navigationList { background: transparent; border: none; padding: 0; outline: none; }
        QListWidget#navigationList::item { color: $foregroundLight; padding: 12px; border-left: 3px solid transparent; }
        QListWidget#navigationList::item:hover { background: $accent; }
        QListWidget#navigationList::item:selected { background: $accent; border-left: 3px solid $center; }
        QListWidget#navigationList::item:focus { border: 2px solid $foregroundLight; }
        QWidget#activity { background: $background; border-top: 1px solid $shapeStroke; }
        QSplitter::handle { background: $shapeStroke; height: 4px; }
        QLabel[severity="error"] { color: $bad; font-weight: 600; }
        QLabel[severity="warning"] { color: $foregroundDark; background: $backgroundDark; padding: 8px; border-left: 4px solid $neutral; }
        QLabel[severity="success"] { color: $good; font-weight: 600; }
        QTabWidget::pane { border: none; background: $backgroundNeutral; }
        QTabBar::tab { padding: 10px 14px; background: $backgroundDark; color: $firstLevelElements; border-bottom: 3px solid transparent; }
        QTabBar::tab:selected { background: $background; border-bottom: 3px solid $center; }
        QTabBar::tab:focus { border: 2px solid $accent; }
        QPushButton { padding: 8px 14px; min-height: 22px; background: $background; color: $accent; border: 1px solid $shapeStroke; border-radius: 6px; }
        QPushButton:hover { background: $backgroundDark; border-color: $accent; }
        QPushButton:pressed { background: $backgroundDark; border-color: $firstLevelElements; }
        QPushButton[emphasis="solid"] { background: $accent; color: $foregroundButton; border-color: $accent; font-weight: 600; }
        QPushButton[emphasis="solid"]:hover, QPushButton[emphasis="solid"]:pressed { background: $firstLevelElements; }
        QPushButton[intent="danger"] { color: $bad; border-color: $bad; }
        QPushButton[intent="warning"] { color: $foregroundDark; border-color: $neutral; }
        QPushButton:focus, QToolButton:focus { border: 2px solid $firstLevelElements; }
        QPushButton:disabled { background: $backgroundDark; color: $foregroundNeutralSecondary; border-color: $shapeStroke; }
        QToolButton { padding: 7px; background: $background; color: $firstLevelElements; border: 1px solid $shapeStroke; border-radius: 5px; }
        QToolButton:checked { background: $accent; color: $foregroundSelected; }
        QCheckBox, QRadioButton { color: $foreground; spacing: 8px; }
        QCheckBox::indicator { width: 18px; height: 18px; background: $background; border: 1px solid $foregroundNeutralSecondary; border-radius: 3px; }
        QCheckBox::indicator:checked { background: $accent; image: url("$checkmark"); }
        QCheckBox:disabled, QRadioButton:disabled { color: $foregroundNeutralSecondaryAlt; }
        QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QAbstractSpinBox, QListWidget { background: $background; color: $foreground; padding: 7px; border: 1px solid $shapeStroke; border-radius: 6px; selection-background-color: $accent; selection-color: $foregroundSelected; }
        QLineEdit, QComboBox, QAbstractSpinBox { min-height: 22px; }
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QAbstractSpinBox:focus { border: 2px solid $accent; }
        QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] { border: 2px solid $bad; }
        QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled { background: $backgroundDark; color: $foregroundNeutralSecondary; }
        QComboBox QAbstractItemView, QMenu { background: $background; color: $foreground; selection-background-color: $accent; selection-color: $foregroundSelected; }
        QMenu::item:selected { background: $accent; color: $foregroundSelected; }
        QTableView { background: $background; color: $foreground; alternate-background-color: $alternate; gridline-color: $foregroundNeutralTertiaryAlt; selection-background-color: $accent; selection-color: $foregroundSelected; border: 1px solid $shapeStroke; border-radius: 6px; }
        QTableView::item { padding: 8px; color: $foreground; }
        QTableView::item:selected { background: $accent; color: $foregroundSelected; }
        QHeaderView::section, QTableCornerButton::section { background: $tableAccent; color: $foregroundLight; padding: 9px; border: 1px solid $accent; font-weight: 600; }
        QProgressBar { color: $firstLevelElements; border: 1px solid $shapeStroke; min-height: 6px; max-height: 6px; }
        QProgressBar::chunk { background: $center; }
        QToolTip { background: $background; color: $foregroundDark; border: 1px solid $shapeStroke; }
        QGroupBox { background: $background; border: 1px solid $shapeStroke; border-radius: ${radius}px; margin-top: 14px; padding: 14px; }
        QGroupBox::title { color: $firstLevelElements; subcontrol-origin: margin; left: 12px; padding: 0 4px; font-weight: 600; }
        QScrollArea { border: none; }
        QScrollBar:vertical { background: $backgroundNeutral; width: 14px; margin: 0; }
        QScrollBar:horizontal { background: $backgroundNeutral; height: 14px; margin: 0; }
        QScrollBar::handle { background: $foregroundNeutralSecondary; border-radius: 5px; min-height: 28px; min-width: 28px; }
        QScrollBar::handle:hover { background: $accent; }
        QScrollBar::handle:pressed { background: $firstLevelElements; }
        QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
        QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
        QStatusBar { color: $foregroundNeutralSecondary; background: $backgroundNeutral; }
    """)
    rendered = stylesheet.substitute(
        colors,
        font=colors["textClasses"]["label"]["fontFace"],
        bodySize=colors["textClasses"]["label"]["fontSize"],
        titleSize=colors["textClasses"]["largeTitle"]["fontSize"],
        headingFont=colors["textClasses"]["largeTitle"]["fontFace"],
        sectionSize=colors["textClasses"]["title"]["fontSize"],
        radius=colors["visualStyles"]["*"]["*"]["border"][0]["radius"],
        alternate=colors["visualStyles"]["tableEx"]["*"]["values"][0]["backColorSecondary"][
            "solid"
        ]["color"],
        checkmark=asset_path("checkmark.svg").as_posix(),
    )
    # Reopening a window must not rebuild the style of every existing Qt control.
    if app.styleSheet() != rendered:
        app.setStyleSheet(rendered)
    app.setApplicationName("CAIO")
    app.setWindowIcon(icon())


def icon() -> QIcon:
    result = QIcon(str(asset_path("caio.ico")))
    if result.isNull():
        raise ValueError("O ícone CAIO não pôde ser carregado.")
    return result


def configure_table(table: Any) -> None:
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setMinimumSectionSize(95)
    table.horizontalHeader().setMinimumHeight(42)
    table.horizontalHeader().setDefaultAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(44)
    table.setShowGrid(False)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.horizontalHeader().setStretchLastSection(True)
    table.setPalette(QApplication.palette())


class FlowLayout(QLayout):
    """Wrap action rows without hiding actions or growing the minimum window width."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item: QLayoutItem) -> None:
        self.items.append(item)

    def __del__(self) -> None:
        # QLayoutItem ownership must be released before Qt destroys its widgets.
        while self.items:
            self.takeAt(0)

    def count(self) -> int:
        return len(self.items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # type: ignore[override]  # Qt permits null for an absent item.
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self.arrange(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self.items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def arrange(self, rect: QRect, measure: bool) -> int:
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            size = item.sizeHint()
            if x > area.x() and x + size.width() > area.right() + 1:
                x, y, line_height = area.x(), y + line_height + self.spacing(), 0
            if not measure:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self.spacing()
            line_height = max(line_height, size.height())
        return y + line_height - rect.y() + margins.bottom()


class DaysPicker(QWidget):
    def __init__(self, days: list[int], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.buttons = []
        for index, name in enumerate(DAYS):
            button = QToolButton()
            button.setText(tr(name)[:1])
            button.setToolTip(tr(name))
            button.setAccessibleName(tr(name))
            button.setCheckable(True)
            button.setChecked(index in days)
            button.setMinimumSize(44, 38)
            self.buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()

    def values(self) -> list[int]:
        return [i for i, button in enumerate(self.buttons) if button.isChecked()]

    def set_days(self, days: list[int]) -> None:
        for i, button in enumerate(self.buttons):
            button.setChecked(i in days)


class TimesPicker(QWidget):
    def __init__(self, times: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.addItems(sorted(times))
        self.list.setMaximumHeight(90)
        layout.addWidget(self.list)
        tools = QVBoxLayout()
        self.clock = QTimeEdit(QTime(8, 30))
        self.clock.setDisplayFormat("HH:mm")
        self.clock.setToolTip(
            tr("Escolha a hora e os minutos; depois clique em Adicionar horário.")
        )
        tools.addWidget(self.clock)
        add = QPushButton(tr("Adicionar horário"))
        add.clicked.connect(self.add)
        tools.addWidget(add)
        remove = QPushButton(tr("Retirar horário"))
        remove.clicked.connect(lambda: self.list.takeItem(self.list.currentRow()))
        tools.addWidget(remove)
        layout.addLayout(tools)

    def add(self) -> None:
        value = self.clock.time().toString("HH:mm")
        if value not in self.values():
            self.list.addItem(value)
            self.list.sortItems()

    def values(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]


def explain(text: str) -> QLabel:
    label = QLabel(tr(text))
    label.setWordWrap(True)
    label.setProperty("role", "muted")
    return label


def set_cell(table: Any, row: int, column: int, value: Any, role: Any = None) -> None:
    from PySide6.QtWidgets import QTableWidgetItem

    text = str(value if value is not None else "")
    text = display_value(text)
    item = table.item(row, column)
    if item is None:
        item = QTableWidgetItem(text)
        table.setItem(row, column, item)
    elif item.text() != text:
        item.setText(text)
    color = QColor(theme()["foreground"])
    if item.foreground().color() != color:
        item.setForeground(color)
    if item.toolTip() != text:
        item.setToolTip(text)
    if role is not None and item.data(Qt.ItemDataRole.UserRole) != role:
        item.setData(Qt.ItemDataRole.UserRole, role)
