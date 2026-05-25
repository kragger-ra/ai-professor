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

rem Board sidecar event log - rolling file only. Per-session snapshots
rem under data\sessions\ are the historical archive and are preserved
rem unless removed by hand.
if exist "data\board_events.jsonl" (
    echo.
    echo The board rolling log data\board_events.jsonl exists.
    echo Per-session snapshots and any exported PDF/HTML are NOT touched.
    choice /C YN /M "Delete the rolling board log"
    if errorlevel 2 (
        echo Kept board_events.jsonl.
    ) else (
        del /q "data\board_events.jsonl" 2>nul
        echo Deleted data\board_events.jsonl - snapshots under data\sessions\ kept.
    )
)

echo Done. The next session starts with a clean profile and empty memory.
echo.
pause
