@echo off
setlocal
cd /d "%~dp0"
set "ZHIHENG_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%ZHIHENG_PY%" set "ZHIHENG_PY=python"
"%ZHIHENG_PY%" launch.py %*
if errorlevel 1 pause
