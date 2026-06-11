@echo off
setlocal
set "VENV=%~dp0..\.venv\Scripts"

if not exist "%VENV%\python.exe" (
    echo [ERROR] .venv not found. Creating and installing dependencies...
    python -m venv "%~dp0..\.venv"
    "%~dp0..\.venv\Scripts\pip.exe" install -r "%~dp0requirements.txt"
)

echo [Bath-Questionaire] Starting on http://localhost:5001
"%VENV%\python.exe" "%~dp0app.py"
pause
