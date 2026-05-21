@echo off
chcp 65001 >nul
title Reset tutor memory
cd /d "%~dp0"

rem ============================================================
rem  Clears the tutor's long-term state: the student profile and
rem  the cross-session memory. The next session starts clean.
rem  Local setup = one profile, one memory.
rem ============================================================

echo Clearing long-term tutor state (profile + cross-session memory)...
del /q "data\session_memory.json" 2>nul
del /q "data\student_profile.json" 2>nul
echo Done. The next session starts with a clean profile and empty memory.
echo.
pause
