from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .clock import local_now
from .config import load, save
from .engine import Engine
from .io import BusyError, Lock, read_json
from .monitor_status import poll_seconds, write_heartbeat
from .paths import Paths
from .processes import command, spawn
from .qt_tasks import Task, VpnNotice
from .schedule import eligible, paused_until, period_for
from .store import Store


def run_agent(paths: Paths) -> int:
    paths.ensure()
    if (paths.root / "state/uninstalled.json").is_file() and not (
        paths.root / "installation.json"
    ).is_file():
        return 0
    try:
        ownership = Lock(paths.root / "state/monitor.lock")
        ownership.__enter__()
    except BusyError:
        return 0
    try:
        existing_app = QApplication.instance()
        if existing_app is not None and not isinstance(existing_app, QApplication):
            raise RuntimeError("O monitor exige uma instância QApplication.")
        app = existing_app if existing_app is not None else QApplication(sys.argv[:1])
        app.setQuitOnLastWindowClosed(False)
        from .i18n import install_translation, tr

        monitor_language = load(paths).language
        install_translation(app, monitor_language)
        from .notifications import claim, show
        from .ui import icon
        from .windows_identity import set_process_identity

        set_process_identity(paths)
        tray = QSystemTrayIcon(icon())
        tray.setToolTip(tr("Orquestrador • monitor de horários e atualização"))
        menu = QMenu()
        open_action = QAction(tr("Abrir Orquestrador"), menu)
        open_action.triggered.connect(lambda: spawn(command("--data-root", str(paths.root))))
        menu.addAction(open_action)
        pause_action = QAction(tr("Pausar/retomar agendamento"), menu)

        def pause() -> None:
            try:
                with Lock(paths.maintenance_lock), Lock(paths.root / "state/config.lock"):
                    config = load(paths)
                    config.scheduling_paused = not config.scheduling_paused
                    save(paths, config)
            except BusyError:
                show(
                    tray, "Atualização/manutenção em andamento; aguarde para alterar o agendamento."
                )

        pause_action.triggered.connect(pause)
        menu.addAction(pause_action)
        tray.setContextMenu(menu)
        tray.show()
        store = Store(paths.database)
        engine = Engine(paths)
        from .ui import apply_theme, icon

        apply_theme(app)
        tray.setIcon(icon())
        planner: Task | None = None
        task: Task | None = None
        last_monitor = 0.0
        notices: list[VpnNotice] = []

        def open_detail() -> None:
            spawn(command("--data-root", str(paths.root), "--run-detail", "notifications"))

        tray.messageClicked.connect(open_detail)

        def notifications(rows: list[dict[str, object]]) -> None:
            for row in rows:
                show(tray, str(row["message"]))
                if row["kind"] == "vpn":
                    notices.append(VpnNotice(store, str(row["run"]), str(row["message"])))

        def observe() -> dict[str, object]:
            nonlocal last_monitor
            with Lock(paths.maintenance_lock):
                pointer = paths.root / "installation.json"
                restart = False
                if pointer.is_file():
                    value = read_json(pointer)
                    if value.get("distribution") == "native-scripts":
                        from .resources import source_root

                        restart = source_root().parent.resolve() != Path(value["release"]).resolve()
                    elif getattr(sys, "frozen", False):
                        restart = os.path.normcase(value["executable"]) != os.path.normcase(
                            sys.executable
                        )
                config = load(paths)
                engine.config = config
                now = local_now()
                busy = bool(task and task.isRunning())
                interval = poll_seconds(config, store, now, busy)
                paused = config.scheduling_paused or paused_until(config.paused_until, now)
                write_heartbeat(
                    paths,
                    interval=interval,
                    state="running" if busy else "paused" if paused else "idle",
                )
                if now.timestamp() - last_monitor >= 60:
                    engine.monitor()
                    last_monitor = now.timestamp()
                due = (
                    not busy
                    and not restart
                    and any(
                        eligible(
                            j,
                            store.decision_state(j.id, period_for(j, now)),
                            now,
                            paused=paused,
                            excluded_dates=config.calendar.get("dates", []),
                        ).due
                        for j in config.routines
                    )
                )
                return {
                    "restart": restart,
                    "language": config.language,
                    "due": due,
                    "interval": interval,
                    "notifications": claim(store),
                }

        def observed(value: dict[str, object]) -> None:
            nonlocal task, monitor_language
            language = str(value["language"])
            if language != monitor_language:
                install_translation(app, language)
                monitor_language = language
                tray.setToolTip(tr("Orquestrador • monitor de horários e atualização"))
                open_action.setText(tr("Abrir Orquestrador"))
                pause_action.setText(tr("Pausar/retomar agendamento"))
            timer.setInterval(int(str(value["interval"])) * 1000)
            if value["restart"] and not (task and task.isRunning()):
                tray.hide()
                app.quit()
                return
            if value["due"] and not (task and task.isRunning()):
                if task:
                    task.deleteLater()
                task = Task(lambda: Engine(paths).run(scheduled=True))
                task.failed.connect(lambda error: store.event(None, "monitor_error", error))
                task.start()
            notifications(value["notifications"])  # type: ignore[arg-type]

        def failed(error: str) -> None:
            timer.setInterval(10000)

            # Error reporting also runs outside the event loop's thread.
            def record() -> None:
                write_heartbeat(paths, interval=10, state="error", error=error)
                store.event(None, "monitor_error", error)

            diagnostic = Task(record, app)
            diagnostic.finished.connect(diagnostic.deleteLater)
            diagnostic.start()

        def protected_tick() -> None:
            nonlocal planner
            stop = paths.root / "state/monitor-stop.json"
            if stop.is_file():
                import psutil

                request = read_json(stop)
                if (
                    request.get("owner") == "caio-monitor-stop-v1"
                    and request.get("pid") == os.getpid()
                    and abs(request.get("created", 0) - psutil.Process().create_time()) < 0.01
                    and not (task and task.isRunning())
                ):
                    timer.stop()
                    tray.hide()
                    app.quit()
                    return
            if planner and planner.isRunning():
                return
            if planner:
                planner.deleteLater()
            planner = Task(observe, app)
            planner.done.connect(observed)
            planner.failed.connect(failed)
            planner.start()

        timer = QTimer()
        timer.timeout.connect(protected_tick)
        timer.start(30000)
        QTimer.singleShot(0, protected_tick)
        result = app.exec()
        if planner and planner.isRunning():
            planner.wait(15000)
        write_heartbeat(paths, interval=30, state="stopped")
        if task and task.isRunning():
            # Agent shutdown must not kill a live extraction without a recorded cooperative cancellation.
            for row in store.history():
                if row["status"] == "running":
                    store.control(row["id"], "cancel")
            task.wait(15000)
        return result
    finally:
        ownership.__exit__()
