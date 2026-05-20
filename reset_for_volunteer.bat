@echo off
chcp 65001 >nul
title Reset for volunteer session

cd /d "%~dp0"

echo Resetting student_profiles.db and metrics.db (with backup)...
py scripts\reset_for_volunteer.py %*

if errorlevel 1 (
    echo.
    echo Reset FAILED. Check the message above.
    pause
    exit /b 1
)

echo.
echo Ready. Start the tutor with start_professor_tutor.bat
pause
