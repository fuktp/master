@rem CAIO managed entry v1
@echo off
set "CAIO_ENTRY_SCRIPT=%~dp0launch\Entrada.ps1"
if not exist "%CAIO_ENTRY_SCRIPT%" set "CAIO_ENTRY_SCRIPT=%~dp0payload\native\Entrada.ps1"
if exist "%~dp0instalacao-teste.json" (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%CAIO_ENTRY_SCRIPT%" -Action __ACTION__ -DataRoot "%~dp0."
) else (
  "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%CAIO_ENTRY_SCRIPT%" -Action __ACTION__
)
exit /b %errorlevel%
