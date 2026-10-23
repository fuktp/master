"""Names of the owned Windows processes; browser/driver processes keep their own identities."""

from __future__ import annotations

from pathlib import Path

MAIN_HOST = "CAIO-Orquestrador.exe"
MONITOR_HOST = "CAIO-Monitor.exe"
UNINSTALL_HOST = "CAIO-Desinstalador.exe"
ROUTINE_HOST = "CAIO-Rotina.exe"
ROUTINE_HOSTS = {
    "pipefy_clientes_tool_edge": "CAIO-Rotina-Clientes.exe",
    "pipefy_eventos_tool_edge": "CAIO-Rotina-Eventos.exe",
    "pipefy_procedimentos_tool_edge": "CAIO-Rotina-Procedimentos.exe",
    "kwms_alocacoes_tool_edge": "CAIO-Rotina-KWMS.exe",
    "pipefy_status_atms_tool_edge": "CAIO-Rotina-ATMS.exe",
}
HOST_DESCRIPTIONS = {
    MAIN_HOST: "CAIO - Orquestrador",
    MONITOR_HOST: "CAIO - Monitor de agendamentos",
    UNINSTALL_HOST: "CAIO - Desinstalador",
    ROUTINE_HOST: "CAIO - Rotina adicional",
    **{
        name: "CAIO - Rotina " + name.removeprefix("CAIO-Rotina-").removesuffix(".exe")
        for name in ROUTINE_HOSTS.values()
    },
}


def host_for(arguments: tuple[str, ...]) -> str:
    if "--uninstall" in arguments:
        return UNINSTALL_HOST
    if "--worker" in arguments:
        index = arguments.index("--worker") + 1
        return ROUTINE_HOSTS.get(arguments[index] if index < len(arguments) else "", ROUTINE_HOST)
    if "--agent" in arguments:
        return MONITOR_HOST
    return MAIN_HOST


def executable(release: Path, name: str = MAIN_HOST) -> Path:
    """Old releases remain usable for rollback; new releases declare all branded hosts."""
    candidate = release / "runtime" / name
    return candidate if candidate.is_file() else release / "runtime/pythonw.exe"
