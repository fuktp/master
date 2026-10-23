from __future__ import annotations

import importlib.util
import logging
import os
import runpy
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from .config import KNOWN, Config, Routine, from_dict, load
from .connectivity import as_dict, classify, probe
from .files import Publisher
from .io import Lock, atomic_json, digest, read_json
from .notifications import enqueue
from .paths import Paths
from .resources import script_path
from .store import Store


class Cancelled(RuntimeError):
    pass


class InteractionRequired(RuntimeError):
    pass


class ServerUnavailable(RuntimeError):
    pass


class InternetUnavailable(RuntimeError):
    pass


def error_category(exc: BaseException) -> str:
    if isinstance(exc, InteractionRequired):
        return "authentication"
    if isinstance(exc, ServerUnavailable):
        return "server"
    if isinstance(exc, InternetUnavailable):
        return "internet"
    if isinstance(exc, PermissionError):
        return "locked_file"
    if isinstance(exc, (ValueError, zip_error())):
        return "invalid_file"
    text = str(exc).casefold()
    if any(s in text for s in ("sso", "mfa", "sessão expirada", "autentica", "login")):
        return "authentication"
    if isinstance(exc, TimeoutError) or "download" in text:
        return "download"
    if any(s in text for s in ("edgedriver", "webdriver", "driver incompat")):
        return "driver"
    if any(s in text for s in ("connectionerror", "name_not_resolved", "internet")):
        return "internet"
    return "unknown"


def zip_error() -> type[Exception]:
    import zipfile

    return zipfile.BadZipFile


def module_for(job: Routine) -> ModuleType:
    script = script_path(job.script)
    if not script.is_file() or script.suffix.casefold() != ".py":
        raise ValueError("Selecione um arquivo Python existente para esta rotina.")
    sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location(job.id, script)
    if not spec or not spec.loader:
        raise ValueError("Não foi possível carregar o extrator.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[job.id] = module
    spec.loader.exec_module(module)
    return module


class Context:
    def __init__(self, paths: Paths, config: Config, job: Routine, run: str, mode: str):
        self.paths, self.config, self.job, self.run, self.mode = paths, config, job, run, mode
        self.script_hash = (
            digest(script_path(job.script)) if script_path(job.script).is_file() else ""
        )
        self.store = Store(paths.database)
        self.publisher = Publisher(paths.root / "backups/reports", config.retention)
        self.publications: list[dict[str, Any]] = []
        self.directory = Path(config.downloads) / f"run-{run}"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.result = self.directory / "result.json"
        self.committed = False
        self.driver: Any = None
        self.retry_source: str = ""

    def checkpoint(self, stage: str) -> None:
        self.store.stage(self.run, stage)
        control = self.store.control(self.run)
        was_paused = control == "pause"
        if control == "cancel":
            raise Cancelled("Cancelado em checkpoint seguro; arquivo anterior preservado.")
        while control == "pause":
            self.store.stage(self.run, f"pausada em checkpoint: {stage}")
            time.sleep(0.2)
            control = self.store.control(self.run)
            if control == "cancel":
                raise Cancelled("Cancelado durante pausa segura.")
        if was_paused:
            if digest(script_path(self.job.script)) != self.script_hash:
                raise ValueError("Extrator mudou durante a pausa; retomada bloqueada.")
            if self.driver:
                try:
                    self.driver.execute_script("return document.readyState;")
                    url = str(self.driver.current_url).casefold()
                    if any(
                        marker in url
                        for marker in ("/login", "login.microsoftonline", "/authenticate")
                    ):
                        raise InteractionRequired("Sessão precisa de autenticação após a pausa.")
                except InteractionRequired:
                    raise
                except Exception as exc:
                    raise InteractionRequired(
                        "Sessão não pôde ser revalidada após a pausa."
                    ) from exc
        self.store.stage(self.run, stage)

    def wait(self, seconds: float, stage: str) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.checkpoint(f"{stage}: {max(0, int(deadline - time.monotonic()) + 1)} s")
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def record(self, result: dict[str, Any]) -> None:
        self.committed = True
        self.publications.append(result)
        self.store.event(self.run, "publication", result)

    def install_adapters(self, module: Any) -> None:
        target = Path(self.job.target) if self.job.target else None
        for function, validator in (
            ("publish_clients_workbook", "validate_clients_workbook"),
            ("publish_procedures_workbook", "validate_procedures_workbook"),
            ("publish_atms_workbook", "validate_atms_workbook"),
        ):
            if hasattr(module, function):
                validate = getattr(module, validator)

                def publish_table(
                    *,
                    source: Path,
                    sheet: str,
                    header_row: int,
                    allow_empty: bool,
                    _validate: Any = validate,
                    **_: Any,
                ) -> Any:
                    self.checkpoint("validando arquivo")
                    self.retry_source = str(source)
                    validation = _validate(
                        source, sheet=sheet, header_row=header_row, allow_empty=False
                    )
                    assert target is not None
                    existed = target.exists()
                    self.checkpoint(
                        "publicação: backup e substituição; pausa será aplicada após o commit"
                    )
                    self.record(self.publisher.publish(source, target, self.run))
                    return target, validation, existed

                setattr(module, function, publish_table)
        if hasattr(module, "publish_workbook"):

            def publish_kwms(source: Path, destination: Path) -> Path:
                self.checkpoint("validando relatório KWMS")
                self.retry_source = str(source)
                assert target is not None
                self.record(self.publisher.publish(source, target, self.run))
                return target

            module.publish_workbook = publish_kwms
        if hasattr(module, "merge_report"):

            def merge_events(*, excel_path: Path, **_: Any) -> Any:
                self.checkpoint("validando histórico e chaves de Eventos")
                self.retry_source = str(excel_path)
                settings = self.config.events
                frame = module.read_report(
                    excel_path, str(settings["sheet"]), int(settings["header_row"])
                )
                keys = [module.EXPORT_TO_HISTORY.get(k, k) for k in settings["keys"]]
                for key in keys:
                    if key not in frame.columns:
                        raise ValueError(f"Chave ausente: {key}")
                    frame[key] = frame[key].map(module._normalize_key)
                assert target is not None
                created = not target.is_file()
                result = self.publisher.merge_rows(
                    frame.to_dict(orient="records"),
                    list(frame.columns),
                    target,
                    self.run,
                    keys,
                    settings["separator"],
                    settings["encoding"],
                )
                self.record(result)
                return module.MergeResult(
                    result["incoming"], result["duplicates"], 0, result["appended"], created
                )

            module.merge_report = merge_events
        for name in ("wait_for_download", "open_database", "open_report", "open_reporting"):
            if hasattr(module, name):
                original = getattr(module, name)

                def checked(
                    *args: Any,
                    _original: Callable[..., Any] = original,
                    _name: str = name,
                    **kwargs: Any,
                ) -> Any:
                    if args and hasattr(args[0], "execute_script"):
                        self.driver = args[0]
                    self.checkpoint(f"{_name}: aguardando; pausa no próximo checkpoint seguro")
                    result = _original(*args, **kwargs)
                    self.checkpoint(f"{_name}: concluída")
                    return result

                setattr(module, name, checked)
        if self.mode == "scheduled" and hasattr(module, "_perform_visible_login"):

            def require_login(**_: Any) -> None:
                raise InteractionRequired(
                    "Sessão requer interação. Abra Testar login no aplicativo."
                )

            module._perform_visible_login = require_login
        if self.job.id == "kwms_alocacoes_tool_edge":
            self.kwms_adapter(module)

    def kwms_adapter(self, module: Any) -> None:
        def check(driver: Any, error: Exception | None = None) -> None:
            text = str(error or "")
            try:
                text += str(
                    driver.execute_script("return document.body ? document.body.innerText : '';")
                )
            except Exception:
                pass
            if not module.is_empty_response(text):
                return
            evidence = probe(
                module.LOGIN_URL, public_pipefy(self.config), self.config.vpn_interfaces
            )
            evidence.empty_response = True
            category = classify(evidence)
            self.store.event(self.run, "connectivity", {"category": category, **as_dict(evidence)})
            self.store.control(self.run + ":connectivity", category)
            if category == "server":
                raise ServerUnavailable("Indisponibilidade HTTP do servidor confirmada.")
            if category == "internet":
                raise InternetUnavailable(
                    "Falha nas conexões pública e do destino; verifique a conectividade."
                )
            if category == "authentication":
                raise InteractionRequired("Autenticação necessária; use Testar login.")
            raise module.VpnRequiredError(
                "Resposta vazia. Verifique a VPN; causa " + category + "."
            )

        def wait(seconds: int) -> None:
            category = self.store.control(self.run + ":connectivity")
            message = "Verifique a VPN. Nova tentativa em 30 segundos."
            if category != "vpn":
                message += " A causa da falha não foi confirmada."
            enqueue(self.store, self.config, "vpn", self.job.id, self.run, message)
            self.store.event(self.run, "vpn_wait", {"seconds": seconds, "category": category})
            self.wait(seconds, "KWMS: segunda e última tentativa em")

        module.check_vpn_error = check
        module.notify_vpn_and_wait = wait


def public_pipefy(config: Config) -> str:
    # Read only a confirmed URL from the shipped extractor rather than creating a probe endpoint.
    for job in config.routines:
        if job.id == "pipefy_clientes_tool_edge":
            return str(module_for(job).DEFAULT_DATABASE_URL)
    bundled = Routine(
        "pipefy_clientes_tool_edge", "Clientes", "bundle:scripts/pipefy_clientes_tool_edge.py"
    )
    return str(module_for(bundled).DEFAULT_DATABASE_URL)


def prepare_environment(config: Config, job: Routine, directory: Path) -> None:
    os.environ.update(job.environment)
    os.environ.update(
        {
            "PIPEFY_EDGE_DRIVER_PATH": config.driver,
            "MSEDGEDRIVER_PATH": config.driver,
            "PIPEFY_WORK_DIR": str(directory),
            "PIPEFY_OUTPUT_DIR": str(directory / "staging"),
            "SE_CACHE_PATH": str(directory.parent.parent / "cache/selenium"),
            "SE_AVOID_STATS": "true",
            "PYTHONUTF8": "1",
        }
    )


def arguments(module: Any, context: Context, action: str, source: Path | None) -> list[str]:
    job, config = context.job, context.config
    args = ["--log-file", str(Path(config.logs) / f"{context.run}.log")]
    if job.id == "kwms_alocacoes_tool_edge":
        args += [
            "--email",
            config.email,
            "--user-data-dir",
            config.profile,
            "--destination",
            str(context.directory / "staging"),
            "--work-dir",
            str(context.directory / "kwms"),
        ]
        if job.url:
            module.LOGIN_URL = job.url
        args.append("login" if action == "login" else "run")
        if action != "login" and job.headless:
            args.append("--headless")
        return args
    if job.id not in {
        "pipefy_clientes_tool_edge",
        "pipefy_eventos_tool_edge",
        "pipefy_procedimentos_tool_edge",
        "pipefy_status_atms_tool_edge",
    }:
        # Additional exporters retain their CLI. Their explicit arguments are reviewed with their hash.
        values = {
            "output_dir": str(context.directory / "staging"),
            "log_file": args[1],
            "driver_path": config.driver,
            "project_root": str(Path(job.script).parent),
        }

        def expand(items: list[str]) -> list[str]:
            return [str(x).format_map(values) for x in items]

        return (
            expand(job.options)
            + ["login" if action == "login" else job.command]
            + expand(job.arguments)
        )
    args.append(action)
    if action in {"run", "login"}:
        args += ["--email", config.email, "--user-data-dir", config.profile]
        if job.url:
            args += ["--report-url" if job.label == "ATMS" else "--database-url", job.url]
    if source:
        args += ["--input", str(source)]
    if action == "run" and job.headless:
        args.append("--headless")
    if action != "login":
        if job.id == "pipefy_eventos_tool_edge":
            args += ["--history-csv", str(context.directory / "staging/history.csv")]
        else:
            option = {
                "Clientes": "--clients-dir",
                "Procedimentos": "--procedures-dir",
                "ATMS": "--output-dir",
            }[job.label]
            args += [option, str(context.directory / "staging")]
        args += job.arguments
    return args


def execute(
    paths: Paths,
    job_id: str,
    run: str,
    mode: str,
    action: str = "run",
    source: Path | None = None,
    snapshot: Path | None = None,
) -> int:
    config = from_dict(read_json(snapshot)) if snapshot else load(paths)
    if config.test_mode:
        from .sandbox import validate_isolation

        validate_isolation(paths, config)
    job = config.job(job_id)
    context = Context(paths, config, job, run, mode)
    Path(config.logs).mkdir(parents=True, exist_ok=True)
    prepare_environment(config, job, context.directory)
    result: dict[str, Any] = {"code": 1, "category": "unknown", "publications": []}
    try:
        from .script_versions import capture

        context.store.event(run, "script_version", capture(paths, job))
        context.checkpoint("iniciando extrator preservado")
        if action in {"run", "login"} and job.requires_browser:
            from .driver import diagnose

            context.store.stage(run, "validando EdgeDriver e assinatura")
            context.store.event(
                run, "driver", diagnose(paths, config, repair=True, test_session=False)
            )
            prepare_environment(config, job, context.directory)
        if job.id not in KNOWN:
            result = run_custom(context, action)
            return int(result["code"])
        module = module_for(job)
        if action in {"run", "login"} and job.requires_browser:
            url = (
                job.url
                or getattr(module, "LOGIN_URL", "")
                or getattr(module, "DEFAULT_REPORT_URL", "")
                or getattr(module, "DEFAULT_DATABASE_URL", "")
            )
            evidence = probe(url, public_pipefy(config), config.vpn_interfaces)
            category = classify(evidence)
            context.store.event(
                run, "connectivity_preflight", {"category": category, **as_dict(evidence)}
            )
            if category == "server":
                raise ServerUnavailable(
                    "O destino apresentou erro HTTP de servidor antes da extração."
                )
            if category == "internet":
                raise InternetUnavailable("Conexões necessárias indisponíveis antes da extração.")
        context.install_adapters(module)
        if job.id == "kwms_alocacoes_tool_edge" and action == "replace" and source:
            context.record(context.publisher.publish(source, Path(job.target), run))
            result = {
                "code": 0,
                "category": "",
                "committed": True,
                "publications": context.publications,
            }
            return 0
        # Selenium's Service is patched only within this isolated worker, not in the source files.
        from selenium.webdriver.edge.service import Service

        original_service = Service.__init__

        def service_init(self: Any, *args: Any, **kwargs: Any) -> None:
            kwargs["executable_path"] = config.driver
            if args:
                args = (config.driver, *args[1:])
                kwargs.pop("executable_path")
            original_service(self, *args, **kwargs)

        setattr(Service, "__init__", service_init)
        parser = module.build_parser()
        parsed = parser.parse_args(arguments(module, context, action, source))
        if hasattr(module, "configure_logging"):
            module.configure_logging(False, str(Path(config.logs) / f"{run}.log"))
        with (
            Lock(Path(config.profile).parent / ".orquestrador-profile.lock")
            if action in {"run", "login"}
            else _NoLock()
        ):
            if job.id == "kwms_alocacoes_tool_edge":
                code = module.execute(parsed)
            else:
                parsed.func(parsed)
                code = 0
        if action != "login" and code == 0 and job.target and not context.publications:
            raise ValueError("Extrator encerrou sem publicação validada; sucesso não registrado.")
        category = context.store.control(run + ":connectivity") if code == 20 else ""
        result = {
            "code": code,
            "category": category or ("inconclusive" if code == 20 else ""),
            "publications": context.publications,
            "committed": context.committed,
            "retry_input": context.retry_source,
        }
    except Cancelled as exc:
        result = {
            "code": 130,
            "category": "cancelled",
            "error": str(exc),
            "publications": context.publications,
        }
    except BaseException as exc:
        logging.getLogger("desktop.worker").error("Falha: %s", exc)
        result = {
            "code": 1,
            "category": error_category(exc),
            "error": str(exc),
            "publications": context.publications,
            "committed": context.committed,
            "retry_input": context.retry_source,
        }
        if hasattr(exc, "conflicts"):
            result["conflicts"] = exc.conflicts
        rejected = Path(context.retry_source) if context.retry_source else None
        if (
            result["category"] == "invalid_file"
            and rejected
            and rejected.is_file()
            and rejected.resolve().is_relative_to(Path(config.downloads).resolve())
        ):
            try:
                from .operations import quarantine

                result["rejected"] = quarantine(
                    paths, rejected, str(exc), run, Path(config.downloads)
                )
            except Exception as preservation_error:
                result["rejected_warning"] = str(preservation_error)
    finally:
        atomic_json(context.result, result)
    return int(result["code"])


class _NoLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: Any) -> None:
        return None


def run_custom(context: Context, action: str) -> dict[str, Any]:
    job, config = context.job, context.config
    script = script_path(job.script)
    if not script.is_file() or script.suffix.casefold() != ".py":
        raise ValueError("O script cadastrado não está disponível.")
    values = {
        "project_root": str(script.parent),
        "output_dir": str(context.directory / "staging"),
        "driver_path": config.driver,
        "log_file": str(Path(config.logs) / f"{context.run}.log"),
    }
    (context.directory / "staging").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(script.parent))
    sys.argv = [str(script), *[s.format_map(values) for s in job.options]]
    if job.command:
        sys.argv.append("login" if action == "login" else job.command)
    sys.argv.extend(s.format_map(values) for s in job.arguments)
    os.chdir(job.working_directory or script.parent)
    code = 0
    with (
        Lock(Path(config.profile).parent / ".orquestrador-profile.lock")
        if job.requires_browser
        else _NoLock()
    ):
        try:
            runpy.run_path(str(script), run_name="__main__")
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    if not code and action != "login" and job.target:
        if not job.staged_output:
            raise ValueError(
                "Defina staged_output para validar e publicar o resultado deste extrator."
            )
        output = (context.directory / "staging" / job.staged_output).resolve()
        if not output.is_relative_to((context.directory / "staging").resolve()):
            raise ValueError("Resultado adicional fora da área temporária gerenciada.")
        context.checkpoint("validando e publicando resultado adicional")
        context.record(context.publisher.publish(output, Path(job.target), context.run))
    return {
        "code": code,
        "category": "" if code == 0 else "unknown",
        "publications": context.publications,
        "committed": context.committed,
    }
