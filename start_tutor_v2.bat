@echo off
chcp 65001 >nul
title AI Professor (Tutor v2)
cd /d "%~dp0"

rem ============================================================
rem  Tutor v2 launcher - starts the Vosk TTS server, then the
rem  single-process tutor app (python -m tutor.app).
rem  LM Studio (RAG embeddings, :22227) is a separate prerequisite.
rem ============================================================

echo [1/2] Vosk TTS server...
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 goto vosk_running
powershell -NoProfile -Command "Start-Process -WindowStyle Minimized -FilePath 'scripts\_run_vosk_tts.bat'"
echo       waiting for TTS (model load can take up to 3 min on first run)...
set TTS_WAIT=0
:wait_tts
ping -n 4 127.0.0.1 >nul
set /a TTS_WAIT=TTS_WAIT+3
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 goto tts_ready
if %TTS_WAIT% lss 180 goto wait_tts
echo       ERROR: TTS did not start within 3 minutes. Check vosk_tts.log
exit /b 1
:tts_ready
echo       TTS ready after %TTS_WAIT% sec
goto check_lms
:vosk_running
echo       already running

:check_lms
curl -s -o nul --max-time 1 http://localhost:22227/v1/models
if not errorlevel 1 goto launch
echo       WARNING: LM Studio (:22227) not responding - RAG will be
echo                unavailable. Start LM Studio with the bge-m3 model.

:launch
echo.
echo ============================================================
echo   AI Professor Tutor v2 is running.
echo   - You will HEAR a readiness signal when it starts listening.
echo   - Full log: tutor_v2.log
echo   - Keep this window open. Press Ctrl+C here to stop.
echo ============================================================
echo.
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m tutor.app > tutor_v2.log 2>&1
