from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from openpyxl import Workbook

from orquestrador_app.config import (
    defaults,
    import_preview,
    portable,
    save,
)
from orquestrador_app.connectivity import Evidence, classify
from orquestrador_app.engine import Engine
from orquestrador_app.paths import Paths
from orquestrador_app.resources import source_root
from orquestrador_app.worker import (
    Cancelled,
    Context,
    ServerUnavailable,
    module_for,
)


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        (Evidence(empty_response=True), "inconclusive"),
        (Evidence(public_reachable=True, target_tcp=False), "inconclusive"),
        (
            Evidence(
                public_reachable=True, target_tcp=False, vpn_configured=True, vpn_active=False
            ),
            "vpn",
        ),
        (
            Evidence(
                public_reachable=True,
                target_tcp=True,
                http_status=503,
                vpn_configured=True,
                vpn_active=False,
            ),
            "server",
        ),
        (Evidence(public_reachable=False, target_tcp=False), "internet"),
        (Evidence(http_status=401), "authentication"),
        (Evidence(http_status=200), "reachable"),
    ],
)
def test_connectivity_requires_multiple_signals(evidence: Evidence, expected: str) -> None:
    assert classify(evidence) == expected


def context_for(tmp_path: Path, id: str = "kwms_alocacoes_tool_edge") -> tuple[Context, object]:
    paths = Paths.user(tmp_path)
    paths.ensure()
    config = defaults(paths, source_root())
    config.email = "different@example.invalid"
    job = config.job(id)
    job.target = str(tmp_path / "published" / "report.xlsx")
    run = Engine(paths, config).store.begin("batch", id, "extraction", None)
    return Context(paths, config, job, run, "manual"), module_for(job)


def test_new_kwms_adapter_two_attempts_30_seconds_then_pending(tmp_path: Path) -> None:
    context, module = context_for(tmp_path)
    context.install_adapters(module)
    driver = Mock()
    driver.execute_script.return_value = "ERR_EMPTY_RESPONSE"
    calls = []
    waited = []
    context.wait = lambda seconds, stage: waited.append(seconds)

    def operation() -> None:
        calls.append(1)
        module.check_vpn_error(driver)

    with (
        patch(
            "orquestrador_app.worker.probe",
            return_value=Evidence(public_reachable=True, target_tcp=False),
        ),
        patch("orquestrador_app.worker.public_pipefy", return_value="https://example.invalid"),
    ):
        with pytest.raises(module.VpnRequiredError):
            module.with_vpn_retry(operation)
    assert len(calls) == 2 and waited == [30]
    assert context.store.control(context.run + ":connectivity") == "inconclusive"


def test_proven_server_outage_is_not_reclassified_as_vpn(tmp_path: Path) -> None:
    context, module = context_for(tmp_path)
    context.install_adapters(module)
    driver = Mock()
    driver.execute_script.return_value = "ERR_EMPTY_RESPONSE"
    with (
        patch("orquestrador_app.worker.probe", return_value=Evidence(http_status=503)),
        patch("orquestrador_app.worker.public_pipefy", return_value="https://example.invalid"),
    ):
        with pytest.raises(ServerUnavailable):
            module.with_vpn_retry(lambda: module.check_vpn_error(driver))


def test_checkpoint_cancel_does_not_publish(tmp_path: Path) -> None:
    context, _ = context_for(tmp_path)
    context.store.control(context.run, "cancel")
    with pytest.raises(Cancelled):
        context.checkpoint("before publication")
    assert context.publications == []


def test_portable_export_import_preview_rejects_code_and_machine_paths(tmp_path: Path) -> None:
    paths = Paths.user(tmp_path)
    config = defaults(paths, source_root())
    data = portable(config)
    assert "profile" not in data and "driver_options" not in data
    assert all("environment" not in j and "script" not in j for j in data["routines"])
    data["routines"][0]["schedule"]["times"] = ["19:07"]
    candidate, changes = import_preview(config, data)
    assert candidate.routines[0].schedule.times == ["19:07"] and changes
    data["routines"][0]["script"] = "untrusted.py"
    with pytest.raises(ValueError, match="execução"):
        import_preview(config, data)


@pytest.mark.parametrize(
    "name",
    [
        "pipefy_clientes_tool_edge",
        "pipefy_procedimentos_tool_edge",
        "pipefy_eventos_tool_edge",
        "pipefy_status_atms_tool_edge",
    ],
)
def test_real_worker_local_publication_without_browser(tmp_path: Path, name: str) -> None:
    paths = Paths.user(tmp_path / "usuário com espaço e acentuação")
    paths.ensure()
    config = defaults(paths, source_root())
    config.email = "other@example.invalid"
    job = config.job(name)
    job.enabled = True
    source = tmp_path / "input.xlsx"
    module = module_for(job)
    columns = (
        module.EXPORT_COLUMNS if name == "pipefy_eventos_tool_edge" else module.EXPECTED_COLUMNS
    )
    book = Workbook()
    book.active.append(list(columns))
    book.active.append(["1"] * len(columns))
    book.save(source)
    book.close()
    filename = (
        "historico_reports.csv" if name == "pipefy_eventos_tool_edge" else module.FINAL_FILENAME
    )
    job.target = str(tmp_path / "output" / filename)
    save(paths, config)
    engine = Engine(paths)
    result = engine.run([name], source=source)
    assert result[0]["status"] == "success", result
    assert Path(job.target).is_file()
    assert engine.store.state(name)["last_success"] is None
    assert engine.store.history()[0]["mode"] == "local_publication"
    if name == "pipefy_eventos_tool_edge":
        original = Path(job.target).read_bytes()
        result = engine.run([name], source=source)
        assert result[0]["status"] == "success" and Path(job.target).read_bytes() == original


def test_task_xml_same_product_interactive_token_and_no_restart_multiplier(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    from orquestrador_app.tasks import task_name, xml

    paths = Paths.user(tmp_path)
    value = xml(tmp_path / "Orquestrador.exe", paths, "MACHINE\\User")
    assert "InteractiveToken" in value and "LeastPrivilege" in value
    assert "--agent" in value and "IgnoreNew" in value and "RestartOnFailure" not in value
    assert "PT1M" in value and "StartWhenAvailable" in value
    assert task_name(paths) in value
    ET.fromstring(value)
