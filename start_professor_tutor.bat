@echo off
chcp 65001 >nul
title AI Professor (Tutor) - Starting...

cd /d "%~dp0"

echo [1/3] Starting VoiceMeeter Banana...
tasklist /FI "IMAGENAME eq voicemeeterpro_x64.exe" 2>nul | find /i "voicemeeterpro_x64.exe" >nul
if errorlevel 1 (
    start "" "C:\Program Files (x86)\VB\Voicemeeter\voicemeeterpro_x64.exe"
    echo       Waiting for engine...
    timeout /t 5 /nobreak >nul
) else (
    echo       Already running
)

echo [2/3] Starting Vosk TTS server...
tasklist /FI "WINDOWTITLE eq hVostic TTS*" 2>nul | find /i "python.exe" >nul
if errorlevel 1 (
    start "hVostic TTS" /MIN "N:\exam\hVostic TTS\venv\Scripts\python.exe" "N:\exam\LocalLLMExperement\hVostic TTS\server.py"
    echo       Waiting for TTS...
    timeout /t 10 /nobreak >nul
) else (
    echo       Already running
)

echo [3/3] Starting AI Professor Tutor (args: %*)...
start "AI Professor Tutor" /MIN python src\main.py %*
echo       Waiting for Gradio...
timeout /t 15 /nobreak >nul

echo.
echo Configuring audio routing...
python -c "import sys; sys.path.insert(0,chr(39)+chr(115)+chr(114)+chr(99)+chr(39)); from utils.voicemeeter_control import meeting_mode; print(meeting_mode())"

echo.
echo ========================================
echo   AI Professor (Tutor) is ready!
echo   Opening http://localhost:22229
echo ========================================
start http://localhost:22229
exit
