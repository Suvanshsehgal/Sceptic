@echo off
if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0cli\main.py" %*
) else (
    python "%~dp0cli\main.py" %*
)
