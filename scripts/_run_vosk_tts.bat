@echo off
chcp 65001 >nul
title Vosk TTS server
cd /d "%~dp0\.."
.venv\Scripts\python.exe vosk_tts_server\server.py > vosk_tts.log 2>&1
