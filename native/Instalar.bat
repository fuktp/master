@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0wizard.ps1"
exit /b %errorlevel%
