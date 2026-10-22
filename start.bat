@echo off
setlocal
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo Create venv and install requirements.txt first.
    pause
    exit /b 1
)
"venv\Scripts\python.exe" scripts\start_system.py
if errorlevel 1 pause
