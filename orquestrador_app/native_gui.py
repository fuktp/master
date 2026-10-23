from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from .i18n import tr
from .io import Lock, atomic_json, read_json
from .native_updates import open_wizard, prepare_zip
from .ui import explain


def preferences(window: Any) -> None:
    file = window.paths.root / "update.json"
    values = read_json(file) if file.is_file() else {}
    dialog = QDialog(window)
    dialog.setWindowTitle(tr("Atualização…"))
    dialog.resize(680, 260)
    form = QFormLayout(dialog)
    form.addRow(
        QLabel(
            "O wizard WinForms prepara versões em pastas separadas. Dados e extratores são preservados."
        )
    )
    address = QLineEdit(values.get("feed_url", ""))
    address.setPlaceholderText("Endereço HTTPS fornecido pelo administrador; opcional")
    form.addRow(tr("Feed interno (opcional, indisponível nesta edição)"), address)
    address.setEnabled(False)
    form.addRow(
        explain(
            "Feed é um endereço de catálogo de versões fornecido pela equipe de TI. Como não há servidor HTTPS disponível, use Atualizar por ZIP local. Nenhuma consulta automática será realizada."
        )
    )
    form.addRow(
        explain(
            "A atualização por ZIP verifica a integridade, guarda a versão atual e reinicia o aplicativo após sua confirmação."
        )
    )

    def persist() -> None:
        url = address.text().strip()
        atomic_json(file, {**values, "feed_url": url, "enabled": False})

    def save_preferences() -> None:
        try:
            destination = QFileDialog.getSaveFileName(
                dialog,
                tr("Salvar preferências de atualização"),
                "atualizacao.json",
                "JSON (*.json)",
            )[0]
            if not destination:
                return
            persist()
            atomic_json(Path(destination), {"enabled": False, "feed_url": address.text().strip()})
            dialog.accept()
        except Exception as exc:
            QMessageBox.warning(dialog, "Atualização", str(exc))

    def local_package() -> None:
        archive = QFileDialog.getOpenFileName(
            dialog, "Selecionar pacote completo", "", "Pacote ZIP (*.zip)"
        )[0]
        if archive:
            dialog.accept()
            from .gui import Task

            task = Task(lambda: str(prepare_zip(window.paths, Path(archive))), window)
            window.task = task
            prepared: list[str] = []
            task.done.connect(lambda result: prepared.append(result))
            task.failed.connect(window.task_error)
            task.finished.connect(lambda: handoff(window, Path(prepared[0])) if prepared else None)
            task.start()

    def repair() -> None:
        dialog.accept()
        handoff(window)

    for label, callback in (
        ("Salvar preferências", save_preferences),
        ("Abrir wizard de reparo e configuração", repair),
        ("Atualizar por ZIP local…", local_package),
    ):
        button = QPushButton(tr(label))
        button.clicked.connect(callback)
        form.addRow(button)
    dialog.exec()


def handoff(window: Any, package: Path | None = None, backup: Path | None = None) -> None:
    try:
        if window.task and window.task.isRunning():
            raise ValueError("Aguarde a operação atual antes de atualizar.")
        if window.dev_panel.task and window.dev_panel.task.isRunning():
            raise ValueError("Aguarde o diagnóstico de Dev antes de atualizar.")
        update_task = getattr(window, "update_task", None)
        if update_task and update_task.isRunning():
            raise ValueError("Aguarde a conclusão da verificação de atualização.")
        with Lock(window.paths.lock):
            pass
        if (
            QMessageBox.question(
                window,
                "Abrir manutenção",
                "O aplicativo será fechado para o wizard de instalação/atualização. Continuar?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        open_wizard(window.paths, package, backup)
        window.exit_requested = True
        window.close()
    except Exception as exc:
        window.task_error(str(exc))


def check_automatically(window: Any, force: bool = False) -> None:
    return
