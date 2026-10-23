@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "PACKAGE_DIR=%~dp0"
set "ORCHESTRATOR=%PACKAGE_DIR%pipefy_orchestrator.py"
set "CONFIG=%PACKAGE_DIR%pipefy_orchestrator.config.json"
set "REQUIREMENTS=%PACKAGE_DIR%requirements.txt"
set "TASK_INSTALLER=%PACKAGE_DIR%install_tasks.ps1"

if not exist "%ORCHESTRATOR%" goto :missing_file
if not exist "%CONFIG%" goto :missing_file
if not exist "%REQUIREMENTS%" goto :missing_file
if not exist "%TASK_INSTALLER%" goto :missing_file

where py >nul 2>&1
if errorlevel 1 (
    echo Falha: o Python Launcher ^(py^) nao foi encontrado.
    goto :failure
)

py -c "import selenium, pandas, openpyxl, requests" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias Python...
    py -m pip install -r "%REQUIREMENTS%"
    if errorlevel 1 goto :failure
)

echo Configurando frequencias das automacoes...
py "%ORCHESTRATOR%" --config "%CONFIG%" configure-schedules --if-needed
if errorlevel 1 goto :failure

echo Validando driver e login do Pipefy...
py "%ORCHESTRATOR%" --config "%CONFIG%" login
if errorlevel 1 goto :failure

echo Instalando tarefas automaticas...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TASK_INSTALLER%" -ConfigPath "%CONFIG%"
if errorlevel 1 goto :failure

echo.
echo Automacao instalada com sucesso.
echo As tarefas respeitarao a frequencia escolhida para cada automacao.
pause
exit /b 0

:missing_file
echo Falha: o pacote esta incompleto em %PACKAGE_DIR%

:failure
echo.
echo A instalacao nao foi concluida. Consulte as mensagens acima.
pause
exit /b 1
