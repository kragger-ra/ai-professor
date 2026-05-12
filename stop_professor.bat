@echo off
chcp 65001 >nul
title Stopping AI Professor (Tutor)...

cd /d "%~dp0"

echo Releasing VoiceMeeter audio...
python -c "import sys; sys.path.insert(0,chr(39)+chr(115)+chr(114)+chr(99)+chr(39)); from utils.voicemeeter_control import release_audio; print(release_audio())" 2>nul

echo Stopping all python.exe running from this project's .venv...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.ExecutablePath -like '%~dp0.venv\Scripts\*' } | ForEach-Object { Write-Host ('  killing PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
rem Note: this also kills the Vosk TTS server on :22232. It will be restarted by start_professor_tutor.bat.

echo.
echo All stopped.
timeout /t 3 /nobreak >nul
exit
