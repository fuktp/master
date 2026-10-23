"""Capture actual Qt widgets with isolated data; never run corporate extraction."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from orquestrador_app.config import defaults, save
from orquestrador_app.gui import MainWindow, RoutineDialog
from orquestrador_app.paths import Paths
from orquestrador_app.resources import source_root


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    captures: list[str] = []
    for language in ("pt-BR", "en", "es"):
        with tempfile.TemporaryDirectory(prefix="caio-design-") as temporary:
            paths = Paths.user(temporary)
            paths.ensure()
            config = defaults(paths, source_root())
            config.language = language
            save(paths, config)
            window = MainWindow(paths)
            window.timer.stop()
            window.dev_panel.timer.stop()
            window.show()
            deadline = time.monotonic() + 15
            while window.read_task is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.002)
            if window.read_task is not None:
                raise RuntimeError("Initial observation did not finish")
            try:
                for width, height in ((980, 720), (1040, 850), (1440, 940)):
                    window.resize(width, height)
                    for page in range(window.tabs.count()):
                        window.navigation.setCurrentRow(page)
                        app.processEvents()
                        assert window.width() == width, "Content forced the window wider"
                        assert window.log.isVisible() and window.status_label.isVisible()
                        assert window.page_title.text()
                        name = f"{language}-{width}-page-{page}.png"
                        assert window.grab().save(str(args.output / name))
                        captures.append(name)
                window.navigation.setCurrentRow(0)
                window.navigation.setFocus()
                QTest.keyClick(window.navigation, Qt.Key.Key_Down)
                assert window.tabs.currentIndex() == 1
                dialog = RoutineDialog(config, config.routines[0], window)
                dialog.show()
                app.processEvents()
                assert dialog.grab().save(str(args.output / f"{language}-routine.png"))
                dialog.frequency.showPopup()
                app.processEvents()
                assert (
                    dialog.frequency.view()
                    .window()
                    .grab()
                    .save(str(args.output / f"{language}-routine-popup.png"))
                )
                dialog.frequency.hidePopup()
                dialog.reject()
            finally:
                window.timer.stop()
                window.dev_panel.timer.stop()
                window.tray.hide()
                window.exit_requested = True
                window.close()
                deadline = time.monotonic() + 15
                while (
                    any(task.isRunning() for task in window.findChildren(QThread))
                    and time.monotonic() < deadline
                ):
                    app.processEvents()
                    time.sleep(0.002)
                app.processEvents()
    report = {
        "platform": app.platformName(),
        "pages": captures,
        "locales": ["pt-BR", "en", "es"],
        "keyboard_navigation": "passed",
        "popup": "Qt ComboBox opened; Windows popup not verified",
        "windows_executed": False,
    }
    (args.output / "capture.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
