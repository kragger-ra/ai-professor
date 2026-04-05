@echo off
chcp 65001 >nul
title AI Professor - Starting...

cd /d "%~dp0"

echo [1/3] Starting VoiceMeeter Banana...
tasklist /FI "IMAGENAME eq voicemeeterpro.exe" 2>/dev/null | find /i "voicemeeterpro.exe" >nul
if errorlevel 1 (
    start "" "C:\Program Files (x86)\VB\Voicemeeteroicemeeterpro.exe"
    echo       Waiting for engine...
    timeout /t 5 /nobreak >nul
) else (
    echo       Already running
)

echo [2/3] Starting Vosk TTS server...
start "" /MIN "N:\exam\hVostic TTSenv\Scripts\python.exe" "N:\exam\hVostic TTS\server.py"
echo       Waiting for TTS...
timeout /t 10 /nobreak >nul

echo [3/3] Starting AI Professor...
start "" /MIN python src\main.py
echo       Waiting for Gradio...
timeout /t 15 /nobreak >nul

echo.
echo Configuring audio routing...
python -c "import sys; sys.path.insert(0,chr(39)+chr(115)+chr(114)+chr(99)+chr(39)); from utils.voicemeeter_control import zoom_mode; print(zoom_mode())"

echo.
echo ========================================
echo   AI Professor is ready!
echo   Opening http://localhost:22228
echo ========================================
start http://localhost:22228
exit
