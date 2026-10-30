@echo off
rem FlexaScale launcher for Windows (PowerShell or cmd):  fsctl start ^| fsctl stop ^| fsctl status
rem Same as ./fsctl on Linux/macOS. Implementation: src\flexascale\lab\launcher.py
setlocal
set "FS_ROOT=%~dp0"
if exist "%FS_ROOT%.venv\Scripts\python.exe" (
  "%FS_ROOT%.venv\Scripts\python.exe" -m flexascale.lab.launcher %*
) else (
  echo Python virtualenv missing at %FS_ROOT%.venv  ^(python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt ^&^& .venv\Scripts\pip install -e .^)
  exit /b 1
)
exit /b %ERRORLEVEL%
