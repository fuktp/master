from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QSystemTrayIcon,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from . import VERSION
from .clock import local_now
from .config import (
    KNOWN,
    Config,
    Routine,
    Schedule,
    discover,
    from_dict,
    import_preview,
    load,
    migrate,
    portable,
    preset_days,
    save,
    script_identifier,
    to_dict,
    validate,
)
from .connectivity import as_dict, classify, probe
from .driver import diagnose
from .editors import CalendarEditor, DependencyEditor, RetryEditor, SettingsEditor, field_error
from .engine import Engine
from .files import Publisher
from .i18n import duration, install_translation, tr, translate_tree
from .install import Installer
from .io import Lock, atomic_json, digest, read_json
from .observation import HistoryModel, Observer
from .paths import Paths, check_directory, identity, onedrives
from .processes import command, spawn
from .qt_tasks import Task, VpnNotice
from .resources import script_path, source_root
from .sandbox import check_location, confined, mark, prepare_config, remember
from .store import Store
from .tasks import WindowsTasks, current_user
from .ui import (
    DAYS,
    DaysPicker,
    FlowLayout,
    SingleLineLabel,
    TimesPicker,
    apply_theme,
    configure_table,
    explain,
    icon,
    set_cell,
)
from .worker import module_for, public_pipefy

STATUS = {
    "running": "Em execução",
    "success": "Concluída",
    "failed": "Falhou",
    "skipped": "Ignorada; pendente",
    "cancelled": "Cancelada",
    "not_eligible": "Não elegível",
    "ignored": "Desabilitada",
    "blocked_dependency": "Bloqueada por dependência",
}


def button(
    text: str,
    callback: Callable[..., Any],
    layout: Any,
    *,
    emphasis: str = "outline",
    intent: str = "neutral",
) -> QPushButton:
    result = QPushButton(tr(text))
    result.setProperty("emphasis", emphasis)
    result.setProperty("intent", intent)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.clicked.connect(callback)
    layout.addWidget(result)
    return result


def path_field(value: str, *, file: bool = False) -> tuple[QWidget, QLineEdit]:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    field = QLineEdit(value)
    layout.addWidget(field)

    def browse() -> None:
        result = (
            QFileDialog.getOpenFileName(widget, "Selecionar arquivo", field.text())[0]
            if file
            else QFileDialog.getExistingDirectory(widget, "Selecionar pasta", field.text())
        )
        if result:
            field.setText(result)

    choose = button("Escolher…", browse, layout)
    layout.setStretch(0, 1)
    layout.setStretch(1, 1)
    choose.setMinimumHeight(field.sizeHint().height())
    return widget, field


def json_view(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def friendly_details(value: Any, level: int = 0, key: str = "") -> str:
    """Localize operational labels; preserve user-authored values and paths."""
    from .i18n import display_value

    labels = {
        "source": "Origem",
        "target": "Destino",
        "file": "Arquivo",
        "size": "Tamanho (bytes)",
        "modified": "Última alteração",
        "exists": "Arquivo existe",
        "validation": "Validação",
        "destination_state": "Estado do destino",
        "external_sync": "Sincronização externa",
        "operation": "Operação",
        "creates_backup": "Criará backup",
        "events_keys": "Chaves de Eventos",
        "current": "Versão atual",
        "backup": "Backup",
        "identical": "Conteúdo idêntico",
        "preserves_current_before_restore": "Preservará a versão atual antes de restaurar",
        "differences_available": "Comparação disponível",
        "at": "Data",
        "status": "Estado",
        "reason": "Motivo",
        "requirements": "Requisitos de sucesso",
        "blockers": "Bloqueios",
        "position": "Posição na fila",
        "label": "Rotina",
        "job": "Identificador da rotina",
        "occurrence": "Oportunidade",
        "period": "Período",
        "execution_time": "Horário efetivo",
        "queue_delay_seconds": "Intervalo entre rotinas (s)",
        "catch_up_hours": "Janela de recuperação (horas)",
        "eligible": "Elegível",
        "recovering": "Recuperação de horário perdido",
        "total": "Total",
        "components": "Componentes",
        "component": "Componente",
        "restored": "Restaurado",
        "intervention_required": "Exige intervenção",
        "complete": "Recuperação completa",
        "error": "Erro",
        "missing": "Bibliotecas ausentes",
        "imports": "Bibliotecas utilizadas",
        "executed": "Script executado",
        "limitation": "Limitação",
        "files": "Arquivos",
        "notes": "Notas desta versão",
        "version": "Versão",
        "before": "Versão anterior",
        "after": "Versão posterior",
        "changed_files": "Arquivos alterados",
        "source_diff": "Diferenças no código",
        "contract": "Contrato de saída e execução",
        "usage_bytes": "Ocupação (bytes)",
        "candidates": "Arquivos selecionados para limpeza",
        "sample": "Amostra",
        "sanitized": "Dados sensíveis removidos",
        "result": "Resultado",
    }
    codes = {
        "local": "Gravação local",
        "unavailable": "Pasta indisponível",
        "not verified": "Não verificado",
        "passed; revalidated at commit": "Validação aprovada; repetida ao publicar",
        "replace": "Substituir",
        "merge": "Mesclar Eventos",
        "simulation": "Simulação elegível",
        "conditional": "Execução condicionada",
        "depends on prior completion; not a guaranteed time": "Depende da conclusão anterior; sem horário garantido",
        "metadata and hash; contents are not assumed equivalent": "Datas, tamanhos e hashes; diferença de células não disponível",
        "configuration": "Configuração",
        "database": "Banco de dados",
        "scripts_and_launchers": "Scripts e iniciadores",
        "application_version": "Versão do aplicativo",
        "scheduled_task": "Tarefa do Agendador",
        "shortcuts": "Atalhos",
    }
    indent = "  " * level
    if isinstance(value, dict):
        return "\n".join(
            indent
            + tr(labels.get(str(k), str(k).replace("_", " ").capitalize()))
            + ": "
            + (
                "\n" + friendly_details(v, level + 1, str(k))
                if isinstance(v, (dict, list))
                else friendly_details(v, 0, str(k))
            )
            for k, v in value.items()
        )
    if isinstance(value, list):
        return (
            "\n".join(
                indent + "• " + friendly_details(item, level + 1, key).lstrip() for item in value
            )
            or indent + "—"
        )
    if isinstance(value, bool):
        return tr("Sim" if value else "Não")
    if value is None or value == "":
        return "—"
    text = str(value)
    if key in {
        "status",
        "state",
        "mode",
        "category",
        "reason",
        "component",
        "operation",
        "destination_state",
        "validation",
        "external_sync",
        "execution_time",
        "differences_available",
        "at",
        "modified",
    }:
        return tr(codes[text]) if text in codes else display_value(text)
    return text


def show_detail(parent: QWidget, title: str, value: Any) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(900, 600)
    layout = QVBoxLayout(dialog)
    content = QPlainTextEdit(value if isinstance(value, str) else json_view(value))
    content.setReadOnly(True)
    layout.addWidget(content)
    button("Fechar", dialog.accept, layout)
    dialog.exec()


class RoutineDialog(QDialog):
    def __init__(self, config: Config, job: Routine, parent: QWidget | None = None):
        super().__init__(parent)
        self.config, self.job = config, job
        self.config_paths = getattr(parent, "paths", None)
        self.updated = job
        self.setWindowTitle(f"Rotina • {job.label}")
        self.resize(750, 700)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general = QWidget()
        form = QFormLayout(general)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.enabled = QCheckBox("Habilitar esta rotina")
        self.enabled.setChecked(job.enabled)
        form.addRow(self.enabled)
        form.addRow("Origem", QLabel(job.origin))
        script, self.script = path_field(job.script, file=True)
        form.addRow("Extrator", script)
        self.version = QLineEdit(job.script_version)
        self.version.setPlaceholderText("Ex.: 1.4.0; vazio usa a identificação automática")
        form.addRow("Versão do script", self.version)
        self.version_notes = QLineEdit(job.notes)
        form.addRow(tr("Notas desta versão"), self.version_notes)
        self.category_field = QLineEdit(job.category)
        form.addRow(tr("Categoria do catálogo"), self.category_field)
        self.stalled_field = QSpinBox()
        self.stalled_field.setRange(1, 1440)
        self.stalled_field.setValue(job.stalled_minutes)
        form.addRow(tr("Alerta sem evolução (minutos)"), self.stalled_field)
        form.addRow(
            explain(
                "Salvar registra a nova versão automaticamente. O arquivo original não será sobrescrito. Scripts cadastrados são código local confiável; não há aprovação repetida por hash."
            )
        )
        self.browser = QCheckBox("Este script utiliza o navegador Edge")
        self.browser.setChecked(job.requires_browser)
        form.addRow(self.browser)
        self.command = QLineEdit(job.command)
        self.command.setPlaceholderText("Vazio para scripts sem subcomando")
        form.addRow("Subcomando do script", self.command)
        self.frequency = QComboBox()
        for label, value in (
            ("Diária: um sucesso por data", "daily"),
            ("Somente dias úteis: um sucesso por dia de segunda a sexta", "weekdays"),
            ("Semanal: um sucesso por semana", "weekly"),
            ("Todos os horários: um sucesso por ocorrência", "every_run"),
        ):
            self.frequency.addItem(label, value)
        self.frequency.setCurrentIndex(max(0, self.frequency.findData(job.schedule.frequency)))
        form.addRow("Frequência", self.frequency)
        self.times = TimesPicker(job.schedule.times)
        form.addRow("Horários próprios", self.times)
        self.days_picker = DaysPicker(job.schedule.days)
        form.addRow("Dias da semana", self.days_picker)
        self.day_pattern = QComboBox()
        self.day_pattern.addItem(tr("Padrão da frequência"))
        self.day_pattern.addItem(tr("Personalizado"))
        form.addRow("Calendário", self.day_pattern)
        form.addRow(
            explain(
                "Selecione os dias pelos botões. Passe o mouse para ver o nome completo. Semanal começa no primeiro dia selecionado; os demais recuperam pendências. Feriados não são excluídos."
            )
        )

        def refresh_day_pattern() -> None:
            days = self.days_picker.values()
            weekday = days[0] if len(days) == 1 else job.schedule.weekday
            standard = days == preset_days(self.frequency.currentData(), weekday)
            self.day_pattern.setCurrentIndex(0 if standard else 1)

        def frequency_changed() -> None:
            self.days_picker.set_days(
                preset_days(self.frequency.currentData(), job.schedule.weekday)
            )
            refresh_day_pattern()

        self.frequency.currentIndexChanged.connect(frequency_changed)
        self.day_pattern.activated.connect(
            lambda index: frequency_changed() if index == 0 else None
        )
        for day in self.days_picker.buttons:
            day.toggled.connect(refresh_day_pattern)
        refresh_day_pattern()
        form.addRow(
            explain(
                "Personalizado preserva os dias escolhidos sem mudar a regra de sucesso da frequência."
            )
        )
        self.paused = QCheckBox("Pausar o agendamento desta rotina")
        self.paused.setChecked(job.schedule.paused)
        form.addRow(self.paused)
        self.order = QComboBox()
        ordered_jobs = sorted(config.routines, key=lambda j: (j.order, j.id))
        self.order.addItems([str(i + 1) for i in range(len(ordered_jobs))])
        self.order.setCurrentIndex(next(i for i, j in enumerate(ordered_jobs) if j.id == job.id))
        form.addRow("Ordem/prioridade na fila", self.order)
        self.headless = QCheckBox("Ocultar janela do navegador (headless)")
        self.headless.setChecked(job.headless)
        form.addRow(self.headless)
        destination, self.destination = path_field(
            str(Path(job.target).parent) if job.target else ""
        )
        form.addRow("Pasta de publicação local", destination)
        self.output_name = QLineEdit(Path(job.target).name if job.target else "")
        self.output_name.setReadOnly(job.id in KNOWN)
        form.addRow("Nome do arquivo final (opcional)", self.output_name)
        if job.id not in KNOWN:
            form.addRow(
                explain(
                    "Sem publicação gerenciada: deixe pasta e nome vazios. Para publicar, informe ambos e configure staged_output nas opções avançadas."
                )
            )
        self.url = QLineEdit(job.url)
        self.url.setPlaceholderText("Vazio preserva a URL confirmada no extrator")
        form.addRow("URL configurável", self.url)
        form.addRow(
            explain(
                "Endereço da página usada pela rotina. Deixe vazio para usar a URL do extrator. Alterar este campo não troca seletores nem credenciais."
            )
        )
        self.browser.setToolTip(
            tr(
                "Ative para preparar EdgeDriver, proteger o perfil e verificar conectividade antes de executar."
            )
        )
        self.paused.setAccessibleName(tr("Pausar o agendamento desta rotina"))
        for widget in (self.headless, self.url):
            widget.setEnabled(self.browser.isChecked())
            self.browser.toggled.connect(widget.setEnabled)
        self.enabled.setToolTip(
            tr("Desabilitada: impede novos disparos manuais e agendados, preservando o histórico.")
        )
        self.paused.setToolTip(
            tr("Pausa apenas o agendamento. Executar/Forçar manualmente continua disponível.")
        )
        self.headless.setToolTip(
            tr(
                "Oculta somente o navegador. SSO e MFA podem exigir Testar login com janela visível."
            )
        )
        note = QLabel(
            "Diária: horários extras recuperam pendências. Todos os horários permite atualizar novamente após um sucesso. Recuperação reúne horários perdidos em uma oportunidade; não reexecuta toda a fila antiga."
        )
        note.setWordWrap(True)
        form.addRow(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(general)
        tabs.addTab(scroll, "Rotina e horários")
        self.dependencies_editor = DependencyEditor(config, job)
        self.retry_editor = RetryEditor(job)
        self.calendar_editor = CalendarEditor(job)
        for title, editor in [
            ("Dependências", self.dependencies_editor),
            ("Tentativas", self.retry_editor),
            ("Calendário e recuperação", self.calendar_editor),
        ]:
            wrapper = QScrollArea()
            wrapper.setWidgetResizable(True)
            wrapper.setWidget(editor)
            tabs.addTab(wrapper, tr(title))
        self.preview_button = button("Prévia semanal", self.preview_calendar, layout)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        data = dataclasses.asdict(job)
        for key in (
            "id",
            "label",
            "script",
            "origin",
            "enabled",
            "order",
            "schedule",
            "trusted_sha256",
            "script_version",
            "requires_browser",
            "command",
            "target",
            "headless",
            "url",
        ):
            data.pop(key)
        data["catch_up_hours"] = job.schedule.catch_up_hours
        self.advanced = QPlainTextEdit(json_view(data))
        advanced_form.addRow(
            QLabel(
                "Dependências: same_chain ou fresh_success + max_age_minutes.\nArgumentos: lista JSON, sem shell. Variáveis não podem conter segredos.\nPrazo esperado: horas em dias habilitados; tolerância em grace_hours.\nTentativas por categoria incluem a tentativa inicial; VPN interna = 2 × 30 s."
            )
        )
        advanced_form.addRow(self.advanced)
        self._advanced_initial = copy.deepcopy(data)
        tabs.addTab(advanced, tr("Avançado"))
        self.form_error = explain("")
        self.form_error.setProperty("severity", "error")
        layout.addWidget(self.form_error)
        controls = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        controls.button(QDialogButtonBox.StandardButton.Save).setText(tr("Salvar"))
        controls.button(QDialogButtonBox.StandardButton.Save).setProperty("emphasis", "solid")
        save_button = controls.button(QDialogButtonBox.StandardButton.Save)
        save_button.style().unpolish(save_button)
        save_button.style().polish(save_button)
        controls.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancelar"))
        controls.accepted.connect(self.accept_values)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)
        self._initial_controls = self.control_state()

    def control_state(self) -> tuple[Any, ...]:
        values: list[Any] = []
        for field in self.findChildren(QWidget):
            if isinstance(field, QLineEdit):
                values.append(field.text())
            elif isinstance(field, QPlainTextEdit):
                values.append(field.toPlainText())
            elif isinstance(field, QComboBox):
                values.append(field.currentIndex())
            elif isinstance(field, QCheckBox):
                values.append(field.isChecked())
        return (*values, tuple(self.times.values()), tuple(self.days_picker.values()))

    def reject(self) -> None:
        if any(
            getattr(self, name, None) and getattr(self, name).isRunning()
            for name in ("preview_task", "dependency_task")
        ):
            self.form_error.setText(tr("Aguarde a prévia terminar antes de fechar."))
            return
        if self.isVisible() and self.control_state() != self._initial_controls:
            if (
                QMessageBox.question(
                    self,
                    tr("Alterações não salvas"),
                    tr("Descartar as alterações desta edição?"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
        super().reject()

    def preview_calendar(self) -> None:
        previous = getattr(self, "preview_task", None)
        if previous and previous.isRunning():
            return
        try:
            candidate = self.collect_values()
            job = candidate.job(self.job.id)
            from .clock import local_now
            from .schedule import opportunities, period_for

            task = Task(
                lambda: opportunities(
                    job,
                    Store(self.config_paths.database).decision_state(
                        job.id, period_for(job, local_now())
                    ),
                    local_now(),
                    candidate,
                )
                if self.config_paths
                else opportunities(job, {}, local_now(), candidate),
                self,
            )
            self.preview_task = task
            task.done.connect(lambda value: show_detail(self, tr("Prévia semanal"), value))
            task.failed.connect(lambda text: self.form_error.setText(text))
            task.start()
        except Exception as exc:
            self.form_error.setText(str(exc))

    def collect_values(self) -> Config:
        value = dataclasses.asdict(self.job)
        extra = json.loads(self.advanced.toPlainText())
        catchup = extra.pop("catch_up_hours", 24)
        value.update(extra)
        value.update(
            enabled=self.enabled.isChecked(),
            script=self.script.text(),
            order=self.order.currentIndex(),
            script_version=self.version.text().strip(),
            notes=self.version_notes.text().strip(),
            category=self.category_field.text().strip(),
            stalled_minutes=self.stalled_field.value(),
            requires_browser=self.browser.isChecked(),
            command=self.command.text().strip(),
            headless=self.headless.isChecked(),
            url=self.url.text().strip(),
        )
        value["schedule"] = dataclasses.asdict(
            Schedule(
                frequency=self.frequency.currentData(),
                times=self.times.values(),
                days=self.days_picker.values(),
                weekday=min(self.days_picker.values(), default=0),
                paused=self.paused.isChecked(),
                catch_up_hours=int(catchup),
            )
        )
        folder = self.destination.text().strip()
        if folder:
            filename = (
                KNOWN[self.job.id][2] if self.job.id in KNOWN else self.output_name.text().strip()
            )
            if Path(filename).name != filename or "/" in filename or "\\" in filename:
                raise ValueError("Informe somente o nome do arquivo, sem pastas.")
            if not filename:
                raise ValueError(
                    "Extrator adicional exige um contrato de destino explícito em Configuração completa."
                )
            value["target"] = str(Path(folder) / filename)
        source = script_path(value["script"])
        if not source.is_file() or source.suffix.casefold() != ".py":
            raise ValueError("Selecione um arquivo Python existente.")
        value["trusted_sha256"] = digest(source)
        candidate = to_dict(self.config)
        candidate["routines"] = [
            value if j["id"] == self.job.id else j for j in candidate["routines"]
        ]
        rows = sorted(candidate["routines"], key=lambda j: (j["order"], j["id"]))
        edited = next(j for j in rows if j["id"] == self.job.id)
        rows.remove(edited)
        rows.insert(self.order.currentIndex(), edited)
        for i, routine in enumerate(rows):
            routine["order"] = i
        edited_job = Routine(
            **{
                **value,
                "schedule": copy.deepcopy(self.job.schedule),
                "dependencies": [],
                "retries": {},
            }
        )
        self.calendar_editor.apply(edited_job)
        schedule_extra = dataclasses.asdict(edited_job.schedule)
        for key in ("day_times", "excluded_dates", "paused_until", "catch_up_hours"):
            value["schedule"][key] = schedule_extra[key]
        if catchup != self._advanced_initial.get("catch_up_hours", 24):
            value["schedule"]["catch_up_hours"] = int(catchup)
        value["queue_delay_seconds"] = edited_job.queue_delay_seconds
        for key, editor in [
            ("dependencies", self.dependencies_editor),
            ("retries", self.retry_editor),
        ]:
            if extra.get(key) == self._advanced_initial.get(key):
                data = (
                    self.dependencies_editor.value()
                    if key == "dependencies"
                    else self.retry_editor.value()
                )
                value[key] = (
                    {k: dataclasses.asdict(v) for k, v in data.items()}
                    if isinstance(data, dict)
                    else [dataclasses.asdict(v) for v in data]
                )
        candidate["routines"] = [
            value if j["id"] == self.job.id else j for j in candidate["routines"]
        ]
        result = from_dict(candidate)
        if hasattr(self.config, "_source_revision"):
            result._source_revision = self.config._source_revision  # type: ignore[attr-defined]
        return result

    def accept_values(self) -> None:
        try:
            self.result_config = self.collect_values()
            self.updated = self.result_config.job(self.job.id)
            if self.updated.enabled and not self.job.enabled:
                from .script_versions import check_dependencies

                previous = getattr(self, "dependency_task", None)
                if previous and previous.isRunning():
                    return
                self.dependency_task = Task(lambda: check_dependencies(self.updated), self)

                def checked(value: Any) -> None:
                    if value["missing"]:
                        self.form_error.setText(
                            tr("Bibliotecas ausentes: ") + ", ".join(value["missing"])
                        )
                    else:
                        self.accept()

                self.dependency_task.done.connect(checked)
                self.dependency_task.failed.connect(self.form_error.setText)
                self.dependency_task.start()
            else:
                self.accept()
        except Exception as exc:
            self.form_error.setText(str(exc))
            field_error(self.script, str(exc))


class InstallPage(QWizardPage):
    def __init__(self, title: str, validator: Callable[[], bool] | None = None):
        super().__init__()
        self.setTitle(title)
        self.validator = validator

    def validatePage(self) -> bool:
        return self.validator() if self.validator else True


class InstallWizard(QWizard):
    def __init__(
        self,
        paths: Paths,
        config: Config | None = None,
        parent: QWidget | None = None,
        installer: Installer | None = None,
    ):
        super().__init__(parent)
        self.paths = paths
        self.config = (
            copy.deepcopy(config) if config and config.test_mode else prepare_config(paths, config)
        )
        self.installer = installer or Installer(paths)
        self.installed = False
        self.install_task: Task | None = None
        self.changes: list[str] = []
        self.setWindowTitle("Orquestrador • Instalação de teste e atualização")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setButtonText(QWizard.WizardButton.NextButton, "Avançar")
        self.setButtonText(QWizard.WizardButton.BackButton, "Voltar")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Cancelar")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Abrir aplicativo")
        self.resize(900, 690)
        diagnostic = InstallPage("1. Diagnóstico prévio", self.initial_decision)
        layout = QVBoxLayout(diagnostic)
        current = read_json(self.installer.pointer) if self.installer.pointer.is_file() else {}
        text = f"Versão atual de teste: {current.get('version', 'não instalada')}\nNova versão: {VERSION}\nSistema: {sys.platform}\nRuntime: {'privado no executável' if getattr(sys, 'frozen', False) else 'modo de desenvolvimento'}\n\nEDIÇÃO DE TESTE ISOLADA\nEscolha uma pasta vazia. Aplicativo, perfil do Edge, relatórios, configurações e logs serão mantidos nessa pasta. A instalação original e suas tarefas permanecem preservadas. O versionamento usa snapshots e hashes internos. Falhas internas acionam reversão automática. Login e VPN são testes operacionais separados."
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.operation = QComboBox()
        self.operation.addItems(
            ["Instalar/atualizar", "Reparar a instalação", "Abrir versão instalada"]
            if current
            else ["Instalar"]
        )
        layout.addWidget(self.operation)
        button("Copiar preferências da v1.3.0 para o teste…", self.import_legacy, layout)
        layout.addStretch()
        self.addPage(diagnostic)
        location = InstallPage("2. Pasta exclusiva da versão de teste", self.select_location)
        form = QFormLayout(location)
        suggestion = (
            paths.root
            if (paths.root / "instalacao-teste.json").is_file()
            else paths.root.parent / "Ambiente"
        )
        widget, self.install_root = path_field(str(suggestion))
        form.addRow("Pasta de teste", widget)
        form.addRow(
            QLabel(
                "Use uma pasta vazia ou uma instalação de teste reconhecida. Nenhum arquivo existente de outra instalação será substituído. É possível voltar ou cancelar antes de aplicar."
            )
        )
        self.addPage(location)
        who = InstallPage("3. Usuário, computador e OneDrive")
        form = QFormLayout(who)
        self.who = QLabel(json_view(identity()))
        self.who.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(self.who)
        self.email = QLineEdit(self.config.email)
        form.addRow("E-mail corporativo", self.email)
        self.accounts = QComboBox()
        self.accounts.addItem("Selecione explicitamente um destino ou use o seletor de pastas", "")
        for account in onedrives():
            self.accounts.addItem(
                f"{account['kind']} • {account['account']} • {account['path']}", account["path"]
            )
        form.addRow("Contas detectadas", self.accounts)
        form.addRow(
            QLabel(
                "Contas exibidas para identificação. Os destinos desta edição permanecem na pasta de teste."
            )
        )
        self.addPage(who)
        destinations = InstallPage("4. Destinos dos arquivos", self.validate_destinations)
        self.destination_form = QFormLayout(destinations)
        self.destination_fields: dict[str, QLineEdit] = {}
        self.build_destinations()
        self.addPage(destinations)
        routines = InstallPage("5. Rotinas, dependências e horários próprios")
        layout = QVBoxLayout(routines)
        layout.addWidget(
            QLabel(
                "Selecione uma rotina para editar frequência, dias, horários, ordem, dependências e retries."
            )
        )
        self.routine_table = QTableWidget(0, 4)
        self.routine_table.setHorizontalHeaderLabels(
            ["Rotina", "Habilitada", "Frequência", "Horários próprios"]
        )
        self.routine_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.routine_table.cellDoubleClicked.connect(lambda row, _: self.edit_job(row))
        layout.addWidget(self.routine_table)
        button(
            "Editar rotina selecionada",
            lambda: self.edit_job(self.routine_table.currentRow()),
            layout,
        )
        self.refresh_routines()
        self.schedule_install = QCheckBox(
            "Instalar monitor de teste no Agendador (agendamento inicialmente pausado)"
        )
        self.schedule_install.setChecked(self.config.install_schedules)
        layout.addWidget(self.schedule_install)
        self.addPage(routines)
        dependencies = InstallPage("6. Validação de dependências")
        layout = QVBoxLayout(dependencies)
        self.dependency_text = QPlainTextEdit()
        self.dependency_text.setReadOnly(True)
        layout.addWidget(self.dependency_text)
        self.dependency_text.setPlainText(
            json_view(
                {
                    name: importlib.metadata.version(name)
                    for name in ("PySide6", "selenium", "pandas", "openpyxl", "requests")
                }
            )
        )
        layout.addWidget(
            QLabel(
                "O health check de instalação valida somente recursos internos. Antes da primeira extração, use Diagnóstico para verificar Edge/assinatura e Testar login para renovar SSO/MFA."
            )
        )
        self.addPage(dependencies)
        review = InstallPage("7. Revisão das alterações", self.review_valid)
        layout = QVBoxLayout(review)
        self.review_text = QPlainTextEdit()
        self.review_text.setReadOnly(True)
        layout.addWidget(self.review_text)
        self.approve = QCheckBox(
            "Aplicar somente na pasta de teste e criar snapshots internos verificáveis"
        )
        layout.addWidget(self.approve)
        self.addPage(review)
        install = InstallPage("8. Instalação, atualização e verificação final")
        layout = QVBoxLayout(install)
        self.install_text = QPlainTextEdit()
        self.install_text.setReadOnly(True)
        self.install_bar = QProgressBar()
        self.install_bar.setRange(0, 0)
        layout.addWidget(self.install_bar)
        layout.addWidget(self.install_text)
        self.addPage(install)
        self.currentIdChanged.connect(self.page_changed)

    def select_location(self) -> bool:
        try:
            selected = check_location(Path(self.install_root.text().strip()))
            existing = selected.root
            while not existing.exists() and existing != existing.parent:
                existing = existing.parent
            check_directory(existing, min_free=500_000_000)
            if selected.root != self.paths.root:
                if selected.config.is_file():
                    self.config = load(selected)
                    from .sandbox import validate_isolation

                    validate_isolation(selected, self.config)
                else:
                    self.config = prepare_config(selected, self.config)
                self.paths = selected
                self.installer = Installer(selected)
                self.email.setText(self.config.email)
                self.schedule_install.setChecked(self.config.install_schedules)
                self.build_destinations()
                self.refresh_routines()
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Pasta de teste", str(exc))
            return False

    def initial_decision(self) -> bool:
        if self.operation.currentIndex() == 2:
            current = read_json(self.installer.pointer)
            spawn([current["executable"], "--data-root", str(self.paths.root)])
            self.reject()
            return False
        return True

    def build_destinations(self) -> None:
        while self.destination_form.count():
            item = self.destination_form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.destination_fields.clear()
        for job in self.config.routines:
            widget, field = path_field(str(Path(job.target).parent) if job.target else "")
            self.destination_fields[job.id] = field
            self.destination_form.addRow(job.label, widget)
        self.destination_form.addRow(
            QLabel(
                "A gravação é local. A sincronização do OneDrive/SharePoint não é confirmada pelo aplicativo."
            )
        )

    def import_legacy(self) -> None:
        filename = QFileDialog.getOpenFileName(
            self, "Configuração da instalação existente", "", "JSON (*.json)"
        )[0]
        if not filename:
            return
        try:
            candidate, self.changes = migrate(Path(filename), self.paths, source_root())
            self.config = prepare_config(self.paths, candidate)
            self.changes.append(
                "Destinos, perfil, logs e downloads redirecionados ao teste; tarefas e estado de produção preservados."
            )
            self.email.setText(self.config.email)
            self.build_destinations()
            self.refresh_routines()
            show_detail(self, "Prévia da migração", self.changes)
        except Exception as exc:
            QMessageBox.warning(self, "Migração não aplicada", str(exc))

    def apply_base(self) -> None:
        folder = self.accounts.currentData()
        if not folder:
            QMessageBox.information(
                self, "Destino", "Selecione uma conta ou escolha cada pasta na próxima etapa."
            )
            return
        for job in self.config.routines:
            subfolder = KNOWN.get(job.id, ("", job.id, ""))[1]
            self.destination_fields[job.id].setText(str(Path(folder) / subfolder))

    def validate_destinations(self) -> bool:
        try:
            for job in self.config.routines:
                text = self.destination_fields[job.id].text().strip()
                if not job.enabled and not text:
                    continue
                if not text or not Path(text).is_absolute():
                    raise ValueError(f"Escolha a pasta de destino de {job.label}.")
                candidate = Path(text)
                confined(self.paths, candidate, f"Pasta de {job.label}")
                existing = candidate
                while not existing.exists() and existing != existing.parent:
                    existing = existing.parent
                check_directory(existing)
                filename = KNOWN.get(job.id, ("", "", Path(job.target).name))[2]
                job.target = str(candidate / filename) if filename else job.target
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Destino inválido", str(exc))
            return False

    def refresh_routines(self) -> None:
        self.routine_table.setRowCount(len(self.config.routines))
        for row, job in enumerate(self.config.routines):
            for column, value in enumerate(
                (
                    job.label,
                    "Sim" if job.enabled else "Não",
                    job.schedule.frequency,
                    ", ".join(job.schedule.times),
                )
            ):
                self.routine_table.setItem(row, column, QTableWidgetItem(value))

    def edit_job(self, row: int) -> None:
        if row < 0:
            return
        dialog = RoutineDialog(self.config, self.config.routines[row], self)
        if dialog.exec():
            self.config.routines[row] = dialog.updated
            self.refresh_routines()

    def review_valid(self) -> bool:
        try:
            if not self.approve.isChecked():
                raise ValueError("Revise e marque a aplicação das alterações para continuar.")
            self.config.email = self.email.text().strip()
            self.config.install_root = str(self.paths.root / "app")
            self.config.install_schedules = self.schedule_install.isChecked()
            if self.config.email and "@" not in self.config.email:
                raise ValueError("Informe um e-mail válido ou deixe vazio para testes locais.")
            validate(self.config)
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Revisão", str(exc))
            return False

    def page_changed(self, page: int) -> None:
        if page == 6:
            self.config.email = self.email.text().strip()
            self.config.install_root = str(self.paths.root / "app")
            self.config.install_schedules = self.schedule_install.isChecked()
            self.review_text.setPlainText(
                json_view(
                    {
                        "version": VERSION,
                        "pasta_exclusiva_do_teste": str(self.paths.root),
                        "versionamento": "interno: snapshots e SHA-256; sem Git",
                        "changes": self.changes,
                        "configuration": to_dict(self.config),
                    }
                )
            )
        if page == 7:
            self.button(QWizard.WizardButton.BackButton).setEnabled(False)
            self.button(QWizard.WizardButton.CancelButton).setEnabled(False)
            self.button(QWizard.WizardButton.FinishButton).setEnabled(False)
            task = Task(
                lambda: self.installer.install(
                    Path(sys.executable),
                    self.config,
                    progress=lambda message: task.progress.emit(message),
                ),
                self,
            )
            self.install_task = task
            task.progress.connect(self.install_text.appendPlainText)
            task.done.connect(self.install_done)
            task.failed.connect(self.install_failed)
            task.start()

    def install_done(self, result: Any) -> None:
        self.installed_executable = Path(result)
        mark(self.paths)
        remember(self.paths)
        self.installed = True
        self.install_bar.setRange(0, 1)
        self.install_bar.setValue(1)
        self.button(QWizard.WizardButton.FinishButton).setEnabled(True)
        self.install_text.appendPlainText(f"Versão instalada: {result}")

    def install_failed(self, error: str) -> None:
        self.install_bar.setRange(0, 1)
        self.install_bar.setValue(0)
        self.install_text.appendPlainText(
            error
            + "\nConsulte acima o resultado da reversão. A conversão não será marcada como instalada."
        )
        self.button(QWizard.WizardButton.CancelButton).setEnabled(True)

    def reject(self) -> None:
        if self.install_task and self.install_task.isRunning():
            return
        super().reject()

    def accept(self) -> None:
        if self.installed:
            super().accept()


class MainWindow(QMainWindow):
    def __init__(self, paths: Paths, *, observe: bool = True):
        super().__init__()
        self.paths = paths
        self.config = load(paths)
        install_translation(QApplication.instance(), self.config.language)
        self.store = Store(paths.database, initialize=False)
        self.engine = Engine(paths, self.config, store=self.store)
        self.observer = Observer(paths)
        self.read_task: Task | None = None
        self._refresh_pending = False
        self._snapshot_generation = 0
        self._last_rows: list[dict[str, Any]] = []
        self._last_monitor: dict[str, Any] = {}
        self._history_page = 0
        self._history_sort = "started"
        self._history_descending = True
        self._history_committed: dict[str, Any] = {}
        self._backup_page = 0
        self.setWindowIcon(icon())
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app)
        self.task: Task | None = None
        self.update_task: Task | None = None
        self.exit_requested = False
        self._log_stamp: tuple[str, int, int] | None = None
        self._last_stage = ""
        self.setWindowTitle(
            f"CAIO • Teste {VERSION}" if self.config.test_mode else f"CAIO • {VERSION}"
        )
        self.resize(1400, 940)
        self.setMinimumSize(980, 720)
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.activity = QWidget()
        self.activity.setObjectName("activity")
        self.activity_layout = QVBoxLayout(self.activity)
        self.activity_layout.setContentsMargins(16, 12, 16, 12)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.workspace_splitter = splitter
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.activity)
        splitter.setSizes([660, 170])
        shell = QWidget()
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        navigation = QFrame()
        navigation.setObjectName("navigation")
        navigation.setFixedWidth(204)
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(12, 24, 12, 20)
        navigation_layout.setSpacing(18)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(icon().pixmap(44, 44))
        logo.setFixedSize(44, 44)
        brand.addWidget(logo)
        name = QLabel("CAIO")
        name.setProperty("role", "brand")
        brand.addWidget(name)
        brand.addStretch()
        navigation_layout.addLayout(brand)
        navigation_layout.addWidget(QLabel(tr("Central de automações")))
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigationList")
        self.navigation.setAccessibleName(tr("Navegação principal"))
        self.navigation.setWordWrap(True)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        navigation_layout.addWidget(self.navigation, 1)
        navigation_layout.addWidget(QLabel(tr("Versão de teste") + f"\n{VERSION}"))
        shell_layout.addWidget(navigation)
        workspace = QWidget()
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(20, 16, 20, 0)
        workspace_layout.setSpacing(12)
        self.page_title = QLabel()
        self.page_title.setProperty("role", "title")
        self.page_description = explain("")
        workspace_layout.addWidget(self.page_title)
        workspace_layout.addWidget(self.page_description)
        workspace_layout.addWidget(splitter, 1)
        shell_layout.addWidget(workspace, 1)
        self.setCentralWidget(shell)
        self.build_panel()
        self.build_routines()
        self.build_settings()
        self.build_history()
        self.build_maintenance()
        from .dev_gui import DevPanel

        self.dev_panel = DevPanel(paths, self)
        self.tabs.addTab(self.dev_panel, "Dev • Internos")
        self.page_descriptions = (
            "Acompanhe as extrações e escolha o que executar.",
            "Organize scripts, frequências e horários de cada rotina.",
            "Ajuste as preferências e os caminhos desta instalação.",
            "Consulte resultados e investigue o histórico das execuções.",
            "Verifique conexões, tarefas e backups antes de intervir.",
            "Inspecione os componentes e as evidências desta instalação.",
        )
        for index in range(self.tabs.count()):
            item = QListWidgetItem(tr(self.tabs.tabText(index)))
            item.setSizeHint(QSize(174, 60))
            self.navigation.addItem(item)
        self.navigation.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.show_page)
        self.navigation.setCurrentRow(0)
        self.show_page(0)
        if self.config.test_mode:
            self.installation_banner = SingleLineLabel(f"{tr('TESTE ISOLADO')} • {self.paths.root}")
            self.statusBar().addPermanentWidget(self.installation_banner, 1)
            self.statusBar().setMaximumHeight(self.installation_banner.height() + 6)
        self.tray = QSystemTrayIcon(icon(), self)
        self.tray.setToolTip("CAIO • Orquestrador")
        menu = QMenu()
        show = QAction("Abrir Orquestrador", self)
        show.triggered.connect(self.show_application)
        menu.addAction(show)
        quit_action = QAction("Sair da interface", self)
        quit_action.triggered.connect(self.explicit_exit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.show_application()
            if reason
            in (
                QSystemTrayIcon.ActivationReason.Trigger,
                QSystemTrayIcon.ActivationReason.DoubleClick,
            )
            else None
        )
        self.last_notification_run = ""
        self.vpn_notices: list[VpnNotice] = []
        self.tray.messageClicked.connect(self.notification_detail)
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        if observe:
            self.timer.start(2000)
        for table in self.findChildren(QTableWidget):
            configure_table(table)
        for label in self.findChildren(QLabel):
            if not label.property("singleLine"):
                label.setWordWrap(True)
        self.selection_actions()
        self.restore_window_preferences()
        if observe:
            self.refresh()
        translate_tree(self)
        from .windows_identity import set_process_identity, set_window_identity

        set_process_identity(paths)
        if isinstance(app, QApplication) and app.platformName() == "windows":
            set_window_identity(self, paths)

    def show_page(self, index: int) -> None:
        if getattr(self, "_navigation_guard", False):
            return
        if (
            getattr(self, "_previous_page", 0) == 2
            and index != 2
            and not self.confirm_settings_navigation()
        ):
            self._navigation_guard = True
            self.tabs.setCurrentIndex(2)
            self.navigation.setCurrentRow(2)
            self._navigation_guard = False
            return
        self._previous_page = index
        self.navigation.setCurrentRow(index)
        self.page_title.setText(tr(self.tabs.tabText(index)))
        self.page_description.setText(tr(self.page_descriptions[index]))
        product = f"CAIO • Teste {VERSION}" if self.config.test_mode else f"CAIO • {VERSION}"
        self.setWindowTitle(f"{tr(self.tabs.tabText(index))} — {product}")
        if index == 3:
            self.refresh_history()
        elif index == 4:
            self.refresh_backups()

    def add_scroll_page(self, page: QWidget, title: str) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)

    def build_panel(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(12)
        summary = QHBoxLayout()
        self.summary_values: list[QLabel] = []
        for text in ("Rotinas habilitadas", "Agendamento", "Estado do monitor"):
            card = QFrame()
            card.setProperty("role", "summary")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 12, 16, 12)
            value = QLabel()
            value.setProperty("role", "section")
            card_layout.addWidget(explain(text))
            card_layout.addWidget(value)
            self.summary_values.append(value)
            summary.addWidget(card, 1)
        layout.addLayout(summary)
        self.timezone = QLabel()
        self.timezone.setProperty("role", "muted")
        layout.addWidget(self.timezone)
        self.panel = QTableWidget(0, 11)
        self.panel.setHorizontalHeaderLabels(
            [
                "Rotina",
                "Habilitada",
                "Estado/etapa",
                "Última tentativa",
                "Último sucesso",
                "Dados",
                "Próxima elegibilidade",
                "Duração (s)",
                "Tentativas",
                "Pendência/ação",
                "Execução",
            ]
        )
        self.panel.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.panel.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.panel.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.panel)
        actions = QHBoxLayout()
        self.batch_group = QGroupBox(tr("Lote completo"))
        batch_actions = FlowLayout(self.batch_group)
        self.batch_button = button(
            "Executar todas", lambda: self.start_run(), batch_actions, emphasis="solid"
        )
        button("Simular todas", lambda: self.start_run(simulate=True), batch_actions)
        actions.addWidget(self.batch_group)
        self.selection_group = QGroupBox(tr("Escolha uma rotina"))
        selected_actions = FlowLayout(self.selection_group)
        self.run_button = button(
            "Executar rotina",
            lambda: self.start_run(selected=True),
            selected_actions,
            emphasis="solid",
        )
        self.force_button = button(
            "Forçar rotina",
            lambda: self.start_run(selected=True, force=True),
            selected_actions,
            intent="warning",
        )
        self.simulate_button = button(
            "Simular", lambda: self.start_run(selected=True, simulate=True), selected_actions
        )
        self.login_button = button(
            "Testar login", lambda: self.start_run(selected=True, login=True), selected_actions
        )
        self.recommended_button = button(
            "Ver detalhe da execução", self.recommended_action, selected_actions
        )
        actions.addWidget(self.selection_group)
        self.panel.itemSelectionChanged.connect(self.selection_actions)
        self.panel.setAlternatingRowColors(True)
        layout.addLayout(actions)
        controls = FlowLayout()
        self.pause_schedule = button("Pausar/retomar agendamento", self.toggle_schedule, controls)
        operations = QPushButton(tr("Controlar execução"))
        operation_menu = QMenu(operations)
        for text, action in (
            ("Pausar execução", lambda: self.control("pause")),
            ("Retomar execução", lambda: self.control("resume")),
            ("Cancelar rotina", lambda: self.control("cancel")),
            ("Cancelar lote", lambda: self.control("cancel", batch=True)),
        ):
            item = operation_menu.addAction(tr(text))
            item.triggered.connect(action)
        operations.setMenu(operation_menu)
        controls.addWidget(operations)
        button("Pausar até…", self.pause_until_dialog, controls)
        button("Executar somente pendentes…", self.run_pending, controls)
        layout.addLayout(controls)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(False)
        progress_policy = self.progress.sizePolicy()
        progress_policy.setRetainSizeWhenHidden(True)
        self.progress.setSizePolicy(progress_policy)
        self.activity_layout.addWidget(self.progress)
        self.status_label = QLabel("Pronto")
        self.status_label.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText(
            tr("Atividade do aplicativo: operações, avisos e logs aparecem aqui.")
        )
        self.log.setMinimumHeight(70)
        self.log.setAccessibleName(tr("Atividade da instalação"))
        self.log.document().setMaximumBlockCount(800)
        self.activity_layout.addWidget(explain("Atividade da instalação"))
        log_controls = QHBoxLayout()
        self.follow_log = QCheckBox(tr("Acompanhar novas linhas"))
        self.follow_log.setChecked(True)
        log_controls.addWidget(self.follow_log)
        self.monitor_status_label = QLabel()
        self.monitor_status_label.setWordWrap(True)
        log_controls.addWidget(self.monitor_status_label, 1)
        self.activity_layout.addLayout(log_controls)
        self.activity_layout.addWidget(self.log, 1)
        self.activity_layout.addWidget(self.status_label)
        self.tabs.addTab(page, "Painel")

    def build_routines(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        catalog = FlowLayout()
        self.catalog_search = QLineEdit()
        self.catalog_search.setPlaceholderText(tr("Buscar nome, origem ou categoria"))
        self.catalog_search.setClearButtonEnabled(True)
        self.catalog_enabled = QComboBox()
        for label, value in [("Todas", None), ("Habilitadas", True), ("Desabilitadas", False)]:
            self.catalog_enabled.addItem(tr(label), value)
        self.catalog_browser = QComboBox()
        for label, value in [
            ("Qualquer navegador", None),
            ("Usa navegador", True),
            ("Sem navegador", False),
        ]:
            self.catalog_browser.addItem(tr(label), value)
        for widget in (self.catalog_search, self.catalog_enabled, self.catalog_browser):
            catalog.addWidget(widget)
        layout.addLayout(catalog)
        self.catalog_search.textChanged.connect(self.filter_catalog)
        self.catalog_enabled.currentIndexChanged.connect(self.filter_catalog)
        self.catalog_browser.currentIndexChanged.connect(self.filter_catalog)
        self.routines = QTableWidget(0, 6)
        self.routines.setHorizontalHeaderLabels(
            ["Rotina", "Frequência", "Horários próprios", "Dias", "Ordem", "Origem"]
        )
        self.routines.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.routines.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routines.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.routines.setAlternatingRowColors(True)
        self.routines.cellDoubleClicked.connect(lambda row, _: self.edit_routine(row))
        layout.addWidget(self.routines)
        actions = FlowLayout()
        button("Editar selecionada", lambda: self.edit_routine(self.routines.currentRow()), actions)
        button("Descobrir extratores…", self.discover_jobs, actions)
        button("Cadastrar script…", self.register_script, actions, emphasis="solid")
        button("Versões do script…", self.script_history, actions)
        button("Excluir rotina…", self.delete_routine, actions, intent="danger")
        button("Publicar arquivo local…", self.local_file, actions)
        button("Importar pasta de script…", self.import_script_folder, actions)
        button("Verificar bibliotecas", self.check_script_libraries, actions)
        button("Lixeira de cadastros", self.routine_trash, actions)
        button("Exportar rotina…", self.export_selected_routine, actions)
        button("Testar versão candidata…", self.candidate_script, actions)
        layout.addLayout(actions)
        layout.addWidget(
            QLabel(
                "Adicionar scripts: selecione um arquivo .py, revise os argumentos e habilite a rotina. Versões são guardadas automaticamente. Publicar arquivo local valida e copia um Excel já baixado (Eventos: mescla o histórico), sem abrir o navegador."
            )
        )
        self.queue_delay = QSpinBox()
        self.queue_delay.setRange(0, 3600)
        self.queue_delay.setSuffix(" s")
        self.queue_delay.setValue(self.config.queue_delay_seconds)
        delay_form = QFormLayout()
        delay_form.addRow("Espera entre rotinas agendadas na fila", self.queue_delay)
        button("Salvar intervalo", self.save_delay, delay_form)
        layout.addLayout(delay_form)
        layout.addWidget(
            explain(
                "O intervalo começa quando a rotina anterior termina. Não há execuções simultâneas no perfil compartilhado."
            )
        )
        self.tabs.addTab(page, "Rotinas e agendamentos")

    def build_settings(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        languages = QHBoxLayout()
        languages.addWidget(QLabel("Idioma / Language / Idioma"))
        self.language = QComboBox()
        for label, code in (("Português (Brasil)", "pt-BR"), ("English", "en"), ("Español", "es")):
            self.language.addItem(label, code)
        self.language.setCurrentIndex(self.language.findData(self.config.language))
        languages.addWidget(self.language)
        button("Aplicar idioma", self.change_language, languages)
        layout.addLayout(languages)
        self.settings_tabs = QTabWidget()
        self.common_scroll = QScrollArea()
        self.common_scroll.setWidgetResizable(True)
        self.common_settings = SettingsEditor(self.config, path_field)
        self.common_scroll.setWidget(self.common_settings)
        self.settings_tabs.addTab(self.common_scroll, tr("Preferências"))
        self.settings_json = QPlainTextEdit(json_view(to_dict(self.config)))
        self.settings_json.setMinimumHeight(240)
        self.settings_json.setAccessibleName(tr("Configuração completa"))
        self.settings_tabs.addTab(self.settings_json, tr("Avançado"))
        layout.addWidget(self.settings_tabs)
        self.settings_error = explain("")
        self.settings_error.setProperty("severity", "error")
        layout.addWidget(self.settings_error)
        self._settings_saved_text = self.settings_json.toPlainText()
        self._common_baseline = to_dict(self.common_settings.value(validating=False))
        self._edit_revision = getattr(self.config, "_source_revision", digest(self.paths.config))
        self._settings_mode = 0
        self._settings_sync = False
        self.settings_tabs.currentChanged.connect(self.sync_settings_mode)
        actions = FlowLayout()
        button("Validar e salvar", self.save_settings, actions, emphasis="solid")
        button("Exportar preferências sem segredos…", self.export_settings, actions)
        button("Importar com prévia…", self.import_settings, actions)
        button("Atualização…", self.installation, actions)
        layout.addLayout(actions)
        paths_form = QFormLayout()
        self.path_key = QComboBox()
        for key in ("profile", "driver", "downloads", "logs", "install_root"):
            self.path_key.addItem(key)
        paths_form.addRow("Selecionar caminho", self.path_key)
        layout.addWidget(
            explain(
                "O EdgeDriver é localizado e reparado automaticamente. Ao escolher um driver externo, ele será validado e copiado para o cache gerenciado; o arquivo original será preservado."
            )
        )
        button("Escolher e aplicar caminho…", self.choose_setting_path, paths_form)
        layout.addLayout(paths_form)
        layout.addWidget(
            QLabel(
                "Console oculto refere-se a subprocessos internos. Minimizar mantém a interface. Headless controla somente a janela do navegador. SSO/MFA não é convertido em serviço Windows."
            )
        )
        self.add_scroll_page(page, "Configurações")

    def build_history(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        filters = FlowLayout()
        self.filter_job = QComboBox()
        self.filter_job.setEditable(True)
        self.filter_job.addItem(tr("Todos"), "")
        for job in self.config.routines:
            self.filter_job.addItem(job.label, job.id)
        self.filter_job.setAccessibleName(tr("Filtrar por rotina"))
        self.filter_status = QComboBox()
        self.filter_status.addItem(tr("Todos"), "")
        for code, label in STATUS.items():
            self.filter_status.addItem(tr(label), code)
        self.filter_category = QComboBox()
        self.filter_category.addItem(tr("Todas as categorias"), "")
        from .editors import CATEGORY_LABELS

        for code, label in CATEGORY_LABELS.items():
            self.filter_category.addItem(tr(label), code)
        self.filter_batch = QLineEdit()
        self.filter_batch.setPlaceholderText(tr("Lote"))
        self.filter_text = QLineEdit()
        self.filter_text.setPlaceholderText(tr("Texto no histórico"))
        self.filter_start = QLineEdit()
        self.filter_start.setPlaceholderText(tr("De: AAAA-MM-DD"))
        self.filter_end = QLineEdit()
        self.filter_end.setPlaceholderText(tr("Até: AAAA-MM-DD"))
        for field in (self.filter_batch, self.filter_text, self.filter_start, self.filter_end):
            field.setAccessibleName(field.placeholderText())
            field.setClearButtonEnabled(True)
        for widget in (
            self.filter_job,
            self.filter_status,
            self.filter_category,
            self.filter_batch,
            self.filter_text,
            self.filter_start,
            self.filter_end,
        ):
            filters.addWidget(widget)
        button("Filtrar", self.refresh_history, filters, emphasis="solid")
        button("Limpar filtros", self.clear_history_filters, filters)
        button("Exportar diagnóstico sanitizado…", self.export_history, filters)
        button("Central de notificações", self.notification_center, filters)
        button("Pacote de suporte com prévia", self.support_package, filters)
        layout.addLayout(filters)
        self.history_model = HistoryModel(self)
        self.history = QTableView()
        self.history.setModel(self.history_model)
        configure_table(self.history)
        self.history.setAccessibleName(tr("Histórico de execuções"))
        self.history.doubleClicked.connect(lambda index: self.history_detail(index.row()))
        self.history.horizontalHeader().sectionClicked.connect(self.sort_history)
        self.history.horizontalHeader().setSortIndicatorShown(True)
        layout.addWidget(self.history)
        paging = FlowLayout()
        self.history_previous = button(
            "Página anterior", lambda: self.history_change_page(-1), paging
        )
        self.history_next = button("Próxima página", lambda: self.history_change_page(1), paging)
        self.history_size = QComboBox()
        for size in (25, 50, 100):
            self.history_size.addItem(str(size), size)
        self.history_size.setCurrentIndex(1)
        paging.addWidget(self.history_size)
        self.history_total = QLabel()
        paging.addWidget(self.history_total)
        self.history_size.currentIndexChanged.connect(self.refresh_history)
        layout.addLayout(paging)
        self.history_empty = explain(
            "Nenhuma execução registrada. Execute uma rotina no Painel para acompanhar o resultado aqui."
        )
        layout.addWidget(self.history_empty)
        self.tabs.addTab(page, "Histórico e logs")
        self._history_committed = self.history_query()

    def history_query(self) -> dict[str, Any]:
        label = self.filter_job.currentText().strip()
        index = self.filter_job.findText(label)
        job = self.filter_job.itemData(index) if index >= 0 else label

        def date(field: QLineEdit, end: bool = False) -> str:
            value = field.text().strip()
            if not value:
                return ""
            day = dt.date.fromisoformat(value)
            if end:
                day += dt.timedelta(days=1)
            return (
                dt.datetime.combine(day, dt.time())
                .astimezone()
                .astimezone(dt.timezone.utc)
                .isoformat()
            )

        return {
            "job": job or "",
            "status": self.filter_status.currentData() or "",
            "category": self.filter_category.currentData() or "",
            "batch": self.filter_batch.text().strip(),
            "text": self.filter_text.text().strip(),
            "start": date(self.filter_start),
            "end": date(self.filter_end, True),
            "page": self._history_page,
            "size": self.history_size.currentData(),
            "sort": self._history_sort,
            "descending": self._history_descending,
        }

    def sort_history(self, column: int) -> None:
        key = self.history_model.columns[column]
        self._history_descending = (
            not self._history_descending if self._history_sort == key else True
        )
        self._history_sort = key
        self.history.horizontalHeader().setSortIndicator(
            column,
            Qt.SortOrder.DescendingOrder
            if self._history_descending
            else Qt.SortOrder.AscendingOrder,
        )
        self.refresh_history()

    def history_change_page(self, offset: int) -> None:
        self._history_page = max(0, self._history_page + offset)
        self._history_committed["page"] = self._history_page
        self.refresh()

    def build_maintenance(self) -> None:
        page = QWidget()
        root_layout = QVBoxLayout(page)

        def section(title: str) -> QVBoxLayout:
            group = QGroupBox(tr(title))
            root_layout.addWidget(group)
            return QVBoxLayout(group)

        layout = section("Diagnóstico")
        targets = QHBoxLayout()
        targets.addWidget(QLabel(tr("Destino do teste de conectividade/VPN")))
        self.connectivity_job = QComboBox()
        for job in self.config.routines:
            if job.requires_browser:
                self.connectivity_job.addItem(job.label, job.id)
        index = self.connectivity_job.findData("kwms_alocacoes_tool_edge")
        if index >= 0:
            self.connectivity_job.setCurrentIndex(index)
        targets.addWidget(self.connectivity_job)
        layout.addLayout(targets)
        actions = FlowLayout()
        button(
            "Diagnosticar EdgeDriver",
            lambda: self.driver_operation(False),
            actions,
        )
        button(
            "Reparar EdgeDriver",
            lambda: self.driver_operation(True),
            actions,
        )
        button("Testar conectividade", self.connectivity, actions)
        layout.addLayout(actions)
        layout = section("Agendador e monitor")
        tasks = FlowLayout()
        button("Conferir tarefas", self.task_diff, tasks)
        button("Instalar/atualizar tarefa", self.install_task, tasks)
        button(
            "Remover tarefa própria",
            lambda: self.manage_task(False),
            tasks,
            intent="danger",
        )
        layout.addLayout(tasks)
        self.tasks_view = QTableWidget(0, 4)
        self.tasks_view.setHorizontalHeaderLabels(["Campo", "No Windows", "Esperado", "Resultado"])
        self.tasks_view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tasks_view.setMaximumHeight(220)
        self.tasks_view.setMinimumHeight(150)
        layout.addWidget(self.tasks_view)
        layout.addWidget(
            explain(
                "Conferir tarefas compara o monitor registrado com esta instalação. A lista abaixo contém backups de relatórios, não resultados do diagnóstico."
            )
        )
        layout.addWidget(
            QLabel(
                "Backups de relatórios • restaurar preserva a versão atual e não registra nova extração."
            )
        )
        layout = section("Backups de relatórios")
        self.backups = QTableWidget(0, 5)
        self.backups.setHorizontalHeaderLabels(["Data", "Arquivo", "Tamanho", "SHA-256", "Versão"])
        self.backups.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.backups)
        self.backups.setMinimumHeight(160)
        self.backup_empty = explain(
            "Nenhum backup de relatório ainda. A lista é preenchida após a primeira substituição de um arquivo válido."
        )
        layout.addWidget(self.backup_empty)
        paging = FlowLayout()
        button("Página anterior", lambda: self.backup_change_page(-1), paging)
        button("Próxima página", lambda: self.backup_change_page(1), paging)
        self.backup_total = QLabel()
        paging.addWidget(self.backup_total)
        layout.addLayout(paging)
        controls = FlowLayout()
        button("Atualizar lista", self.refresh_backups, controls)
        button("Validar selecionado", self.validate_backup, controls)
        button("Restaurar selecionado", self.restore_backup, controls)
        layout.addLayout(controls)
        layout = section("Versões do aplicativo e armazenamento")
        controls = FlowLayout()
        button("Backup do aplicativo", self.backup_application, controls)
        button("Ocupação e limpeza…", self.storage_review, controls)
        button(
            "Resultado da recuperação",
            lambda: self.read_details(
                tr("Resultado da recuperação"),
                lambda: read_json(self.paths.root / "state/recovery-report.json")
                if (self.paths.root / "state/recovery-report.json").is_file()
                else {"result": tr("Nenhuma recuperação registrada.")},
            ),
            controls,
        )
        button("Arquivos rejeitados…", self.rejected_files, controls)
        button("Reverter atualização…", self.rollback_application, controls)
        layout.addLayout(controls)
        button(
            "Desinstalar CAIO e preservar dados…",
            self.uninstall,
            layout,
            intent="danger",
        )
        self.add_scroll_page(page, "Diagnóstico e manutenção")

    def read_details(
        self,
        title: str,
        loader: Callable[[], Any],
        *,
        commit: Callable[[Any], Any] | None = None,
        action: str = "Aplicar alterações",
        present: Callable[[Any], Any] | None = None,
    ) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        content = QPlainTextEdit(tr("Carregando…"))
        content.setReadOnly(True)
        layout.addWidget(content)
        actions = FlowLayout()
        layout.addLayout(actions)
        button("Fechar", dialog.reject, actions)
        values: list[Any] = []
        apply = button(action, lambda: apply_value(), actions, emphasis="solid") if commit else None
        if apply:
            apply.setEnabled(False)

        def loaded(value: Any) -> None:
            values.append(value)
            content.setPlainText(friendly_details(present(value) if present else value))
            if apply:
                apply.setEnabled(True)

        def apply_value() -> None:
            if not commit or not values or (self.task and self.task.isRunning()):
                return
            if apply:
                apply.setEnabled(False)
            task = Task(lambda: commit(values[-1]), self)
            self.task = task
            self.progress.setRange(0, 0)
            self.progress.show()

            def done(value: Any) -> None:
                self.append_log(json_view(value))
                self.set_status(tr("Operação concluída."), "success")
                dialog.accept()
                self.refresh()

            def failed(text: str) -> None:
                content.appendPlainText("\n" + text)
                self.set_status(text, "error")
                if apply:
                    apply.setEnabled(True)

            task.done.connect(done)
            task.failed.connect(failed)
            task.finished.connect(self.progress.hide)
            task.start()

        task = Task(loader, self)
        task.done.connect(loaded)
        task.failed.connect(content.setPlainText)
        task.finished.connect(task.deleteLater)
        task.start()
        dialog.show()

    def render_monitor(self, value: dict[str, Any]) -> None:
        from .i18n import display_value

        labels = {
            "configured": "Configurado",
            "installed": "Tarefa instalada",
            "active": "Processo ativo",
            "paused": "Pausado",
            "no_communication": "Sem comunicação",
            "disabled": "Não configurado",
            "stopped": "Monitor encerrado",
        }
        state = tr(labels[value["state"]])
        self.summary_values[2].setText(state)
        self.summary_values[1].setText(tr("Pausado" if value["paused"] else "Ativo"))
        installed = (
            tr("Sim" if value["installed"] else "Não")
            if value["installed"] is not None
            else tr("Não verificado")
        )
        self.monitor_status_label.setText(
            tr("Monitor")
            + ": "
            + state
            + " · "
            + tr("Tarefa instalada")
            + ": "
            + installed
            + " · "
            + tr("Última comunicação")
            + ": "
            + (display_value(value["last_seen"]) if value["last_seen"] else tr("Nunca"))
        )
        if value["unexpected_stop"] or (value["active"] and not value["communicating"]):
            self.set_status(
                tr(
                    "Monitor sem comunicação. Confira a tarefa e os processos em Diagnóstico; nenhuma rotina será marcada como concluída."
                ),
                "warning",
            )

    def filter_catalog(self) -> None:
        if not hasattr(self, "routines"):
            return
        query = self.catalog_search.text().casefold().strip()
        enabled = self.catalog_enabled.currentData()
        browser = self.catalog_browser.currentData()
        for index, job in enumerate(self.config.routines):
            text = " ".join((job.label, job.origin, job.category)).casefold()
            self.routines.setRowHidden(
                index,
                bool(
                    (query and query not in text)
                    or (enabled is not None and job.enabled != enabled)
                    or (browser is not None and job.requires_browser != browser)
                ),
            )

    def sync_settings_mode(self, index: int) -> None:
        if self._settings_sync:
            return
        try:
            if (
                index == 1
                and to_dict(self.common_settings.value(validating=False)) != self._common_baseline
            ):
                self.settings_json.setPlainText(json_view(to_dict(self.common_settings.value())))
            elif index == 0 and self.settings_json.toPlainText() != self._settings_saved_text:
                value = from_dict(json.loads(self.settings_json.toPlainText()))
                self.common_settings = SettingsEditor(value, path_field)
                self.common_scroll.setWidget(self.common_settings)
            self._settings_mode = index
        except Exception as exc:
            self.settings_error.setText(str(exc))
            self._settings_sync = True
            self.settings_tabs.setCurrentIndex(self._settings_mode)
            self._settings_sync = False

    def backup_change_page(self, offset: int) -> None:
        self._backup_page = max(0, self._backup_page + offset)
        self.apply_backups(getattr(self, "_backup_records", []))

    def recommended_action(self) -> None:
        try:
            name = self.selected_id()
            record = next(r for r in self._last_rows if r["id"] == name)
            category = record["last"].get("category", "")
            if category == "driver":
                self.driver_operation(True)
            elif category == "authentication":
                self.start_run(selected=True, login=True)
            elif category in {"vpn", "internet", "server"}:
                self.connectivity_job.setCurrentIndex(self.connectivity_job.findData(name))
                self.connectivity()
            elif category in {"locked_file", "invalid_file"}:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                target = Path(self.config.job(name).target).parent
                if not target.is_dir():
                    raise ValueError(tr("Pasta de destino indisponível."))
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            else:
                run = record["last"].get("id")
                self.read_details(
                    tr("Detalhe da execução"),
                    lambda: {
                        "run": record["last"],
                        "events": self.store.details(run) if run else [],
                    },
                )
        except Exception as exc:
            self.set_status(str(exc), "error")

    def pause_until_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Pausar até…"))
        form = QFormLayout(dialog)
        field = QLineEdit(
            self.config.paused_until
            or (local_now() + dt.timedelta(hours=1)).isoformat(timespec="minutes")
        )
        form.addRow(tr("Data e hora ISO, incluindo fuso"), field)
        help = explain(
            "A pausa temporária termina automaticamente. Uma pausa sem prazo continua ativa até ser retomada. Vazio remove somente o prazo."
        )
        form.addRow(help)

        def apply() -> None:
            try:
                config = load(self.paths)
                config.paused_until = field.text().strip()
                self.write_config(config)
                dialog.accept()
                self.refresh()
            except Exception as exc:
                help.setText(str(exc))
                field_error(field, str(exc))

        button("Salvar", apply, form, emphasis="solid")
        button("Cancelar", dialog.reject, form)
        dialog.exec()

    def run_pending(self) -> None:
        selected = set(self.selected_ids())
        names = [
            r["id"]
            for r in self._last_rows
            if r["enabled"]
            and (not selected or r["id"] in selected)
            and r["last"].get("status") in {"failed", "skipped", "blocked_dependency", "cancelled"}
        ]
        if not names:
            self.set_status(tr("Nenhuma rotina pendente encontrada."), "warning")
            return
        self.read_details(
            tr("Prévia das rotinas pendentes"),
            lambda: Engine(self.paths).preview(names),
            commit=lambda plan: Engine(self.paths).run(names),
            action="Executar pendentes",
        )

    def check_script_libraries(self) -> None:
        row = self.routines.currentRow()
        if row < 0:
            return
        from .script_versions import check_dependencies

        job = copy.deepcopy(self.config.routines[row])
        self.read_details(tr("Verificar bibliotecas"), lambda: check_dependencies(job))

    def import_script_folder(self) -> None:
        if not self.confirm_settings_navigation():
            return
        root = QFileDialog.getExistingDirectory(self, tr("Selecionar pasta do script"))
        if not root:
            return
        entry = QFileDialog.getOpenFileName(
            self, tr("Selecionar entrada Python"), root, "Python (*.py)"
        )[0]
        if not entry:
            return
        from .operations import file_info
        from .script_versions import package_files

        folder = Path(root).resolve()
        source = Path(entry).resolve()
        if not source.is_relative_to(folder):
            self.set_status(tr("Entrada fora da pasta selecionada."), "error")
            return

        def preview() -> Any:
            files = package_files(folder)
            if source.relative_to(folder).as_posix() not in files:
                raise ValueError(tr("Entrada excluída da pasta de script."))
            return {
                "entry": source.relative_to(folder).as_posix(),
                "files": {name: file_info(path) for name, path in files.items()},
                "enabled": False,
                "excluded": "profiles, caches, .env, keys and links",
            }

        def commit(value: Any) -> Any:
            import uuid

            from .files import synced_copy
            from .script_versions import capture

            destination = self.paths.root / "extras/packages" / str(uuid.uuid4())
            if not destination.resolve().is_relative_to(self.paths.root.resolve()):
                raise ValueError("Pasta gerenciada inválida.")
            for name, item in value["files"].items():
                source_file = folder / name
                if digest(source_file) != item["sha256"]:
                    raise ValueError(tr("Arquivo mudou depois da prévia."))
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                synced_copy(source_file, target)
            config = load(self.paths)
            name = script_identifier(source)
            if any(j.id == name for j in config.routines):
                raise ValueError(tr("Identificador de rotina já cadastrado."))
            job = Routine(
                name,
                source.stem,
                str(destination / value["entry"]),
                package_root=str(destination),
                enabled=False,
                requires_browser=False,
                command="",
                origin="pasta importada",
                order=len(config.routines),
            )
            capture(self.paths, job)
            config.routines.append(job)
            save(self.paths, config)
            return {"registered": name, "enabled": False}

        self.read_details(
            tr("Prévia da pasta de script"), preview, commit=commit, action="Importar desabilitado"
        )

    def routine_trash(self) -> None:
        if not self.confirm_settings_navigation():
            return
        folder = self.paths.root / "extras/trash"
        folder.mkdir(parents=True, exist_ok=True)
        record = QFileDialog.getOpenFileName(
            self, tr("Restaurar cadastro da lixeira"), str(folder), "JSON (*.json)"
        )[0]
        if not record:
            return
        from .script_versions import restore_registration

        self.read_details(
            tr("Restaurar cadastro"),
            lambda: read_json(Path(record)),
            commit=lambda value: restore_registration(self.paths, load(self.paths), Path(record)),
            action="Restaurar desabilitado",
        )

    def export_selected_routine(self) -> None:
        row = self.routines.currentRow()
        if row < 0:
            return
        target = QFileDialog.getSaveFileName(
            self, tr("Exportar rotina"), "rotina.zip", "ZIP (*.zip)"
        )[0]
        if not target:
            return
        from .operations import export_routine, export_routine_preview

        config = copy.deepcopy(self.config)
        job = config.routines[row]
        self.read_details(
            tr("Prévia da exportação"),
            lambda: export_routine_preview(config, job),
            commit=lambda value: export_routine(Path(target), value),
            action="Exportar arquivos revisados",
        )

    def candidate_script(self) -> None:
        row = self.routines.currentRow()
        if row < 0:
            return
        file = QFileDialog.getOpenFileName(
            self, tr("Selecionar script candidato"), "", "Python (*.py)"
        )[0]
        if not file:
            return
        if (
            QMessageBox.question(
                self,
                tr("Ambiente de teste"),
                tr(
                    "Abrir o candidato em uma nova instalação de teste, sem ativá-lo nesta instalação? Scripts são código confiável e não recebem isolamento de segurança do Windows."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        import uuid

        candidate = Paths.user(self.paths.root / "candidates" / str(uuid.uuid4()))
        from .sandbox import mark, prepare_config

        config = prepare_config(candidate, self.config)
        for job in config.routines:
            job.enabled = False
        job = config.routines[row]
        job.script = str(Path(file).resolve())
        job.package_root = ""
        job.enabled = False
        candidate.ensure()
        mark(candidate)
        save(candidate, config)
        spawn(command("--data-root", str(candidate.root)))
        self.set_status(
            tr(
                "Candidato preparado e desabilitado. Revise e habilite somente no ambiente de teste."
            ),
            "success",
        )

    def notification_center(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("Central de notificações"))
        dialog.resize(900, 600)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(
            [
                tr("Data"),
                tr("Rotina"),
                tr("Mensagem"),
                tr("Execução"),
                tr("Repetições"),
                tr("Última repetição"),
            ]
        )
        configure_table(table)
        layout.addWidget(table)

        def loaded(rows: list[dict[str, Any]]) -> None:
            table.setRowCount(len(rows))
            names = {j.id: j.label for j in self.config.routines}
            for index, row in enumerate(rows):
                for col, value in enumerate(
                    (
                        row["at"],
                        names.get(row["job"], row["job"]),
                        row["message"],
                        row["run"],
                        row["repeat_count"],
                        row["last_at"] or row["at"],
                    )
                ):
                    set_cell(table, index, col, value)

        def detail(row: int, column: int) -> None:
            item = table.item(row, 3)
            run = item.text() if item else ""
            if run:
                self.read_details(tr("Detalhe da execução"), lambda: self.store.details(run))

        table.cellDoubleClicked.connect(detail)
        button(
            "Abrir execução selecionada",
            lambda: detail(table.currentRow(), 0) if table.currentRow() >= 0 else None,
            layout,
        )
        button("Fechar", dialog.reject, layout)
        task = Task(lambda: self.store.notification_history(), self)
        task.done.connect(loaded)
        task.failed.connect(lambda text: self.set_status(text, "error"))
        task.finished.connect(task.deleteLater)
        task.start()
        dialog.show()

    def support_package(self) -> None:
        target = QFileDialog.getSaveFileName(
            self, tr("Pacote de suporte"), "suporte.json", "JSON (*.json);;Excel (*.xlsx)"
        )[0]
        if not target:
            return
        from .exporting import export_data
        from .operations import support_preview

        query = self._history_committed

        def export(value: Any) -> Any:
            if Path(target).suffix.casefold() == ".xlsx":
                return export_data(
                    Path(target),
                    {
                        "Execuções": [
                            {k: v for k, v in r.items() if k != "events"} for r in value["runs"]
                        ],
                        "Eventos": [
                            {"run": r["id"], **e} for r in value["runs"] for e in r["events"]
                        ],
                    },
                )
            return export_data(Path(target), value)

        self.read_details(
            tr("Prévia sanitizada do suporte"),
            lambda: support_preview(
                self.store,
                start=query.get("start", ""),
                end=query.get("end", ""),
                jobs=[query["job"]] if query.get("job") else None,
            ),
            commit=export,
            action="Exportar evidências",
            present=lambda value: {
                "total": len(value["runs"]),
                "period": value["period"],
                "sample": value["runs"][:3],
                "sanitized": True,
            },
        )

    def storage_review(self) -> None:
        from .operations import clean_previewed, storage_preview

        self.read_details(
            tr("Ocupação e prévia da limpeza"),
            lambda: storage_preview(self.paths, load(self.paths)),
            commit=lambda value: clean_previewed(self.paths, value),
            action="Limpar arquivos revisados",
        )

    def save_window_preferences(self) -> None:
        atomic_json(
            self.paths.root / "state/window-preferences.json",
            {
                "width": self.width(),
                "height": self.height(),
                "splitter": self.workspace_splitter.sizes(),
                "follow_log": self.follow_log.isChecked(),
                "columns": {
                    "panel": [self.panel.columnWidth(i) for i in range(self.panel.columnCount())],
                    "history": [
                        self.history.columnWidth(i) for i in range(self.history_model.columnCount())
                    ],
                },
                "catalog": {
                    "query": self.catalog_search.text(),
                    "enabled": self.catalog_enabled.currentIndex(),
                    "browser": self.catalog_browser.currentIndex(),
                },
                "history_filters": {
                    k: v for k, v in self._history_committed.items() if k != "text"
                },
                "sort": self._history_sort,
                "descending": self._history_descending,
            },
        )

    def restore_window_preferences(self) -> None:
        try:
            value = read_json(self.paths.root / "state/window-preferences.json")
            screen = self.screen().availableGeometry()
            self.resize(
                min(screen.width(), max(980, int(value["width"]))),
                min(screen.height(), max(720, int(value["height"]))),
            )
            sizes = value.get("splitter", [])
            if len(sizes) == 2 and all(isinstance(n, int) and n >= 80 for n in sizes):
                self.workspace_splitter.setSizes(sizes)
            self.follow_log.setChecked(bool(value.get("follow_log", True)))
            for name, table in (("panel", self.panel), ("history", self.history)):
                for index, width in enumerate(value.get("columns", {}).get(name, [])):
                    if index < table.model().columnCount() and isinstance(width, int):
                        table.setColumnWidth(index, min(1000, max(60, width)))
            catalog = value.get("catalog", {})
            self.catalog_search.setText(str(catalog.get("query", "")))
            self.catalog_enabled.setCurrentIndex(max(0, min(2, int(catalog.get("enabled", 0)))))
            self.catalog_browser.setCurrentIndex(max(0, min(2, int(catalog.get("browser", 0)))))
            filters = value.get("history_filters", {})
            for name, field in (
                ("job", self.filter_job),
                ("status", self.filter_status),
                ("category", self.filter_category),
            ):
                index = field.findData(filters.get(name, ""))
                field.setCurrentIndex(max(0, index))
            self.filter_batch.setText(str(filters.get("batch", "")))
            for name, date_field in (("start", self.filter_start), ("end", self.filter_end)):
                if filters.get(name):
                    date = dt.datetime.fromisoformat(filters[name]).astimezone().date()
                    if name == "end":
                        date -= dt.timedelta(days=1)
                    date_field.setText(date.isoformat())
            sort = value.get("sort", "started")
            if sort in self.history_model.columns:
                self._history_sort = sort
                self._history_descending = bool(value.get("descending", True))
            self._history_committed = self.history_query()
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def rejected_files(self) -> None:
        from .operations import file_info, publication_preview

        filename = QFileDialog.getOpenFileName(
            self,
            tr("Selecionar registro de arquivo rejeitado"),
            str(self.paths.root / "rejected"),
            "JSON (*.json)",
        )[0]
        if not filename:
            return
        row = self.routines.currentRow()
        if row < 0:
            self.set_status(tr("Selecione primeiro uma rotina no catálogo."), "warning")
            return
        config = copy.deepcopy(self.config)
        job = config.routines[row]

        def preview() -> dict[str, Any]:
            record_file = Path(filename)
            area = (self.paths.root / "rejected").resolve()
            if record_file.is_symlink() or not record_file.resolve().is_relative_to(area):
                raise ValueError(tr("Registro fora da área de rejeitados."))
            record = read_json(record_file)
            source = Path(record["file"])
            if (
                record.get("owner") != "caio-rejected-v1"
                or source.is_symlink()
                or not source.resolve().is_relative_to(area)
                or digest(source) != record["sha256"]
            ):
                raise ValueError(tr("Arquivo rejeitado alterado ou inválido."))
            return {"record": record, "publication": publication_preview(config, job, source)}

        def publish(value: dict[str, Any]) -> Any:
            source = Path(value["record"]["file"])
            previous = value["publication"]
            if (
                file_info(source) != previous["source"]
                or file_info(Path(job.target)) != previous["target"]
            ):
                raise ValueError(tr("Arquivo mudou depois da prévia."))
            return Engine(self.paths).run([job.id], source=source)

        self.read_details(
            tr("Revalidar arquivo rejeitado"),
            preview,
            commit=publish,
            action="Publicar arquivo revisado",
        )

    def selected_ids(self) -> list[str]:
        names = []
        for index in self.panel.selectionModel().selectedRows():
            item = self.panel.item(index.row(), 0)
            if item is not None:
                names.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return names

    def selection_actions(self) -> None:
        count = len(self.selected_ids())
        self.batch_group.setVisible(count == 0)
        self.selection_group.setVisible(count > 0)
        self.selection_group.setTitle(
            tr(
                "Lote selecionado"
                if count > 1
                else "Rotina selecionada"
                if count == 1
                else "Escolha uma rotina"
            )
        )
        if count > 1:
            self.selection_group.setTitle(tr("Lote selecionado") + f" · {count}")
        self.simulate_button.setEnabled(count > 0)
        self.batch_button.setVisible(count == 0)
        self.run_button.setText(tr("Executar lote selecionado" if count > 1 else "Executar rotina"))
        self.force_button.setText(tr("Forçar lote selecionado" if count > 1 else "Forçar rotina"))
        self.login_button.setVisible(count <= 1)
        self.login_button.setEnabled(count == 1)
        self.run_button.setEnabled(count > 0)
        self.force_button.setEnabled(count > 0)
        if hasattr(self, "recommended_button"):
            record = next((r for r in self._last_rows if r["id"] in self.selected_ids()), None)
            category = (record or {}).get("last", {}).get("category", "")
            labels = {
                "driver": "Reparar EdgeDriver",
                "authentication": "Testar login",
                "vpn": "Testar conectividade",
                "internet": "Testar conectividade",
                "locked_file": "Abrir destino",
                "invalid_file": "Abrir destino",
            }
            self.recommended_button.setText(tr(labels.get(category, "Ver detalhe da execução")))
            self.recommended_button.setEnabled(count == 1)

    def save_delay(self) -> None:
        try:
            config = load(self.paths)
            config.queue_delay_seconds = self.queue_delay.value()
            self.write_config(config)
            self.status_label.setText(tr("Intervalo salvo."))
        except Exception as exc:
            self.task_error(str(exc))

    def change_language(self) -> None:
        if self.task and self.task.isRunning():
            self.task_error(tr("Aguarde a operação atual antes de trocar o idioma."))
            return
        try:
            config = load(self.paths)
            config.language = self.language.currentData()
            self.write_config(config)
            install_translation(QApplication.instance(), config.language)
            # Rebuild presentation only; the DB, tasks, profiles and scripts stay untouched.
            self.timer.stop()
            self.dev_panel.shutdown()
            self.tray.hide()
            self.replacement = MainWindow(self.paths)
            self.replacement.tabs.setCurrentIndex(2)
            self.replacement.show()
            setattr(QApplication.instance(), "_caio_window", self.replacement)
            self.hide()
            self.deleteLater()
        except Exception as exc:
            self.task_error(str(exc))

    def delete_routine(self) -> None:
        row = self.routines.currentRow()
        if row < 0:
            return
        config = load(self.paths)
        job = config.routines[row]
        box = QMessageBox(self)
        box.setWindowTitle(tr("Excluir rotina"))
        box.setText(tr("Retirar esta rotina do programa?") + "\n" + job.label)
        box.setInformativeText(
            tr(
                "Por padrão, o histórico e as versões do script ficam guardados. O arquivo original e os relatórios nunca são apagados."
            )
        )
        purge = QCheckBox(tr("Apagar também as cópias e versões gerenciadas deste script"))
        box.setCheckBox(purge)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            from .script_versions import remove

            remove(self.paths, config, job.id, purge.isChecked())
            self.config = config
            self.refresh()
        except Exception as exc:
            self.task_error(str(exc))

    def script_history(self) -> None:
        row = self.routines.currentRow()
        if row < 0:
            return
        from .script_versions import capture, compare_versions, restore, versions

        def collect() -> Any:
            config = load(self.paths)
            job = config.routines[row]
            capture(self.paths, job)
            return config, job, versions(self.paths, job)

        def loaded(value: Any) -> None:
            config, job, records = value
            dialog = QDialog(self)
            dialog.setWindowTitle(tr("Versões do script") + " • " + job.label)
            dialog.resize(900, 550)
            layout = QVBoxLayout(dialog)
            layout.addWidget(
                explain(
                    "Snapshots incluem os arquivos da pasta importada. Restaurar cria uma cópia gerenciada e preserva o original. Compare argumentos, destino e contrato antes de ativar."
                )
            )
            table = QTableWidget(len(records), 5)
            table.setHorizontalHeaderLabels(
                [tr("Data"), tr("Versão"), tr("Notas desta versão"), "SHA-256", tr("Origem")]
            )
            configure_table(table)
            for index, record in enumerate(records):
                for column, key in enumerate(("at", "version", "notes", "sha256", "source")):
                    set_cell(table, index, column, record.get(key, ""))
            layout.addWidget(table)

            def compare() -> None:
                index = table.currentRow()
                if index < 0 or index + 1 >= len(records):
                    self.set_status(
                        tr("Selecione uma versão com uma versão anterior disponível."), "warning"
                    )
                    return
                before, after = records[index + 1]["sha256"], records[index]["sha256"]
                self.read_details(
                    tr("Comparação entre versões"),
                    lambda: compare_versions(self.paths, job, before, after),
                )

            def rollback() -> None:
                index = table.currentRow()
                if index < 0:
                    return
                selected = records[index]
                self.read_details(
                    tr("Restaurar script"),
                    lambda: {
                        "selected": selected,
                        "current": capture(self.paths, job),
                        "preserves_original": True,
                    },
                    commit=lambda _: restore(self.paths, config, job, selected["sha256"]),
                    action="Ativar versão revisada",
                )
                dialog.accept()

            button("Comparar com versão anterior", compare, layout)
            button("Restaurar versão selecionada", rollback, layout)
            button("Fechar", dialog.reject, layout)
            dialog.show()

        task = Task(collect, self)
        task.done.connect(loaded)
        task.failed.connect(lambda text: self.set_status(text, "error"))
        task.finished.connect(task.deleteLater)
        task.start()

    def driver_operation(self, repair: bool) -> None:
        def operation() -> Any:
            with Lock(self.paths.lock):
                return diagnose(self.paths, load(self.paths), repair=repair)

        self.background(operation)

    @staticmethod
    def task_report(value: dict[str, Any]) -> str:
        import xml.etree.ElementTree as ET

        from .tasks import NS

        lines = [
            tr("Tarefa instalada") + ": " + tr("Sim" if value["installed"] else "Não"),
            tr("Configuração corresponde") + ": " + tr("Sim" if value["matches"] else "Não"),
        ]
        for label, key in (("Efetiva", "actual"), ("Esperada", "expected")):
            if not value.get(key):
                continue
            root = ET.fromstring(value[key])
            lines.append("\n" + tr(label))
            for name, path in (
                ("Programa", "Actions/Exec/Command"),
                ("Argumentos", "Actions/Exec/Arguments"),
                ("Usuário", "Principals/Principal/UserId"),
                ("Sessão", "Principals/Principal/LogonType"),
                ("Intervalo do monitor", "Triggers/CalendarTrigger/Repetition/Interval"),
                ("Habilitada", "Settings/Enabled"),
            ):
                lines.append(
                    tr(name)
                    + ": "
                    + str(
                        root.findtext("/".join("{" + NS + "}" + p for p in path.split("/"))) or "—"
                    )
                )
        return "\n".join(lines)

    def selected_id(self) -> str:
        row = self.panel.currentRow()
        item = self.panel.item(row, 0)
        if row < 0 or item is None:
            raise ValueError("Selecione uma rotina no Painel.")
        return str(item.data(Qt.ItemDataRole.UserRole))

    def background(self, callback: Callable[[], Any], details: bool = False) -> None:
        if self.task and self.task.isRunning():
            QMessageBox.information(
                self, "Operação em andamento", "Acompanhe a operação atual antes de iniciar outra."
            )
            return
        self.status_label.setText(tr("Processando… acompanhe o log acima."))
        self.append_log(tr("Operação iniciada."))
        self.set_status(tr("Processando… acompanhe o log acima."), "active")
        self.progress.setRange(0, 0)
        self.progress.show()
        self.task = Task(callback, self)
        self.task.progress.connect(lambda text: self.append_log(tr(text)))
        self.task.done.connect(lambda value: self.task_done(value, details))
        self.task.failed.connect(lambda error: self.task_error(error))
        self.task.start()

    def task_done(self, value: Any, details: bool) -> None:
        self.refresh()
        if not self.settings_dirty():
            self.reset_settings(load(self.paths))
        self.progress.hide()
        self.set_status(tr("Etapa anterior concluída com sucesso."), "success")
        if isinstance(value, dict) and "expected" in value and "installed" in value:
            self.render_task_report(value)
            if not value["matches"] and value.get("action") not in {"removed", "already_absent"}:
                self.set_status(
                    tr("A tarefa precisa de revisão. Consulte a tabela de tarefas."), "warning"
                )
            value = self.task_report(value)
        self.append_log(
            value
            if isinstance(value, str)
            else json_view(value)
            if value is not None
            else tr("Etapa anterior concluída com sucesso.")
        )
        if isinstance(value, list) and any(
            r.get("status") in {"failed", "skipped", "cancelled", "blocked_dependency"}
            for r in value
            if isinstance(r, dict)
        ):
            self.set_status(tr("Execução com pendências. Consulte o log e o histórico."), "warning")
            QApplication.alert(self)
        if (
            isinstance(value, list)
            and value
            and all(
                isinstance(row, dict) and row.get("status") in {"ignored", "not_eligible"}
                for row in value
            )
        ):
            self.set_status(
                tr(
                    "Nenhuma rotina executada. Consulte os motivos no log; Forçar permite repetir uma atualização já concluída."
                ),
                "warning",
            )
        if details:
            show_detail(self, "Resultado da operação", value)

    def task_error(self, error: str) -> None:
        self.progress.hide()
        self.append_log(error)
        self.set_status(error, "error")
        QApplication.alert(self, 15000)
        QMessageBox.warning(self, "Operação não concluída", error)
        self.refresh()

    def append_log(self, text: str) -> None:
        scroll = self.log.verticalScrollBar()
        position = scroll.value()
        self.log.appendPlainText(text)
        if not self.follow_log.isChecked():
            scroll.setValue(position)

    def set_status(self, text: str, severity: str = "") -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("severity", severity)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def show_application(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def start_run(self, selected: bool = False, **options: Any) -> None:
        try:
            names = self.selected_ids() if selected else None
            if selected and not names:
                raise ValueError("Selecione uma ou mais rotinas no Painel.")
            self.background(
                lambda: Engine(self.paths).run(names, **options),
                details=options.get("simulate", False),
            )
        except Exception as exc:
            self.task_error(str(exc))

    def control(self, value: str, batch: bool = False) -> None:
        selected = set(self.selected_ids())

        def operation() -> Any:
            active = self.store.history(status="running", limit=10000)
            active = [run for run in active if batch or run["job"] in selected]
            for run in active:
                self.store.control(run["id"], value)
                if value == "cancel" and batch:
                    self.store.control("batch:" + run["batch"], "cancel")
            return {"controls_requested": len(active), "action": value}

        self.background(operation)

    def settings_dirty(self) -> bool:
        if not hasattr(self, "common_settings"):
            return False
        return (
            self.settings_json.toPlainText() != self._settings_saved_text
            or to_dict(self.common_settings.value(validating=False)) != self._common_baseline
        )

    def confirm_settings_navigation(self) -> bool:
        if not self.settings_dirty():
            return True
        answer = QMessageBox.question(
            self,
            tr("Alterações não salvas"),
            tr("Salvar as alterações antes de continuar?"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_settings()
        if answer == QMessageBox.StandardButton.Discard:
            self.reset_settings(load(self.paths))
            return True
        return False

    def reset_settings(self, config: Config) -> None:
        self.common_settings = SettingsEditor(config, path_field)
        self.common_scroll.setWidget(self.common_settings)
        self.settings_json.setPlainText(json_view(to_dict(config)))
        self._settings_saved_text = self.settings_json.toPlainText()
        self._common_baseline = to_dict(self.common_settings.value(validating=False))
        self._edit_revision = getattr(config, "_source_revision", digest(self.paths.config))
        self.settings_error.clear()

    def write_config(self, config: Config, *, editing: bool = False) -> None:
        if self.config.test_mode and not config.test_mode:
            raise ValueError("O modo de teste isolado não pode ser desativado nesta instalação.")
        if self.settings_dirty() and not editing:
            raise ValueError(
                tr("Salve ou descarte as alterações em Configurações antes desta operação.")
            )
        with Lock(self.paths.maintenance_lock), Lock(self.paths.root / "state/config.lock"):
            save(
                self.paths,
                config,
                expected=self._edit_revision
                if editing
                else getattr(config, "_source_revision", self._edit_revision),
            )
        self._snapshot_generation += 1
        self.config = config
        self.reset_settings(config)

    def toggle_schedule(self) -> None:
        config = load(self.paths)
        config.scheduling_paused = not config.scheduling_paused
        self.write_config(config)
        self.refresh()

    def edit_routine(self, row: int) -> None:
        if row < 0:
            return
        config = load(self.paths)
        dialog = RoutineDialog(config, config.routines[row], self)
        if dialog.exec():
            from .script_versions import capture

            try:
                with Lock(self.paths.lock):
                    if script_path(config.routines[row].script).is_file():
                        capture(self.paths, config.routines[row])
                    capture(self.paths, dialog.updated)
                    self.write_config(dialog.result_config)
                self.refresh()
                self.set_status(tr("Etapa anterior concluída com sucesso."), "success")
            except Exception as exc:
                self.task_error(str(exc))

    def save_settings(self) -> bool:
        try:
            use_json = self.settings_tabs.currentIndex() == 1 or (
                self.settings_json.toPlainText() != self._settings_saved_text
                and to_dict(self.common_settings.value(validating=False)) == self._common_baseline
            )
            candidate = (
                from_dict(json.loads(self.settings_json.toPlainText()))
                if use_json
                else self.common_settings.value()
            )
            self.write_config(candidate, editing=True)
            self.refresh()
            self.set_status(tr("Alterações salvas."), "success")
            return True
        except Exception as exc:
            self.settings_error.setText(str(exc))
            self.set_status(str(exc), "error")
            return False

    def choose_setting_path(self) -> None:
        key = self.path_key.currentText()
        value = (
            QFileDialog.getOpenFileName(
                self, "Selecionar executável do driver", "", "Executáveis (*.exe)"
            )[0]
            if key == "driver"
            else QFileDialog.getExistingDirectory(self, "Selecionar pasta")
        )
        if value:
            data = json.loads(self.settings_json.toPlainText())
            if key == "driver":
                options = data.setdefault("driver_options", {})
                options["search_paths"] = list(
                    dict.fromkeys([value, *options.get("search_paths", [])])
                )
                self.write_config(from_dict(data))
                self.driver_operation(True)
                return
            data[key] = value
            self.settings_json.setPlainText(json_view(data))

    def export_settings(self) -> None:
        filename = QFileDialog.getSaveFileName(
            self, "Exportar preferências", "preferencias.json", "JSON (*.json)"
        )[0]
        if filename:
            atomic_json(Path(filename), portable(load(self.paths)))

    def import_settings(self) -> None:
        if not self.confirm_settings_navigation():
            return
        filename = QFileDialog.getOpenFileName(self, "Importar preferências", "", "JSON (*.json)")[
            0
        ]
        if not filename:
            return
        try:
            candidate, changes = import_preview(load(self.paths), read_json(Path(filename)))
            show_detail(self, "Prévia das alterações", changes)
            if (
                QMessageBox.question(self, "Aplicar importação", "Aplicar as alterações exibidas?")
                == QMessageBox.StandardButton.Yes
            ):
                self.write_config(candidate)
        except Exception as exc:
            self.task_error(str(exc))

    def discover_jobs(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Localizar extratores adicionais")
        if folder:
            config = load(self.paths)
            additions = discover(config, Path(folder))
            show_detail(
                self,
                "Extratores encontrados; revise e habilite para executar",
                [dataclasses.asdict(j) for j in additions],
            )
            config.routines.extend(additions)
            self.write_config(config)

    def register_script(self) -> None:
        filename = QFileDialog.getOpenFileName(
            self, "Cadastrar extrator Python", "", "Python (*.py)"
        )[0]
        if filename:
            config = load(self.paths)
            script = Path(filename)
            job = Routine(
                id=script_identifier(script),
                label=script.stem,
                script=str(script),
                enabled=False,
                origin="cadastro manual explícito",
                order=max((j.order for j in config.routines), default=-1) + 1,
                command="",
                requires_browser=False,
            )
            config.routines.append(job)
            dialog = RoutineDialog(config, job, self)
            if dialog.exec():
                from .script_versions import capture

                capture(self.paths, dialog.updated)
                self.write_config(dialog.result_config)
                self.refresh()

    def local_file(self) -> None:
        try:
            row = self.routines.currentRow()
            if row < 0:
                raise ValueError("Selecione uma rotina nesta tabela.")
            name = self.config.routines[row].id
            if name not in {
                "pipefy_clientes_tool_edge",
                "pipefy_eventos_tool_edge",
                "pipefy_procedimentos_tool_edge",
                "pipefy_status_atms_tool_edge",
            }:
                raise ValueError(
                    "Publicação local disponível para Clientes, Eventos, Procedimentos e ATMS."
                )
            filename = QFileDialog.getOpenFileName(
                self, "Publicar/mesclar arquivo local", "", "Excel (*.xlsx)"
            )[0]
            if filename:
                from .operations import file_info, publication_preview

                config = copy.deepcopy(self.config)
                job = config.job(name)
                source = Path(filename)

                def publish(preview: dict[str, Any]) -> Any:
                    if (
                        file_info(source) != preview["source"]
                        or file_info(Path(job.target)) != preview["target"]
                    ):
                        raise ValueError(tr("Arquivo mudou depois da prévia."))
                    return Engine(self.paths).run([name], source=source)

                self.read_details(
                    tr("Prévia da publicação local"),
                    lambda: publication_preview(config, job, source),
                    commit=publish,
                    action="Publicar arquivo revisado",
                )
        except Exception as exc:
            self.task_error(str(exc))

    def refresh_history(self) -> None:
        try:
            self._history_page = 0
            self._history_committed = self.history_query()
            self.refresh()
        except ValueError:
            self.history_empty.setText(tr("Informe datas válidas no formato AAAA-MM-DD."))
            self.history_empty.show()
            self.filter_start.setFocus()

    def clear_history_filters(self) -> None:
        self.filter_job.setCurrentIndex(0)
        self.filter_status.setCurrentIndex(0)
        self.filter_category.setCurrentIndex(0)
        for field in (self.filter_batch, self.filter_text, self.filter_start, self.filter_end):
            field.clear()
        self.refresh_history()
        self.filter_job.setFocus()

    def apply_history(self, result: dict[str, Any]) -> None:
        self._history_page = result["page"]
        self._history_committed["page"] = result["page"]
        self.history_model.update(result["rows"], {j.id: j.label for j in self.config.routines})
        total = result["total"]
        size = result["size"]
        page = result["page"]
        self.history_total.setText(
            f"{page * size + 1 if total else 0}–{min((page + 1) * size, total)} / {total}"
        )
        self.history_previous.setEnabled(page > 0)
        self.history_next.setEnabled((page + 1) * size < total)
        self.history_empty.setVisible(not result["rows"])
        self.history_empty.setText(
            tr(
                "Nenhum resultado para estes filtros. Use Limpar filtros para ver as execuções recentes."
                if any(
                    self._history_committed.get(k)
                    for k in ("job", "status", "category", "batch", "text", "start", "end")
                )
                else "Nenhuma execução registrada. Execute uma rotina no Painel para acompanhar o resultado aqui."
            )
        )

    def history_detail(self, row: int) -> None:
        if 0 <= row < len(self.history_model.rows):
            record = self.history_model.rows[row]
            self.read_details(
                tr("Detalhes locais da execução"),
                lambda: {"run": record, "events": self.store.details(record["id"])},
            )

    def export_history(self) -> None:
        filename = QFileDialog.getSaveFileName(
            self,
            "Exportar diagnóstico sem endpoints/segredos",
            "diagnostico.xlsx",
            "Excel (*.xlsx);;JSON (*.json)",
        )[0]
        if filename:
            self.background(lambda: self.store.export(Path(filename)))

    def refresh_backups(self) -> None:
        self.refresh()

    def apply_backups(self, records: list[dict[str, Any]]) -> None:
        self._backup_records = records
        self._backup_page = min(self._backup_page, max(0, (len(records) - 1) // 100))
        selected = records[self._backup_page * 100 : (self._backup_page + 1) * 100]
        if self.backups.rowCount() != len(selected):
            self.backups.setRowCount(len(selected))
        self.backup_empty.setVisible(not records)
        self.backup_total.setText(
            f"{self._backup_page * 100 + 1 if records else 0}–{min((self._backup_page + 1) * 100, len(records))} / {len(records)}"
        )
        for row, record in enumerate(selected):
            for column, key in enumerate(("at", "target", "size", "sha256", "id")):
                set_cell(self.backups, row, column, record[key])

    def selected_backup(self) -> str:
        row = self.backups.currentRow()
        if row < 0:
            raise ValueError("Selecione uma versão de relatório.")
        item = self.backups.item(row, 4)
        if item is None:
            raise ValueError("Versão inválida.")
        return item.text()

    def validate_backup(self) -> None:
        try:
            identifier = self.selected_backup()
            publisher = Publisher(self.paths.root / "backups/reports", self.config.retention)
            self.read_details(
                tr("Validar backup"),
                lambda: {
                    "valid": str(
                        publisher.validate_version(
                            next(r for r in publisher.versions() if r["id"] == identifier)
                        )
                    )
                },
            )
        except Exception as exc:
            self.task_error(str(exc))

    def restore_backup(self) -> None:
        try:
            identifier = self.selected_backup()
            from .operations import restoration_preview

            def restore(preview: dict[str, Any]) -> Any:
                from .operations import file_info

                target = Path(preview["backup"]["target"])
                if file_info(target) != preview["current"]:
                    raise ValueError(tr("Arquivo atual mudou depois da prévia."))
                with Lock(self.paths.lock):
                    run = self.store.begin("restore", "report", "restore", None)
                    try:
                        result = Publisher(
                            self.paths.root / "backups/reports", self.config.retention
                        ).restore(identifier, run)
                        self.store.event(run, "restore", result)
                        self.store.finish(run, "success", 0)
                        return result
                    except Exception as exc:
                        self.store.finish(run, "failed", 1, evidence=str(exc))
                        raise

            self.read_details(
                tr("Comparar e restaurar relatório"),
                lambda: restoration_preview(
                    Publisher(self.paths.root / "backups/reports", self.config.retention),
                    identifier,
                ),
                commit=restore,
                action="Restaurar preservando o atual",
            )
        except Exception as exc:
            self.set_status(str(exc), "error")

    def installation(self) -> None:
        if self.task and self.task.isRunning():
            self.task_error("Encerre a execução antes de atualizar o aplicativo.")
            return
        from .native_updates import is_native

        if is_native(self.paths):
            from .native_gui import preferences

            preferences(self)
            return
        wizard = InstallWizard(self.paths, load(self.paths), self)
        if wizard.exec():
            if wizard.paths.root != self.paths.root:
                spawn([str(wizard.installed_executable), "--data-root", str(wizard.paths.root)])
                return
            self.config = load(self.paths)

    def connectivity(self) -> None:
        try:
            job_id = self.connectivity_job.currentData()
            if not job_id:
                raise ValueError("Cadastre uma rotina de navegador para testar conectividade.")
            job = load(self.paths).job(job_id)
            if job.id not in KNOWN and not job.url:
                raise ValueError("Informe a URL da rotina para testar conectividade.")
            module = module_for(job) if job.id in KNOWN else None
            url = (
                job.url
                or getattr(module, "LOGIN_URL", "")
                or getattr(module, "DEFAULT_REPORT_URL", "")
                or getattr(module, "DEFAULT_DATABASE_URL", "")
            )

            def test() -> Any:
                if job.id == "kwms_alocacoes_tool_edge":
                    from .connectivity import kwms_diagnostic

                    return kwms_diagnostic(
                        self.paths, self.config, job, module, url, public_pipefy(self.config)
                    )
                evidence = probe(url, public_pipefy(self.config), self.config.vpn_interfaces)
                category = classify(evidence)
                return {
                    "category": category,
                    "evidence": as_dict(evidence),
                    "vpn": "confirmada"
                    if category == "vpn"
                    else "inconclusiva"
                    if category == "inconclusive"
                    else category,
                    "method": "Mesma sonda de rede do adaptador KWMS: destino, conexão pública e interfaces VPN. Resposta vazia isolada não confirma VPN.",
                }

            def locked_test() -> Any:
                with Lock(self.paths.lock):
                    return test()

            self.background(locked_test)
        except Exception as exc:
            self.task_error(str(exc))

    def installed_executable(self) -> Path:
        pointer = self.paths.root / "installation.json"
        if not pointer.is_file():
            raise ValueError("Instale o executável pelo wizard antes de gerenciar tarefas reais.")
        current = read_json(pointer)
        return Path(current.get("launcher", current["executable"]))

    def task_diff(self) -> None:
        try:
            executable = self.installed_executable()
            self.background(
                lambda: WindowsTasks(self.paths).differences(executable, current_user())
            )
        except Exception as exc:
            self.task_error(str(exc))

    def install_task(self) -> None:
        self.manage_task(True)

    def manage_task(self, install: bool) -> None:
        def operation() -> Any:
            tasks = WindowsTasks(self.paths)
            executable = self.installed_executable()
            if install:
                result = tasks.install(executable, current_user())
            else:
                result = tasks.remove()
            with Lock(self.paths.maintenance_lock), Lock(self.paths.root / "state/config.lock"):
                config = load(self.paths)
                config.install_schedules = install
                save(self.paths, config)
            return {**result, **tasks.differences(executable, current_user())}

        self.background(operation)

    def render_task_report(self, value: dict[str, Any]) -> None:
        import xml.etree.ElementTree as ET

        from .tasks import NS

        if value.get("checks"):
            labels = {
                "URI": "Identificação da tarefa",
                "Command": "Programa",
                "Arguments": "Argumentos",
                "WorkingDirectory": "Pasta de trabalho",
                "LogonType": "Sessão",
                "RunLevel": "Privilégios",
                "Interval": "Intervalo do monitor",
                "Duration": "Duração",
                "StopAtDurationEnd": "Encerrar ao fim da duração",
                "StartBoundary": "Início do monitor",
                "DaysInterval": "Intervalo em dias",
                "Enabled": "Habilitada",
                "MultipleInstancesPolicy": "Instâncias simultâneas",
                "ExecutionTimeLimit": "Limite de execução",
                "DisallowStartIfOnBatteries": "Impedir início na bateria",
                "StopIfGoingOnBatteries": "Parar na bateria",
                "StartWhenAvailable": "Recuperar execução perdida",
                "RunOnlyIfNetworkAvailable": "Exigir rede",
                "Actions/count": "Quantidade de ações",
                "Triggers/count": "Quantidade de gatilhos",
                "Principals/count": "Quantidade de usuários de execução",
            }
            self.tasks_view.setRowCount(len(value["checks"]))
            for row, check in enumerate(value["checks"]):
                name = tr(
                    labels.get(
                        check["field"],
                        labels.get(check["field"].rsplit("/", 1)[-1], check["field"]),
                    )
                )
                if check["field"].endswith("/Enabled"):
                    name += " · " + tr(
                        "Ao entrar no Windows"
                        if "/LogonTrigger/" in check["field"]
                        else "Monitor periódico"
                        if "/CalendarTrigger/" in check["field"]
                        else "Tarefa"
                    )
                actual = check["actual"]
                if actual is None:
                    actual = (
                        (str(check["effective_actual"]) + " (" + tr("Padrão") + ")")
                        if value["installed"]
                        else tr("Não instalada")
                    )
                for column, content in enumerate(
                    (
                        tr(name),
                        actual,
                        check["effective_expected"],
                        "OK" if check["matches"] else tr("Revisar"),
                    )
                ):
                    set_cell(self.tasks_view, row, column, content)
                    item = self.tasks_view.item(row, column)
                    if item is not None:
                        item.setToolTip(check["field"] + "\n" + str(content))
            return

        fields = [
            ("Programa", "Actions/Exec/Command"),
            ("Argumentos", "Actions/Exec/Arguments"),
            ("Usuário", "Principals/Principal/UserId"),
            ("Sessão", "Principals/Principal/LogonType"),
            ("Intervalo do monitor", "Triggers/CalendarTrigger/Repetition/Interval"),
            ("Habilitada", "Settings/Enabled"),
        ]
        self.tasks_view.setRowCount(len(fields))
        trees = {
            key: ET.fromstring(value[key]) if value.get(key) else None
            for key in ("actual", "expected")
        }
        for row, (label, path) in enumerate(fields):
            key = "/".join("{" + NS + "}" + part for part in path.split("/"))
            actual = (
                trees["actual"].findtext(key, "—")
                if trees["actual"] is not None
                else tr("Não instalada")
            )
            expected = (
                trees["expected"].findtext(key, "—") if trees["expected"] is not None else "—"
            )
            for column, content in enumerate(
                (label, actual, expected, "OK" if actual == expected else tr("Revisar"))
            ):
                set_cell(self.tasks_view, row, column, content)

    def backup_application(self) -> None:
        def backup() -> Any:
            with Lock(self.paths.lock):
                folder = (
                    self.paths.root
                    / "backups/app"
                    / ("manual-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
                )
                from .native_install import installer_for

                return installer_for(self.paths).snapshot(folder)

        self.background(backup)

    def rollback_application(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Selecionar backup de aplicativo", str(self.paths.root / "backups/app")
        )
        if (
            folder
            and QMessageBox.question(
                self,
                "Reverter aplicativo",
                "Restaurar versão, configuração, estado e tarefa deste backup? A configuração atual será preservada em outro backup.",
            )
            == QMessageBox.StandardButton.Yes
        ):
            from .native_updates import is_native

            if is_native(self.paths):
                from .native_gui import handoff

                handoff(self, backup=Path(folder))
            else:
                self.background(lambda: Installer(self.paths).rollback(Path(folder)))

    def uninstall(self) -> None:
        if not self.confirm_settings_navigation():
            return
        if self.task and self.task.isRunning():
            self.set_status(tr("Aguarde a operação atual antes de desinstalar."), "warning")
            return
        from .native_updates import is_native

        if is_native(self.paths):
            import os

            import psutil

            entry = self.paths.root / "launch/Entrada.ps1"
            if not entry.is_file():
                self.set_status(
                    tr("Atualize o CAIO pelo novo pacote para usar o desinstalador externo."),
                    "warning",
                )
                return
            host = str(
                Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            )
            spawn(
                [
                    host,
                    "-NoProfile",
                    "-STA",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    str(entry),
                    "-Action",
                    "uninstall",
                    "-DataRoot",
                    str(self.paths.root),
                    "-ParentPid",
                    str(os.getpid()),
                    "-ParentStarted",
                    str(psutil.Process().create_time()),
                ]
            )
            self.exit_requested = True
            self.close()
        elif (
            QMessageBox.question(
                self,
                tr("Desinstalar"),
                tr(
                    "Remover somente tarefa e atalho próprios? Dados, histórico e backups serão preservados."
                ),
            )
            == QMessageBox.StandardButton.Yes
        ):
            from .install import Installer

            self.background(lambda: Installer(self.paths).uninstall())

    def refresh(self) -> None:
        if self.exit_requested:
            return
        if self.read_task is not None:
            self._refresh_pending = True
            return
        run = ""
        row = self.panel.currentRow()
        item = self.panel.item(row, 10) if row >= 0 else None
        if item:
            run = item.data(Qt.ItemDataRole.UserRole) or item.text()
        history = copy.deepcopy(self._history_committed) if self.tabs.currentIndex() == 3 else None
        backups = self.tabs.currentIndex() == 4
        generation = self._snapshot_generation

        def collect() -> dict[str, Any]:
            with Lock(self.paths.maintenance_lock):
                data = self.observer.collect(log_run=str(run), history=history, backups=backups)
                data["history_request"] = history
                return data

        task = Task(collect, self)
        self.read_task = task
        task.done.connect(
            lambda data: self.refresh_unlocked(data)
            if generation == self._snapshot_generation and not self.exit_requested
            else None
        )
        task.failed.connect(lambda text: self.set_status(text, "warning"))

        def finished() -> None:
            self.read_task = None
            task.deleteLater()
            if self.exit_requested:
                self.close()
            elif self._refresh_pending:
                self._refresh_pending = False
                self.refresh()

        task.finished.connect(finished)
        task.start()

    def refresh_unlocked(self, snapshot: dict[str, Any] | None = None) -> None:
        try:
            if snapshot is None:
                snapshot = self.observer.collect()
            request = self.paths.root / "state/open-interface.json"
            if request.is_file():
                requested = read_json(request)
                request.unlink()
                self.show_application()
                if requested.get("run") == "notifications":
                    self.notification_center()
                elif requested.get("run"):
                    self.read_details(
                        tr("Detalhe da execução"), lambda: self.store.details(requested["run"])
                    )
            if (
                getattr(snapshot["config"], "_source_revision", "") != self._edit_revision
                and not self.settings_dirty()
            ):
                self.reset_settings(snapshot["config"])
            self.config = snapshot["config"]
            self.pause_schedule.setText(
                tr("Retomar agendamento" if self.config.scheduling_paused else "Pausar agendamento")
            )
            choices = [(job.label, job.id) for job in self.config.routines if job.requires_browser]
            if [
                self.connectivity_job.itemData(i) for i in range(self.connectivity_job.count())
            ] != [job for _, job in choices]:
                current = self.connectivity_job.currentData()
                self.connectivity_job.clear()
                for label, identifier in choices:
                    self.connectivity_job.addItem(label, identifier)
                index = self.connectivity_job.findData(current or "kwms_alocacoes_tool_edge")
                if index >= 0:
                    self.connectivity_job.setCurrentIndex(index)
            self.engine.config = self.config
            self.summary_values[0].setText(
                f"{sum(job.enabled for job in self.config.routines)} / {len(self.config.routines)}"
            )
            self.summary_values[1].setText(
                tr("Pausado" if self.config.scheduling_paused else "Ativo")
            )
            self.summary_values[2].setText(
                tr("Configurado" if self.config.install_schedules else "Não configurado")
            )
            rows = snapshot["rows"]
            self._last_rows = rows
            self._last_monitor = snapshot["monitor"]
            if self.panel.rowCount() != len(rows):
                self.panel.setRowCount(len(rows))
            active = False
            for row, record in enumerate(rows):
                last = record["last"]
                running = last.get("status") == "running"
                active |= running
                success = record["last_success"]
                error = last.get("category") or ""
                error = {
                    "driver": "Repare o EdgeDriver em Diagnóstico e manutenção.",
                    "authentication": "Use Testar login para autenticar a sessão.",
                    "vpn": "Verifique a VPN; a rotina permanece pendente.",
                    "internet": "Verifique as conexões de rede necessárias.",
                    "locked_file": "Feche o arquivo no Excel e tente novamente.",
                }.get(error, error)
                if error:
                    from .i18n import display_value

                    error = f"{tr('Etapa')}: {display_value(last.get('stage', ''))} • {tr('Código')}: {last.get('code', '—')}\n{tr(error)}"
                values = [
                    record["label"],
                    "Sim" if record["enabled"] else "Não",
                    last.get("stage") if running else STATUS.get(last.get("status"), "Pronta"),
                    last.get("started", "Nunca"),
                    success["at"] if success else "Nunca",
                    record["freshness"]
                    + ("\n" + record["data_updated"] if record["data_updated"] else ""),
                    record["next"]
                    or (tr("Desabilitada") if not record["enabled"] else tr("Agendamento pausado")),
                    duration(last["duration"]) if last.get("duration") else "",
                    last.get("attempt", ""),
                    error,
                    last.get("id", ""),
                ]
                for column, value in enumerate(values):
                    set_cell(self.panel, row, column, value, record["id"] if column == 0 else None)
            busy = active or bool(self.task and self.task.isRunning())
            self.progress.setVisible(busy)
            self.progress.setRange(0, 0 if busy else 1)
            self.timezone.setText(
                tr("Fuso local")
                + f": {local_now().tzinfo} • "
                + tr("Agendamento")
                + ": "
                + tr("pausado" if self.config.scheduling_paused else "ativo")
                + " • "
                + tr(
                    "Monitor configurado"
                    if self.config.install_schedules
                    else "Sem monitor: instale a tarefa para executar horários automaticamente"
                )
            )
            if self.routines.rowCount() != len(self.config.routines):
                self.routines.setRowCount(len(self.config.routines))
            for row, job in enumerate(self.config.routines):
                for column, value in enumerate(
                    (
                        job.label,
                        job.schedule.frequency,
                        ", ".join(job.schedule.times),
                        ", ".join(tr(DAYS[d])[:3] for d in job.schedule.days),
                        str(job.order),
                        job.origin,
                    )
                ):
                    set_cell(self.routines, row, column, value)
            if "history" in snapshot and snapshot.get("history_request") == self._history_committed:
                self.apply_history(snapshot["history"])
            if "backups" in snapshot:
                self.apply_backups(snapshot["backups"])
            self.deliver_notifications(snapshot["notifications"])
            log = snapshot["log"]
            if log.get("text"):
                scroll = self.log.verticalScrollBar()
                old = scroll.value()
                from PySide6.QtGui import QTextCursor

                cursor = QTextCursor(self.log.document())
                cursor.movePosition(QTextCursor.MoveOperation.End)
                if log.get("reset"):
                    cursor.insertText("\n— " + log.get("file", "") + " —\n")
                cursor.insertText(log["text"])
                scroll.setValue(scroll.maximum() if self.follow_log.isChecked() else old)
            self.render_monitor(snapshot["monitor"])
            self.filter_catalog()
            running_stages = [
                r["label"] + ": " + str(r["last"].get("stage", ""))
                for r in rows
                if r["last"].get("status") == "running"
            ]
            stage = " | ".join(running_stages)
            if stage and stage != self._last_stage:
                self.append_log(stage)
                self.status_label.setText(stage)
            self._last_stage = stage
            self.selection_actions()
        except Exception as exc:
            self.status_label.setText(str(exc))

    def deliver_notifications(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self.last_notification_run = row["run"] or ""
            from .notifications import show

            show(self.tray, row["message"])
            if row["kind"] == "vpn":
                self.vpn_notices.append(VpnNotice(self.store, row["run"], row["message"], self))

    def notification_detail(self) -> None:
        self.show_application()
        self.notification_center()

    def explicit_exit(self) -> None:
        if (
            (self.task and self.task.isRunning())
            or (self.update_task and self.update_task.isRunning())
            or (self.dev_panel.task and self.dev_panel.task.isRunning())
            or any(r["last"].get("status") == "running" for r in self._last_rows)
        ):
            QMessageBox.information(
                self,
                "Execução em andamento",
                "Use Cancelar e aguarde o encerramento controlado, ou minimize para manter a execução.",
            )
            self.hide()
            return
        self.exit_requested = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.isVisible() and self.settings_dirty() and not self.confirm_settings_navigation():
            event.ignore()
            return
        if self.exit_requested:
            self.timer.stop()
            active = [task for task in self.findChildren(QThread) if task.isRunning()]
            if active:
                for task in active:
                    task.finished.connect(self.close)
                self.hide()
                event.ignore()
                return
            self.save_window_preferences()
            self.dev_panel.shutdown()
            self.tray.hide()
            event.accept()
            QApplication.quit()
            return
        self.hide()
        from .notifications import show

        show(
            self.tray,
            "Interface minimizada. A execução continua ativa. Use Sair da interface para encerrar.",
        )
        event.ignore()


def launch(paths: Paths, run_detail: str = "") -> int:
    existing_app = QApplication.instance()
    if existing_app is not None and not isinstance(existing_app, QApplication):
        raise RuntimeError("A interface exige uma instância QApplication.")
    app = existing_app if existing_app is not None else QApplication(sys.argv[:1])
    app.setApplicationName("Orquestrador")
    app.setOrganizationName("Orquestrador")
    apply_theme(app)
    paths.ensure()
    from .native_updates import is_native

    native = is_native(paths)
    installer = Installer(paths)
    recovery = "" if native else installer.recover()
    if recovery:
        QMessageBox.information(None, "Recuperação de instalação", recovery)
    current = read_json(installer.pointer) if installer.pointer.is_file() else None
    if not paths.config.is_file() or (
        not native
        and getattr(sys, "frozen", False)
        and (not current or current.get("version") != VERSION)
    ):
        wizard = InstallWizard(paths, load(paths) if paths.config.is_file() else None)
        if not wizard.exec():
            return 3
        paths = wizard.paths
        from .__main__ import configure_logging

        logging_root = paths.root / "logs"
        logging_root.mkdir(parents=True, exist_ok=True)
        configure_logging(paths)
        from .runtime import capture_windowed_streams

        capture_windowed_streams(logging_root)
    window = MainWindow(paths)
    window.show()
    if native and any(job.enabled and job.requires_browser for job in window.config.routines):
        QTimer.singleShot(
            0,
            lambda: window.background(
                lambda: diagnose(paths, load(paths), repair=True, test_session=False)
            ),
        )
    if run_detail == "notifications":
        QTimer.singleShot(0, window.notification_center)
    elif run_detail:
        QTimer.singleShot(
            0,
            lambda: window.read_details(
                tr("Detalhe da execução"), lambda: Store(paths.database).details(run_detail)
            ),
        )
    return app.exec()
