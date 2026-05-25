@echo off
chcp 65001 >nul
title AI Professor Board (replay)
cd /d "%~dp0"

rem ============================================================
rem  Standalone board sidecar - replays the current rolling log
rem  from the beginning (useful to review a finished session
rem  without running the tutor itself).
rem ============================================================

.venv\Scripts\python.exe -c "import PySide6" 2>nul
if errorlevel 1 (
    echo PySide6 is not installed. Install it first:
    echo     .venv\Scripts\pip install "PySide6~=6.7"
    pause
    exit /b 1
)

set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m board --replay
