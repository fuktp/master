@echo off
setlocal EnableExtensions
chcp 65001 >nul
where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher ^(py^) nao encontrado.
    pause
    exit /b 2
)
py "%~dp0pipefy_orchestrator.py" --config "%~dp0pipefy_orchestrator.config.json" configure-schedules
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
