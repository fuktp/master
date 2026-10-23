"""Frequências por rotina, estado persistente e formulário local de configuração."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DAY_LABELS = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")
FREQUENCIES = {"Diária": "daily", "Semanal": "weekly", "Todos os horários": "every_run"}


class ScheduleError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class Schedule:
    frequency: str = "every_run"
    time: str = "08:30"
    weekday: str = "Monday"
    weekdays_only: bool = False


def parse_schedule(raw: Mapping[str, Any]) -> Schedule:
    unknown = set(raw) - {"frequency", "time", "weekday", "weekdays_only"}
    if unknown:
        raise ScheduleError("Campos de frequência desconhecidos: " + ", ".join(sorted(unknown)))
    frequency = str(raw.get("frequency", "every_run")).strip().lower()
    if frequency not in FREQUENCIES.values():
        raise ScheduleError("frequency deve ser daily, weekly ou every_run.")
    time_text = str(raw.get("time", "08:30"))
    try:
        parsed_time = dt.datetime.strptime(time_text, "%H:%M")
    except ValueError as exc:
        raise ScheduleError(f"Horário inválido: {time_text!r}; use HH:mm.") from exc
    if parsed_time.strftime("%H:%M") != time_text:
        raise ScheduleError(f"Horário inválido: {time_text!r}; use HH:mm.")
    weekday = str(raw.get("weekday", "Monday"))
    if weekday not in WEEKDAYS:
        raise ScheduleError("weekday deve ser um dos dias em inglês: " + ", ".join(WEEKDAYS))
    weekdays_only = raw.get("weekdays_only", False)
    if not isinstance(weekdays_only, bool):
        raise ScheduleError("weekdays_only deve ser true ou false.")
    if frequency == "weekly" and weekdays_only and WEEKDAYS.index(weekday) > 4:
        raise ScheduleError("Uma rotina de dias úteis não pode ser agendada para sábado ou domingo.")
    return Schedule(frequency, time_text, weekday, weekdays_only)


def due_reason(schedule: Schedule, last_success: str | None, now: dt.datetime) -> tuple[bool, str]:
    if schedule.weekdays_only and now.weekday() > 4:
        return False, "Somente dias úteis (segunda a sexta)."
    if schedule.frequency == "every_run":
        return True, "Executa em todos os horários do lote."
    hour, minute = map(int, schedule.time.split(":"))
    period_start = now.date()
    if schedule.frequency == "weekly":
        period_start -= dt.timedelta(days=now.weekday())
        anchor = period_start + dt.timedelta(days=WEEKDAYS.index(schedule.weekday))
    else:
        anchor = now.date()
    scheduled_at = now.replace(year=anchor.year, month=anchor.month, day=anchor.day,
                               hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_at:
        return False, f"Aguardando {scheduled_at:%d/%m/%Y %H:%M}."
    if last_success:
        try:
            previous = dt.datetime.fromisoformat(last_success)
        except (TypeError, ValueError) as exc:
            raise ScheduleError("Data de última execução inválida no estado das frequências.") from exc
        if previous.tzinfo is None:
            raise ScheduleError("A última execução precisa incluir o fuso horário no estado.")
        previous = previous.astimezone(now.tzinfo)
        if previous.date() >= period_start:
            return False, "Já concluída com sucesso neste dia." if schedule.frequency == "daily" else "Já concluída com sucesso nesta semana."
    return True, "Execução pendente; falhas anteriores não contam como atualização."


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "jobs": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8-sig"))
        if state.get("schema_version") != 1 or not isinstance(state.get("jobs"), dict):
            raise ValueError("Formato inválido.")
        for entry in state["jobs"].values():
            if not isinstance(entry, dict) or not isinstance(entry.get("last_success_at"), str):
                raise ValueError("Entrada de execução inválida.")
        return state
    except (ValueError, AttributeError) as exc:
        raise ScheduleError(f"Estado de frequências inválido: {path}. Corrija o arquivo antes de executar.") from exc


def save_preferences(config_path: Path, jobs: Sequence[Any], preferences: Mapping[str, Mapping[str, Any]]) -> None:
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    current = dict(raw.get("job_schedules", {}))
    for job in jobs:
        values = dict(preferences[job.name])
        enabled = values.pop("enabled")
        schedule = parse_schedule(values)
        if schedule.frequency != "every_run":
            requested = dt.datetime.strptime(schedule.time, "%H:%M").time()
            slots = [dt.datetime.strptime(slot, "%H:%M").time() for slot in raw.get("schedules", [])]
            if slots and not any(slot >= requested for slot in slots):
                raise ScheduleError(f"{job.name}: inclua em schedules um horário igual ou posterior a {schedule.time}.")
        current[job.name] = {"enabled": bool(enabled), **dataclasses.asdict(schedule)}
    raw["job_schedules"] = current
    raw["schedule_setup_completed"] = True
    shutil.copy2(config_path, config_path.with_suffix(config_path.suffix + ".bak"))
    atomic_json(config_path, raw)


def configure_schedules(config_path: Path, jobs: Sequence[Any], if_needed: bool = False) -> bool:
    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if if_needed and raw.get("schedule_setup_completed", False):
        return True
    if not jobs:
        raise ScheduleError("Nenhuma rotina encontrada. Confira project_root e a pasta scripts.")
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
        root = tk.Tk()
    except Exception as exc:
        raise ScheduleError("Não foi possível abrir o formulário. Edite job_schedules no JSON e defina schedule_setup_completed como true.") from exc
    root.title("Frequência das automações — Pipefy e KWMS")
    root.geometry(f"940x{min(710, 245 + len(jobs) * 43)}")
    root.minsize(850, 350)
    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Escolha quando cada automação deve rodar", font=("Segoe UI", 14, "bold")).pack(anchor="w")
    ttk.Label(frame, text="Diária: 1 sucesso por dia. Semanal: 1 sucesso por semana, a partir do dia escolhido.\n"
              "Dias úteis: segunda a sexta. Se falhar, será tentada novamente nos próximos horários do lote.").pack(anchor="w", pady=(8, 12))
    canvas_frame = ttk.Frame(frame)
    canvas_frame.pack(fill="both", expand=True)
    canvas = tk.Canvas(canvas_frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    rows_frame = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=rows_frame, anchor="nw")
    rows_frame.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
    for col, title in enumerate(("Ativa / automação", "Frequência", "Dia da semana", "A partir de", "Só dias úteis")):
        ttk.Label(rows_frame, text=title, font=("Segoe UI", 9, "bold")).grid(row=0, column=col, sticky="w", padx=5, pady=6)
    rows_frame.columnconfigure(0, weight=1)
    records = {}
    labels = {value: key for key, value in FREQUENCIES.items()}
    for index, job in enumerate(jobs, 1):
        schedule = job.schedule
        active = tk.BooleanVar(value=job.enabled)
        frequency = tk.StringVar(value=labels[schedule.frequency])
        weekday = tk.StringVar(value=DAY_LABELS[WEEKDAYS.index(schedule.weekday)])
        time_value = tk.StringVar(value=schedule.time)
        weekdays_only = tk.BooleanVar(value=schedule.weekdays_only)
        ttk.Checkbutton(rows_frame, text=job.name, variable=active).grid(row=index, column=0, sticky="w", padx=5, pady=8)
        choice = ttk.Combobox(rows_frame, textvariable=frequency, values=list(FREQUENCIES), state="readonly", width=18)
        choice.grid(row=index, column=1, padx=5)
        day_choice = ttk.Combobox(rows_frame, textvariable=weekday, values=DAY_LABELS, state="readonly", width=10)
        day_choice.grid(row=index, column=2, padx=5)
        ttk.Entry(rows_frame, textvariable=time_value, width=7).grid(row=index, column=3, padx=5)
        ttk.Checkbutton(rows_frame, variable=weekdays_only).grid(row=index, column=4, padx=5)
        def update_day(event=None, frequency=frequency, day_choice=day_choice):
            day_choice.configure(state="readonly" if frequency.get() == "Semanal" else "disabled")
        choice.bind("<<ComboboxSelected>>", update_day)
        update_day()
        records[job.name] = (active, frequency, weekday, time_value, weekdays_only)
    outcome = {"saved": False}
    def save():
        try:
            preferences = {}
            for name, (active, frequency, weekday, time_value, weekdays_only) in records.items():
                preferences[name] = {"enabled": active.get(), "frequency": FREQUENCIES[frequency.get()],
                                     "weekday": WEEKDAYS[DAY_LABELS.index(weekday.get())],
                                     "time": time_value.get().strip(), "weekdays_only": weekdays_only.get()}
            save_preferences(config_path, jobs, preferences)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Configuração inválida", str(exc), parent=root)
            return
        outcome["saved"] = True
        root.destroy()
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(14, 0))
    ttk.Label(buttons, text="Horários do lote: " + ", ".join(raw.get("schedules", []))).pack(side="left")
    ttk.Button(buttons, text="Cancelar", command=root.destroy).pack(side="right", padx=(8, 0))
    ttk.Button(buttons, text="Salvar", command=save).pack(side="right")
    root.mainloop()
    return outcome["saved"]
