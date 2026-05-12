@echo off
chcp 65001 >nul
title AI Professor (Tutor) - Starting...

cd /d "%~dp0"

rem ---- ping-based sleep ----
rem 'timeout' breaks under PowerShell-redirected stdin ("Input redirection is
rem not supported"), instantly returning and skipping every wait. ping always
rem honours its packet count, so we use it as a portable sleep.

rem ---- pre-flight: log files must be writable ----
(echo. > vosk_tts.log) 2>nul
if errorlevel 1 (
    echo ERROR: vosk_tts.log is locked. Close any editor/Notepad/VS Code tab
    echo        showing it ^(file is held open by another process^) and retry.
    exit /b 2
)
(echo. > tutor.log) 2>nul
if errorlevel 1 (
    echo ERROR: tutor.log is locked. Close any editor/Notepad/VS Code tab
    echo        showing it ^(file is held open by another process^) and retry.
    exit /b 2
)

echo [1/2] Starting Vosk TTS server...
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 (
    echo       Already running
    goto launch_main
)

rem Use PowerShell Start-Process to fully detach the child console: plain
rem 'start /MIN ...' inherits the parent's console session, so when this bat
rem hits 'exit' the child python receives CTRL_CLOSE_EVENT and dies.
powershell -NoProfile -Command "Start-Process -WindowStyle Minimized -FilePath 'scripts\_run_vosk_tts.bat'"
echo       Waiting for TTS (model load can take up to 3 min on first run)...
set TTS_WAIT=0

:wait_tts
ping -n 4 127.0.0.1 >nul
set /a TTS_WAIT=TTS_WAIT+3
curl -s -o nul --max-time 1 http://localhost:22232/health
if not errorlevel 1 goto tts_ready
if %TTS_WAIT% lss 180 goto wait_tts
echo       TTS did not start within 3 minutes. Check vosk_tts.log
exit /b 1

:tts_ready
echo       TTS ready after %TTS_WAIT% sec

:launch_main
echo [2/2] Starting AI Professor Tutor (args: %*)...
if "%*"=="" (
    powershell -NoProfile -Command "Start-Process -WindowStyle Minimized -FilePath 'scripts\_run_tutor.bat'"
) else (
    powershell -NoProfile -Command "Start-Process -WindowStyle Minimized -FilePath 'scripts\_run_tutor.bat' -ArgumentList '%*'"
)
echo       Waiting for Gradio (main.py imports + RAG warmup can take 30-60 sec)...
set GRADIO_WAIT=0

:wait_gradio
ping -n 4 127.0.0.1 >nul
set /a GRADIO_WAIT=GRADIO_WAIT+3
curl -s -o nul --max-time 1 http://localhost:22229
if not errorlevel 1 goto gradio_ready
if %GRADIO_WAIT% lss 120 goto wait_gradio
echo       Gradio did not start within 2 minutes. Check tutor.log
exit /b 1

:gradio_ready
echo       Gradio ready after %GRADIO_WAIT% sec

echo.
echo ========================================
echo   AI Professor (Tutor) is ready!
echo   Browser tab is being opened by Gradio.
echo   If it didn't, open http://localhost:22229 manually.
echo ========================================
rem NB: main.py launches Gradio with inbrowser=True, which opens the tab
rem itself. Re-doing 'start http://localhost:22229' here would open a
rem duplicate tab in a race with Gradio.
exit
