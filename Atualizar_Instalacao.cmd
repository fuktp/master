@echo off
setlocal EnableExtensions
chcp 65001 >nul
where py >nul 2>&1
if errorlevel 1 (
    echo Python Launcher ^(py^) nao encontrado.
    pause
    exit /b 2
)
py "%~dp0update_installation.py" %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
