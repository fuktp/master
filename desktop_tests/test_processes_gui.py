from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from desktop_tests.ui_helpers import settle
from orquestrador_app.config import Routine, defaults, save
from orquestrador_app.engine import Engine
from orquestrador_app.io import BusyError, Lock, digest
from orquestrador_app.paths import Paths
from orquestrador_app.processes import OwnedTree
from orquestrador_app.resources import source_root


def test_real_process_lock_active_owner_then_crash_recovery(tmp_path: Path) -> None:
    lock = tmp_path / "active.lock"
    source = "from pathlib import Path\nimport sys\nfrom orquestrador_app.io import Lock\nwith Lock(Path(sys.argv[1])):\n print('owned',flush=True)\n sys.stdin.read()\n"
    process = subprocess.Popen(
        [sys.executable, "-c", source, str(lock)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "owned"
        with pytest.raises(BusyError):
            with Lock(lock):
                pass
        process.kill()
        process.wait(timeout=5)
        with Lock(lock):
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def test_owned_tree_does_not_kill_unrelated_process() -> None:
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        tree = OwnedTree(owned)
        tree.stop(grace=0.2)
        assert owned.poll() is not None
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)
        if owned.poll() is None:
            owned.kill()
            owned.wait(timeout=5)


def test_additional_script_real_worker_tracks_changes_without_hash_authorization(
    tmp_path: Path,
) -> None:
    paths = Paths.user(tmp_path / "isolated")
    paths.ensure()
    config = defaults(paths, source_root())
    script = tmp_path / "custom_local.py"
    script.write_text(
        "from pathlib import Path\nimport sys\nfrom openpyxl import Workbook\np=Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True)\nb=Workbook();b.active.append(['Header']);b.active.append(['value']);b.save(p/'saida.xlsx');b.close()\n"
    )
    job = Routine(
        id="custom_local",
        label="Script local autorizado",
        script=str(script),
        trusted_sha256=digest(script),
        command="",
        options=["{output_dir}"],
        requires_browser=False,
        target=str(tmp_path / "final.xlsx"),
        staged_output="saida.xlsx",
    )
    config.routines.append(job)
    save(paths, config)
    result = Engine(paths).run([job.id], force=True)
    assert result[0]["status"] == "success", result
    assert Path(job.target).exists()
    script.write_text("raise RuntimeError('tampered')")
    result = Engine(paths).run([job.id], force=True)
    assert result[0]["status"] == "failed"
    assert "tampered" in result[0]["error"]
    from orquestrador_app.script_versions import versions

    assert len(versions(paths, job)) == 2


def test_real_background_agent_processes_queue_with_main_interface_closed(tmp_path: Path) -> None:
    from orquestrador_app.notifications import enqueue
    from orquestrador_app.processes import command, spawn

    paths = Paths.user(tmp_path)
    paths.ensure()
    config = defaults(paths, source_root())
    for job in config.routines:
        job.enabled = False
    save(paths, config)
    engine = Engine(paths)
    enqueue(
        engine.store,
        config,
        "complete",
        config.routines[0].id,
        "",
        "Concluída; dado sintético de teste.",
    )
    agent = spawn(
        command("--data-root", str(paths.root), "--agent"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 5
        dispatched = False
        while time.monotonic() < deadline:
            with engine.store.connect() as db:
                dispatched = db.execute("SELECT delivered FROM notifications").fetchone()[0] == 1
            if dispatched:
                break
            time.sleep(0.02)
        assert dispatched, (
            "Agente não processou a fila; não é uma prova de notificação nativa Windows."
        )
        assert engine.store.history() == []
    finally:
        OwnedTree(agent).stop(grace=0.5)


def test_main_window_and_wizard_have_real_controls_and_responsive_timer(tmp_path: Path) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from orquestrador_app.gui import InstallWizard, MainWindow, RoutineDialog, Task

    app = QApplication.instance() or QApplication([])
    paths = Paths.user(tmp_path)
    paths.ensure()
    config = defaults(paths, source_root())
    save(paths, config)
    window = MainWindow(paths)
    settle(window)
    wizard = InstallWizard(paths, config)
    dialog = RoutineDialog(config, config.routines[0])
    try:
        window.show()
        app.processEvents()
        assert window.tabs.count() == 6 and window.panel.rowCount() == 5
        assert len(wizard.pageIds()) == 8
        assert dialog.times.values() == ["08:30"]
        assert not paths.root.joinpath("installation.json").exists()
        ticks = []
        timer = QTimer()
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start(10)
        task = Task(lambda: time.sleep(0.12))
        task.start()
        deadline = time.monotonic() + 2
        while task.isRunning() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.001)
        task.wait(1000)
        timer.stop()
        assert len(ticks) >= 5
    finally:
        dialog.reject()
        wizard.reject()
        window.timer.stop()
        window.tray.hide()
        window.exit_requested = True
        window.close()
        app.processEvents()
