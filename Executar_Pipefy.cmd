@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "PACKAGE_DIR=%~dp0"
set "ORCHESTRATOR=%PACKAGE_DIR%pipefy_orchestrator.py"
set "CONFIG=%PACKAGE_DIR%pipefy_orchestrator.config.json"

if not exist "%ORCHESTRATOR%" (
    echo Falha: arquivo nao encontrado: %ORCHESTRATOR%
    pause
    exit /b 2
)

if not exist "%CONFIG%" (
    echo Falha: arquivo nao encontrado: %CONFIG%
    pause
    exit /b 2
)

where py >nul 2>&1
if errorlevel 1 (
    echo Falha: o Python Launcher ^(py^) nao foi encontrado.
    pause
    exit /b 2
)

py "%ORCHESTRATOR%" --config "%CONFIG%" configure-schedules --if-needed
if errorlevel 1 (
    echo Nenhuma automacao foi iniciada. Configure as frequencias e tente novamente.
    pause
    exit /b 3
)

py "%ORCHESTRATOR%" --config "%CONFIG%" run
set "RESULT=%ERRORLEVEL%"

if not "%RESULT%"=="0" (
    echo.
    echo A execucao terminou com falha. Consulte a pasta logs.
    pause
)

exit /b %RESULT%
