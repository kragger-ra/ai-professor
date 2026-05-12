@echo off
chcp 65001 >nul
title Stopping AI Professor (Tutor)...

cd /d "%~dp0"

echo Releasing VoiceMeeter audio...
python -c "import sys; sys.path.insert(0,chr(39)+chr(115)+chr(114)+chr(99)+chr(39)); from utils.voicemeeter_control import release_audio; print(release_audio())" 2>nul

echo Stopping all python.exe owned by this project (roots + multiprocessing trees)...
rem Roots are processes whose CommandLine contains a marker unique to this project:
rem   vosk_tts_server\server.py  (Vosk HTTP server)
rem   src\main.py                (Tutor entry point)
rem taskkill /T walks the parent->child tree, so multiprocessing spawn children
rem (which only have 'multiprocessing.spawn' in their CommandLine — too generic to
rem match alone) go down with their root.
rem Cyrillic project path can't be passed reliably through cmd->PowerShell argv,
rem so we filter by these ASCII markers instead of %~dp0.
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*vosk_tts_server\server.py*' -or $_.CommandLine -like '*src\main.py*') } | ForEach-Object { Write-Host ('  killing tree at PID ' + $_.ProcessId); & taskkill /F /T /PID $_.ProcessId 2>&1 | Out-Null }"
rem Note: this also kills the Vosk TTS server on :22232. It will be restarted by start_professor_tutor.bat.

echo.
echo All stopped.
timeout /t 3 /nobreak >nul
exit
