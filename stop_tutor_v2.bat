@echo off
chcp 65001 >nul
title Stopping AI Professor (Tutor v2)
cd /d "%~dp0"

rem ============================================================
rem  Stops the Tutor v2 stack: the tutor app (python -m tutor.app)
rem  and the Vosk TTS server. Processes are matched by ASCII
rem  markers in their CommandLine (the Cyrillic project path can't
rem  be passed reliably through cmd -> PowerShell argv).
rem  taskkill /T walks the parent->child tree.
rem ============================================================

echo Stopping the tutor app, the Vosk TTS server, and the board sidecar...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*vosk_tts_server\server.py*' -or $_.CommandLine -like '*tutor.app*' -or $_.CommandLine -like '*-m board*') } | ForEach-Object { Write-Host ('  killing tree at PID ' + $_.ProcessId); & taskkill /F /T /PID $_.ProcessId 2>&1 | Out-Null }"

echo.
echo All stopped.
timeout /t 2 /nobreak >nul
exit
