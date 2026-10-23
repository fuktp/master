from __future__ import annotations

import dataclasses
import queue
import socket
import threading
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse


@dataclass
class Evidence:
    public_reachable: bool | None = None
    target_dns: bool | None = None
    target_tcp: bool | None = None
    http_status: int | None = None
    vpn_configured: bool = False
    vpn_active: bool | None = None
    empty_response: bool = False
    notes: list[str] = field(default_factory=list)


def classify(evidence: Evidence) -> str:
    if evidence.http_status is not None:
        if evidence.http_status >= 500:
            return "server"
        if evidence.http_status in {401, 403}:
            return "authentication"
        if 200 <= evidence.http_status < 400:
            return "inconclusive" if evidence.empty_response else "reachable"
        return "server"
    if evidence.public_reachable is False and evidence.target_tcp is False:
        return "internet"
    if (
        evidence.public_reachable
        and evidence.vpn_configured
        and evidence.vpn_active is False
        and (evidence.target_dns is False or evidence.target_tcp is False)
    ):
        return "vpn"
    return "inconclusive"


def bounded(operation: Callable[[], Any], timeout: float) -> Any:
    results: queue.Queue[Any] = queue.Queue()

    def execute() -> None:
        try:
            results.put((True, operation()))
        except Exception as exc:
            results.put((False, exc))

    threading.Thread(target=execute, daemon=True).start()
    try:
        ok, value = results.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("Tempo limite na verificação de conectividade.") from exc
    if ok:
        return value
    raise value


def probe(target: str, public_url: str, vpn_interfaces: list[str], timeout: float = 4) -> Evidence:
    import psutil
    import requests

    result = Evidence(vpn_configured=bool(vpn_interfaces))
    stats = psutil.net_if_stats()
    if vpn_interfaces:
        result.vpn_active = any(stats.get(name) and stats[name].isup for name in vpn_interfaces)
        result.notes.append("Interfaces VPN explicitamente configuradas foram verificadas.")

    def reachable(url: str) -> bool:
        host = urlparse(url).hostname
        if not host:
            raise ValueError("URL de diagnóstico inválida.")
        with socket.create_connection((host, urlparse(url).port or 443), timeout=timeout):
            return True

    try:
        result.public_reachable = bounded(lambda: reachable(public_url), timeout + 1)
    except (OSError, TimeoutError):
        result.public_reachable = False
    host = urlparse(target).hostname
    if not host:
        raise ValueError("URL alvo inválida.")
    try:
        bounded(lambda: socket.getaddrinfo(host, 443), timeout)
        result.target_dns = True
    except (OSError, TimeoutError):
        result.target_dns = False
    if result.target_dns:
        try:
            result.target_tcp = bounded(lambda: reachable(target), timeout + 1)
        except (OSError, TimeoutError):
            result.target_tcp = False
        try:
            response = requests.head(target, timeout=(timeout, timeout), allow_redirects=False)
            result.http_status = response.status_code
        except (requests.RequestException, OSError, TimeoutError):
            result.notes.append(
                "HTTPS não apresentou resposta verificável no prazo; evidência TCP preservada."
            )
    else:
        result.target_tcp = False
    result.notes.append("Resposta HTTP não comprova sessão autenticada; use Testar login.")
    return result


def as_dict(evidence: Evidence) -> dict[str, Any]:
    return dataclasses.asdict(evidence)


def kwms_diagnostic(
    paths: Any, config: Any, job: Any, module: Any, url: str, public_url: str
) -> dict[str, Any]:
    """Read-only probe of the same KWMS page and empty-response signal as extraction."""
    import tempfile

    from .driver import diagnose
    from .io import Lock

    with Lock(paths.lock):
        evidence = probe(url, public_url, config.vpn_interfaces)
        if classify(evidence) in {"server", "internet", "vpn", "authentication"}:
            return {
                "category": classify(evidence),
                "evidence": as_dict(evidence),
                "browser": "not_required",
            }
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options
        from selenium.webdriver.edge.service import Service

        diagnose(paths, config, repair=True, test_session=False)
        folder = paths.root / "cache/diagnostic"
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="kwms-", dir=folder) as profile:
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--user-data-dir=" + profile)
            options.add_argument("--no-first-run")
            browser = webdriver.Edge(
                service=Service(executable_path=config.driver), options=options
            )
            try:
                browser.set_page_load_timeout(15)
                error = ""
                try:
                    browser.get(url)
                except Exception as exc:
                    error = str(exc)
                try:
                    text = browser.execute_script(
                        "return document.body ? document.body.innerText : '';"
                    )
                except Exception:
                    text = ""
                evidence.empty_response = bool(module.is_empty_response(error + str(text)))
                if error and not evidence.empty_response:
                    evidence.notes.append("Navegador não confirmou acesso à página no prazo.")
                    category = "inconclusive"
                else:
                    category = classify(evidence)
                evidence.notes.append(
                    "Mesma página e detecção de resposta vazia do extrator KWMS; nenhum formulário enviado e nenhum sucesso consumido."
                )
                return {"category": category, "evidence": as_dict(evidence), "browser": "checked"}
            finally:
                browser.quit()
