"""Guided editors reuse Config validation; advanced JSON remains available."""

from __future__ import annotations

import copy
import re
from typing import Any, Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from .config import CATEGORIES, Config, Dependency, Retry, Routine, validate
from .i18n import tr
from .ui import DAYS, explain

CATEGORY_LABELS = dict(
    zip(
        CATEGORIES,
        (
            "VPN",
            "Autenticação",
            "Servidor",
            "Internet",
            "Download",
            "Arquivo inválido",
            "Arquivo bloqueado",
            "Inconclusivo",
            "Driver",
            "Outros erros",
        ),
    )
)


def integer(value: int, low: int = 0, high: int = 1000000) -> QSpinBox:
    widget = QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


def field_error(field: QWidget, message: str) -> None:
    field.setProperty("invalid", bool(message))
    field.setAccessibleDescription(message)
    field.setToolTip(message)
    field.style().unpolish(field)
    field.style().polish(field)
    if message:
        field.setFocus()


class SettingsEditor(QWidget):
    def __init__(self, config: Config, path_widget: Callable[..., Any]):
        super().__init__()
        self.base = copy.deepcopy(config)
        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.email = QLineEdit(config.email)
        self.email_error = explain("")
        self.email_error.setProperty("severity", "error")
        form.addRow(tr("E-mail"), self.email)
        form.addRow(self.email_error)
        self.email.editingFinished.connect(self.validate_email)
        self.directories: dict[str, QLineEdit] = {}
        for key, label in [
            ("downloads", "Temporários"),
            ("logs", "Logs"),
            ("profile", "Perfil do Edge"),
        ]:
            wrapper, field = path_widget(getattr(config, key))
            self.directories[key] = field
            form.addRow(tr(label), wrapper)
        self.targets: dict[str, QLineEdit] = {}
        for job in config.routines:
            field = QLineEdit(job.target)
            field.setAccessibleName(tr("Destino") + ": " + job.label)
            self.targets[job.id] = field
            form.addRow(tr("Destino") + ": " + job.label, field)
        self.count = integer(int(config.retention["count"]), 1, 100000)
        self.days = integer(int(config.retention["days"]), 1, 3650)
        self.megabytes = integer(max(1, int(config.retention["bytes"]) // 1048576), 1, 1000000)
        form.addRow(tr("Versões de relatório a manter"), self.count)
        form.addRow(tr("Idade dos backups (dias)"), self.days)
        form.addRow(tr("Orçamento dos backups (MiB)"), self.megabytes)
        self.temp_days = integer(int(config.maintenance.get("temporary_days", 7)), 1, 3650)
        self.log_days = integer(int(config.maintenance.get("log_days", 30)), 1, 3650)
        form.addRow(tr("Temporários: prévia de limpeza após dias"), self.temp_days)
        form.addRow(tr("Logs: prévia de limpeza após dias"), self.log_days)
        self.notices = QCheckBox(tr("Habilitar notificações"))
        self.notices.setChecked(config.notifications.get("enabled", True))
        form.addRow(self.notices)
        self.kinds: dict[str, QCheckBox] = {}
        for key, label in [
            ("complete", "Conclusão"),
            ("failure", "Falha"),
            ("vpn", "VPN"),
            ("stale", "Atraso"),
            ("stalled", "Sem evolução"),
        ]:
            box = QCheckBox(tr(label))
            box.setChecked(config.notifications.get("kinds", {}).get(key, True))
            self.kinds[key] = box
            form.addRow(box)
        self.cooldown = integer(int(config.notifications.get("cooldown_minutes", 60)), 0, 1440)
        self.hourly = integer(int(config.notifications.get("max_per_hour", 6)), 1, 1000)
        self.quiet_start = QLineEdit(str(config.notifications.get("quiet_start", "")))
        self.quiet_end = QLineEdit(str(config.notifications.get("quiet_end", "")))
        form.addRow(tr("Agrupar avisos repetidos (minutos)"), self.cooldown)
        form.addRow(tr("Limite de avisos por hora"), self.hourly)
        form.addRow(tr("Silêncio: início HH:MM"), self.quiet_start)
        form.addRow(tr("Silêncio: fim HH:MM"), self.quiet_end)
        self.calendar_name = QLineEdit(str(config.calendar.get("name", "")))
        self.calendar_dates = QLineEdit(", ".join(config.calendar.get("dates", [])))
        form.addRow(tr("Calendário de feriados (opcional)"), self.calendar_name)
        form.addRow(
            tr("Datas do calendário: AAAA-MM-DD, separadas por vírgula"), self.calendar_dates
        )
        form.addRow(
            explain(
                "Nenhum feriado é presumido. A limpeza exige prévia e confirmação; o arquivo mais recente é preservado."
            )
        )

    def validate_email(self) -> bool:
        valid = bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.email.text().strip()))
        message = "" if valid else tr("Informe um e-mail válido, como nome@empresa.com.")
        self.email_error.setText(message)
        field_error(self.email, message)
        return valid

    def value(self, *, validating: bool = True) -> Config:
        if validating and not self.validate_email():
            raise ValueError(tr("Informe um e-mail válido, como nome@empresa.com."))
        result = copy.deepcopy(self.base)
        result.email = self.email.text().strip()
        for key, field in self.directories.items():
            setattr(result, key, field.text().strip())
        for job in result.routines:
            if job.id in self.targets:
                job.target = self.targets[job.id].text().strip()
        result.retention.update(count=self.count.value(), days=self.days.value())
        if self.megabytes.value() != int(self.base.retention["bytes"]) // 1048576:
            result.retention["bytes"] = self.megabytes.value() * 1048576
        result.maintenance.update(
            temporary_days=self.temp_days.value(), log_days=self.log_days.value()
        )
        result.notifications.update(
            enabled=self.notices.isChecked(),
            kinds={k: b.isChecked() for k, b in self.kinds.items()},
            cooldown_minutes=self.cooldown.value(),
            max_per_hour=self.hourly.value(),
            quiet_start=self.quiet_start.text().strip(),
            quiet_end=self.quiet_end.text().strip(),
        )
        result.calendar = {
            "name": self.calendar_name.text().strip(),
            "dates": [v.strip() for v in self.calendar_dates.text().split(",") if v.strip()],
        }
        if validating:
            validate(result)
        return result


class DependencyEditor(QWidget):
    def __init__(self, config: Config, job: Routine):
        super().__init__()
        grid = QGridLayout(self)
        for i, label in enumerate(("Origem", "Sucesso exigido", "Validade (minutos)")):
            grid.addWidget(QLabel(tr(label)), 0, i)
        self.rows = []
        selected = {d.job: d for d in job.dependencies}
        for index, origin in enumerate((j for j in config.routines if j.id != job.id), 1):
            enabled = QCheckBox(
                origin.label + ("" if origin.enabled else " · " + tr("Desabilitada"))
            )
            enabled.setProperty("preserveUserText", True)
            enabled.setChecked(origin.id in selected)
            mode = QComboBox()
            mode.addItem(tr("Na mesma cadeia"), "same_chain")
            mode.addItem(tr("Sucesso anterior válido"), "fresh_success")
            age = integer(
                selected[origin.id].max_age_minutes if origin.id in selected else 60, 1, 525600
            )
            if origin.id in selected:
                mode.setCurrentIndex(mode.findData(selected[origin.id].mode))
            for i, widget in enumerate((enabled, mode, age)):
                grid.addWidget(widget, index, i)
            self.rows.append((origin.id, enabled, mode, age))

    def value(self) -> list[Dependency]:
        return [
            Dependency(
                name,
                mode.currentData(),
                age.value() if mode.currentData() == "fresh_success" else 0,
            )
            for name, enabled, mode, age in self.rows
            if enabled.isChecked()
        ]


class RetryEditor(QWidget):
    def __init__(self, job: Routine):
        super().__init__()
        grid = QGridLayout(self)
        for i, label in enumerate(
            ("Categoria", "Tentativas totais", "Espera (s)", "Multiplicador", "Orçamento (s)")
        ):
            grid.addWidget(QLabel(tr(label)), 0, i)
        self.rows = {}
        for index, category in enumerate(CATEGORIES, 1):
            retry = job.retries[category]
            attempts = integer(retry.attempts, 1, 10)
            if category in {"vpn", "authentication"}:
                attempts.setValue(1)
                attempts.setEnabled(False)
            delay = QDoubleSpinBox()
            delay.setRange(0, 86400)
            delay.setValue(retry.delay_seconds)
            backoff = QDoubleSpinBox()
            backoff.setRange(1, 100)
            backoff.setValue(retry.backoff)
            budget = integer(retry.total_timeout_seconds, 1, 86400)
            grid.addWidget(QLabel(tr(CATEGORY_LABELS[category])), index, 0)
            for i, widget in enumerate((attempts, delay, backoff, budget), 1):
                grid.addWidget(widget, index, i)
            self.rows[category] = (attempts, delay, backoff, budget)
        grid.addWidget(
            explain(
                "A tentativa inicial conta no total. Autenticação não repete automaticamente. KWMS mantém duas tentativas internas de VPN, com espera de 30 segundos e sem repetição externa para código 20."
            ),
            len(CATEGORIES) + 1,
            0,
            1,
            5,
        )

    def value(self) -> dict[str, Retry]:
        return {
            k: Retry(a.value(), d.value(), b.value(), t.value())
            for k, (a, d, b, t) in self.rows.items()
        }


class CalendarEditor(QWidget):
    def __init__(self, job: Routine):
        super().__init__()
        form = QFormLayout(self)
        self.day_times = {}
        for index, name in enumerate(DAYS):
            value = ", ".join(job.schedule.day_times.get(str(index), []))
            field = QLineEdit(value)
            field.setPlaceholderText(tr("Vazio usa os horários gerais da rotina"))
            self.day_times[str(index)] = field
            form.addRow(tr(name), field)
        self.excluded = QLineEdit(", ".join(job.schedule.excluded_dates))
        self.until = QLineEdit(job.schedule.paused_until)
        self.catchup = integer(job.schedule.catch_up_hours, 0, 168)
        self.delay = integer(job.queue_delay_seconds or 0, 0, 3600)
        self.override_delay = QCheckBox(tr("Usar intervalo próprio nesta rotina"))
        self.override_delay.setChecked(job.queue_delay_seconds is not None)
        form.addRow(tr("Pular datas AAAA-MM-DD, separadas por vírgula"), self.excluded)
        form.addRow(tr("Pausar até ISO com fuso (opcional)"), self.until)
        form.addRow(tr("Janela de recuperação (horas)"), self.catchup)
        form.addRow(self.override_delay)
        form.addRow(tr("Intervalo próprio após a rotina anterior (s)"), self.delay)
        form.addRow(
            explain(
                "Dias habilitados continuam obrigatórios. Horários perdidos são agrupados na oportunidade elegível mais recente; não há execução em tempestade. Sucesso diário ou semanal impede repetições no mesmo período."
            )
        )

    def apply(self, job: Routine) -> None:
        job.schedule.day_times = {
            k: [v.strip() for v in field.text().split(",") if v.strip()]
            for k, field in self.day_times.items()
            if field.text().strip()
        }
        job.schedule.excluded_dates = [
            v.strip() for v in self.excluded.text().split(",") if v.strip()
        ]
        job.schedule.paused_until = self.until.text().strip()
        job.schedule.catch_up_hours = self.catchup.value()
        job.queue_delay_seconds = self.delay.value() if self.override_delay.isChecked() else None
