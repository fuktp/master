from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .io import SECRET, Lock, atomic_json, digest, read_json
from .paths import Paths

Json = dict[str, Any]
FREQUENCIES = ("daily", "weekly", "every_run", "weekdays")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
CATEGORIES = (
    "vpn",
    "authentication",
    "server",
    "internet",
    "download",
    "invalid_file",
    "locked_file",
    "inconclusive",
    "driver",
    "unknown",
)
KNOWN = {
    "pipefy_clientes_tool_edge": ("Clientes", "clientes", "Clientes.xlsx"),
    "pipefy_eventos_tool_edge": ("Eventos", "historico", "historico_reports.csv"),
    "pipefy_procedimentos_tool_edge": ("Procedimentos", "procedimentos", "Procedimentos.xlsx"),
    "kwms_alocacoes_tool_edge": (
        "KWMS",
        "KWMS",
        "Detalhes de Alocação_- Planos Aprovados e Baixados.xlsx",
    ),
    "pipefy_status_atms_tool_edge": ("ATMS", "ATMS", "status_projeto_atms.xlsx"),
}


def preset_days(frequency: str, weekday: int = 0) -> list[int]:
    return (
        list(range(5))
        if frequency == "weekdays"
        else [weekday]
        if frequency == "weekly"
        else list(range(7))
    )


def script_identifier(path: Path) -> str:
    stem = unicodedata.normalize("NFKD", path.stem).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip(".") or "script"


@dataclass
class Dependency:
    job: str
    mode: str = "same_chain"
    max_age_minutes: int = 0


@dataclass
class Schedule:
    frequency: str = "daily"
    times: list[str] = field(default_factory=lambda: ["08:30"])
    days: list[int] = field(default_factory=lambda: list(range(5)))
    weekday: int = 0
    paused: bool = False
    catch_up_hours: int = 24
    day_times: dict[str, list[str]] = field(default_factory=dict)
    excluded_dates: list[str] = field(default_factory=list)
    paused_until: str = ""


@dataclass
class Retry:
    attempts: int = 1
    delay_seconds: float = 30
    backoff: float = 1
    total_timeout_seconds: int = 1800


@dataclass
class Routine:
    id: str
    label: str
    script: str
    origin: str = "pacote v1.3.0"
    enabled: bool = True
    order: int = 0
    trusted_sha256: str = ""  # Historical checksum, no longer an authorization gate.
    script_version: str = ""
    schedule: Schedule = field(default_factory=Schedule)
    dependencies: list[Dependency] = field(default_factory=list)
    retries: dict[str, Retry] = field(default_factory=lambda: {c: Retry() for c in CATEGORIES})
    arguments: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    command: str = "run"
    timeout_seconds: int = 2700
    expected_hours: int = 24
    grace_hours: int = 2
    target: str = ""
    headless: bool = True
    url: str = ""
    notifications: bool = True
    requires_browser: bool = True
    working_directory: str = ""
    staged_output: str = ""
    queue_delay_seconds: int | None = None
    category: str = ""
    notes: str = ""
    stalled_minutes: int = 30
    package_root: str = ""


@dataclass
class Config:
    execution_profile: str = "desktop"
    language: str = "pt-BR"
    queue_delay_seconds: int = 30
    schema_version: int = 2
    test_mode: bool = False
    install_schedules: bool = True
    email: str = ""
    profile: str = ""
    driver: str = ""
    driver_options: Json = field(default_factory=dict)
    downloads: str = ""
    logs: str = ""
    routines: list[Routine] = field(default_factory=list)
    continue_on_error: bool = False
    scheduling_paused: bool = False
    retention: Json = field(
        default_factory=lambda: {"count": 10, "days": 90, "bytes": 2_000_000_000}
    )
    events: Json = field(
        default_factory=lambda: {
            "keys": ["Código"],
            "separator": ";",
            "encoding": "utf-8-sig",
            "sheet": "0",
            "header_row": 0,
        }
    )
    notifications: Json = field(
        default_factory=lambda: {"enabled": True, "cooldown_minutes": 60, "max_per_hour": 6}
    )
    vpn_interfaces: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    legacy: Json = field(default_factory=dict)
    install_root: str = ""
    paused_until: str = ""
    calendar: Json = field(default_factory=lambda: {"name": "", "dates": []})
    maintenance: Json = field(default_factory=lambda: {"temporary_days": 7, "log_days": 30})

    def job(self, name: str) -> Routine:
        return next(j for j in self.routines if j.id == name)


def to_dict(config: Config) -> Json:
    return dataclasses.asdict(config)


def from_dict(raw: Json) -> Config:
    data = copy.deepcopy(raw)
    routines = []
    for item in data.pop("routines", []):
        item["schedule"] = Schedule(**item.get("schedule", {}))
        item["dependencies"] = [Dependency(**d) for d in item.get("dependencies", [])]
        item["retries"] = {
            **{c: Retry() for c in CATEGORIES},
            **{c: Retry(**r) for c, r in item.get("retries", {}).items()},
        }
        routines.append(Routine(**item))
    config = Config(**data, routines=routines)
    validate(config)
    return config


def ordered(config: Config) -> list[Routine]:
    jobs = {j.id: j for j in config.routines}
    result: list[Routine] = []
    pending: set[str] = set()
    done: set[str] = set()

    def visit(job: Routine) -> None:
        if job.id in pending:
            raise ValueError(f"Ciclo nas dependências: {job.label}")
        if job.id in done:
            return
        pending.add(job.id)
        for dep in job.dependencies:
            if dep.job not in jobs:
                raise ValueError(f"Origem inexistente: {dep.job}")
            visit(jobs[dep.job])
        pending.remove(job.id)
        done.add(job.id)
        result.append(job)

    for job in sorted(config.routines, key=lambda j: (j.order, j.id)):
        visit(job)
    return result


def validate(config: Config) -> None:
    if config.execution_profile not in {"desktop", "portable_gui"}:
        raise ValueError("Perfil de execução inválido.")
    if config.execution_profile == "portable_gui" and not config.test_mode:
        raise ValueError("Este modo mantém os dados isolados na pasta escolhida.")

    def timestamp(value: str) -> None:
        if value and dt.datetime.fromisoformat(value).tzinfo is None:
            raise ValueError("Pausa temporária precisa incluir fuso horário.")

    timestamp(config.paused_until)
    for key in ("temporary_days", "log_days"):
        if not 1 <= int(config.maintenance.get(key, 7)) <= 3650:
            raise ValueError("Prazo de limpeza deve ficar entre 1 e 3650 dias.")
    quiet = [config.notifications.get(k, "") for k in ("quiet_start", "quiet_end")]
    if any(quiet) and (
        not all(quiet) or any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", str(t)) for t in quiet)
    ):
        raise ValueError("Informe início e fim dos horários de silêncio em HH:MM.")
    if config.calendar.get("dates") and not config.calendar.get("name"):
        raise ValueError("Informe o nome do calendário de feriados explicitamente configurado.")
    for date in config.calendar.get("dates", []):
        dt.date.fromisoformat(date)
    if config.schema_version != 2:
        raise ValueError("Configuração desktop deve usar schema_version 2.")
    if config.language not in {"pt-BR", "en", "es"}:
        raise ValueError("Idioma inválido.")
    if not 0 <= config.queue_delay_seconds <= 3600:
        raise ValueError("Intervalo entre rotinas deve ficar entre 0 e 3600 segundos.")
    ids: set[str] = set()
    for job in config.routines:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", job.id) or job.id in {".", ".."} or job.id in ids:
            raise ValueError("Identificador de rotina inválido ou duplicado.")
        ids.add(job.id)
        schedule = job.schedule
        timestamp(schedule.paused_until)
        for date in schedule.excluded_dates:
            dt.date.fromisoformat(date)
        if job.queue_delay_seconds is not None and not 0 <= job.queue_delay_seconds <= 3600:
            raise ValueError("Intervalo próprio deve ficar entre 0 e 3600 segundos.")
        if not 1 <= job.stalled_minutes <= 1440:
            raise ValueError("Alerta sem evolução deve ficar entre 1 e 1440 minutos.")
        for day, times in schedule.day_times.items():
            if (
                day not in {str(i) for i in range(7)}
                or not times
                or len(times) != len(set(times))
                or any(
                    not isinstance(t, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t)
                    for t in times
                )
            ):
                raise ValueError("Horários por dia: use dias 0–6 e horários HH:MM sem duplicatas.")
        if schedule.frequency not in FREQUENCIES:
            raise ValueError("Frequência inválida.")
        if not schedule.times or any(
            not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in schedule.times
        ):
            raise ValueError("Defina um ou mais horários HH:MM por rotina.")
        if len(schedule.times) != len(set(schedule.times)):
            raise ValueError("Horários duplicados.")
        if not schedule.days or any(type(d) is not int or not 0 <= d <= 6 for d in schedule.days):
            raise ValueError("Dias devem estar entre 0 (segunda) e 6 (domingo).")
        if not 0 <= schedule.weekday <= 6 or not 0 <= schedule.catch_up_hours <= 168:
            raise ValueError("Dia inicial ou janela de recuperação inválidos.")
        if schedule.frequency == "weekly" and schedule.weekday not in schedule.days:
            raise ValueError("O dia inicial semanal precisa estar habilitado.")
        if job.timeout_seconds <= 0 or job.expected_hours <= 0 or job.grace_hours < 0:
            raise ValueError("Timeout e prazo de atualização precisam ser positivos.")
        if job.target and not Path(job.target).is_absolute():
            raise ValueError("Destino deve ser absoluto.")
        if any(SECRET.search(k) for k in job.environment):
            raise ValueError("Não armazene segredos em variáveis da configuração.")
        if any(k in {"PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH"} for k in job.environment):
            raise ValueError("Variável de runtime reservada.")
        for dep in job.dependencies:
            if dep.mode not in {"same_chain", "fresh_success"}:
                raise ValueError("Modo de dependência inválido.")
            if dep.mode == "fresh_success" and dep.max_age_minutes <= 0:
                raise ValueError("Defina janela explícita para sucesso anterior.")
        for category, retry in job.retries.items():
            if (
                category not in CATEGORIES
                or not 1 <= retry.attempts <= 10
                or retry.delay_seconds < 0
                or retry.backoff < 1
                or retry.total_timeout_seconds <= 0
            ):
                raise ValueError("Política de tentativas inválida.")
            if category in {"authentication", "vpn"} and retry.attempts != 1:
                raise ValueError(
                    "Autenticação aguarda interação; VPN possui duas tentativas internas."
                )
    if len(config.events["separator"]) != 1 or not config.events["keys"]:
        raise ValueError("Informe separador e chave do histórico.")
    if int(config.events["header_row"]) < 0:
        raise ValueError("A linha de cabeçalho começa em zero.")
    for key in ("count", "days", "bytes"):
        if int(config.retention[key]) < 1:
            raise ValueError("Retenção precisa preservar ao menos uma versão.")
    ordered(config)


class ConfigurationConflict(ValueError):
    pass


def save(paths: Paths, config: Config, *, expected: str | None = None) -> None:
    validate(config)
    if config.test_mode:
        from .sandbox import validate_isolation

        validate_isolation(paths, config)
    # All writers share this commit lock, including callers holding higher-level locks.
    with Lock(paths.root / "state/config-commit.lock"):
        revision = expected if expected is not None else getattr(config, "_source_revision", None)
        actual = digest(paths.config) if paths.config.is_file() else ""
        if revision is not None and actual != revision:
            raise ConfigurationConflict(
                "A configuração mudou em outro processo. Recarregue e revise suas alterações antes de salvar."
            )
        atomic_json(paths.config, to_dict(config))
        config._source_revision = digest(paths.config)  # type: ignore[attr-defined]


_load_cache: dict[Path, tuple[tuple[int, int, int, int], Config]] = {}


def load(paths: Paths) -> Config:
    path = paths.config.resolve()
    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
    cached = _load_cache.get(path)
    if cached is not None and cached[0] == stamp:
        return copy.deepcopy(cached[1])
    raw = path.read_bytes()
    config = from_dict(json.loads(raw.decode("utf-8-sig")))
    config._source_revision = hashlib.sha256(raw).hexdigest()  # type: ignore[attr-defined]
    if len(_load_cache) >= 64:
        _load_cache.clear()
    _load_cache[path] = (stamp, config)
    return copy.deepcopy(config)


def defaults(paths: Paths, source: Path) -> Config:
    config = Config(
        profile=str(paths.root / "profiles/Edge"),
        driver=str(paths.root / "cache/driver/msedgedriver.exe"),
        downloads=str(paths.root / "downloads"),
        logs=str(paths.root / "logs"),
        install_root=str(paths.root / "app"),
    )
    for index, (name, (label, _, _)) in enumerate(KNOWN.items()):
        script = source / "scripts" / f"{name}.py"
        if script.is_file():
            job = Routine(
                id=name,
                label=label,
                script=f"bundle:scripts/{script.name}",
                order=index,
                trusted_sha256=digest(script),
                headless=label != "KWMS",
            )
            if label == "KWMS":
                job.schedule.frequency = "weekly"
                job.expected_hours = len(job.schedule.days) * 24
            if label == "ATMS":
                job.enabled = False
                job.origin = "extrator adicional preservado; habilitação explícita necessária"
            config.routines.append(job)
    return config


def migrate(path: Path, paths: Paths, source: Path) -> tuple[Config, list[str]]:
    import pipefy_orchestrator as legacy

    raw = read_json(path)
    settings = legacy.load_settings(path)
    config = defaults(paths, source)
    config.continue_on_error = settings.continue_on_error
    config.driver = str(settings.driver.managed_path)
    config.driver_options = {
        **dict(raw.get("driver", {})),
        "edge_binary": str(settings.driver.edge_binary or ""),
        "selenium_cache": str(settings.driver.selenium_cache),
    }
    config.legacy = {
        "config_source": str(path),
        "schedules": list(settings.schedules),
        "state_path": str(settings.runtime_dir / "job_schedule_state.json"),
        "tasks_migrated": False,
    }
    changes = ["Horários próprios substituem disparos globais; tarefas legadas exigem revisão."]
    config.routines.clear()
    for index, old in enumerate(settings.jobs):
        base = KNOWN.get(old.name)
        preference = raw.get("job_schedules", {}).get(old.name, {})
        frequency = preference.get("frequency", old.schedule.frequency)
        own_times = preference.get("times", [preference.get("time", old.schedule.time)])
        if frequency == "every_run" and "times" not in preference:
            own_times = list(settings.schedules) or own_times
        subfolder = base[1] if base else old.name
        filename = base[2] if base else ""
        target = settings.output_dir / subfolder / filename if filename else Path()
        if old.name.startswith("kwms"):
            target = (
                Path(old.environment.get("KWMS_OUTPUT_DIR", str(settings.output_dir / "KWMS")))
                / KNOWN[old.name][2]
            )
        environment = {k: v for k, v in old.environment.items() if not SECRET.search(k)}
        email = environment.pop("KWMS_EMAIL", "")
        if email:
            config.email = email
        arguments = [a for a in old.command_arguments if a not in {"--headless", "--weekdays-only"}]
        schedule = Schedule(
            frequency=frequency,
            times=own_times,
            days=list(range(5 if old.schedule.weekdays_only else 7)),
            weekday=WEEKDAYS.index(old.schedule.weekday),
        )
        job = Routine(
            id=old.name,
            label=base[0] if base else old.name,
            script=str(old.script),
            origin="instalação anterior",
            enabled=old.enabled,
            order=index,
            schedule=schedule,
            trusted_sha256=digest(old.script) if old.script.is_file() else "",
            arguments=arguments,
            options=list(old.options),
            environment=environment,
            timeout_seconds=old.timeout_minutes * 60,
            command=old.command,
            target=str(target) if filename else "",
            headless="--headless" in old.command_arguments,
        )
        job.working_directory = str(old.working_directory)
        if schedule.frequency == "weekly":
            job.expected_hours = len(schedule.days) * 24
        profile = environment.get("KWMS_EDGE_PROFILE")
        if profile:
            config.profile = profile
        if not old.script.is_file():
            job.enabled = False
            changes.append(f"Script indisponível: {old.name}")
        config.routines.append(job)
        if job.target and not Path(job.target).parent.is_dir():
            changes.append(f"Destino indisponível; corrija antes de executar: {job.label}")
    validate(config)
    return config, changes


def portable(config: Config) -> Json:
    data = to_dict(config)
    for key in (
        "profile",
        "driver",
        "driver_options",
        "downloads",
        "logs",
        "legacy",
        "install_root",
        "vpn_interfaces",
        "test_mode",
        "install_schedules",
        "execution_profile",
    ):
        data.pop(key, None)
    for job in data["routines"]:
        for key in (
            "script",
            "script_version",
            "target",
            "trusted_sha256",
            "environment",
            "options",
            "arguments",
            "working_directory",
            "staged_output",
            "requires_browser",
            "package_root",
        ):
            job.pop(key, None)
    return data


def import_preview(current: Config, data: Json) -> tuple[Config, list[str]]:
    allowed = {
        "language",
        "queue_delay_seconds",
        "schema_version",
        "email",
        "continue_on_error",
        "scheduling_paused",
        "retention",
        "events",
        "notifications",
        "exclusions",
        "paused_until",
        "calendar",
        "maintenance",
        "routines",
    }
    if set(data) - allowed:
        raise ValueError("Importação portátil contém parâmetros de máquina ou desconhecidos.")
    merged = to_dict(current)
    changes = []
    jobs = {j["id"]: j for j in merged["routines"]}
    for key, value in data.items():
        if key != "routines":
            if merged.get(key) != value:
                changes.append(f"Alterar {key}")
            merged[key] = value
            continue
        for incoming in value:
            if incoming["id"] not in jobs:
                raise ValueError(f"Rotina não cadastrada nesta máquina: {incoming['id']}")
            if set(incoming) & {
                "script",
                "script_version",
                "trusted_sha256",
                "target",
                "environment",
                "options",
                "arguments",
                "working_directory",
                "staged_output",
                "requires_browser",
                "package_root",
            }:
                raise ValueError("Parâmetros de execução não podem vir de importação portátil.")
            jobs[incoming["id"]].update(incoming)
            changes.append(f"Preferências: {incoming['id']}")
    return from_dict(merged), changes


def discover(config: Config, folder: Path, pattern: str = "*_tool_edge.py") -> list[Routine]:
    existing = {Path(j.script).resolve() for j in config.routines}
    results = []
    for script in sorted(folder.glob(pattern)):
        if script.name in config.exclusions or script.resolve() in existing:
            continue
        results.append(
            Routine(
                id=script_identifier(script),
                label=script.stem,
                script=str(script.resolve()),
                enabled=False,
                origin=f"descoberto em {folder}",
            )
        )
    return results
