@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title AI Professor - Setup
cd /d "%~dp0"

rem ============================================================
rem  AI Professor - Beta setup script (Windows).
rem
rem  Idempotent: re-running upgrades dependencies, does NOT clobber
rem  existing .env. Targets a tester with a clean Windows machine.
rem
rem  Stages:
rem    1. Find a Python 3.10 interpreter
rem    2. Create / refresh the .venv
rem    3. Install all required extras
rem    4. Bootstrap .env from .env.example
rem    5. Print "what's next"
rem ============================================================

echo.
echo === AI Professor - setup ===
echo.

rem --- 1. Find Python 3.10 -----------------------------------
set "PY_EXE="

rem Prefer the Python launcher with explicit version.
where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%i in ('py -3.10 -c "import sys; print(sys.executable)" 2^>nul') do set "PY_EXE=%%i"
)

if "!PY_EXE!"=="" (
    rem Fall back to the first python in PATH if it's 3.10.x.
    where python >nul 2>nul
    if not errorlevel 1 (
        for /f "delims=" %%i in ('python -c "import sys; v=sys.version_info; print(sys.executable) if v[:2]==(3,10) else exit(1)" 2^>nul') do set "PY_EXE=%%i"
    )
)

if "!PY_EXE!"=="" (
    echo [error] Python 3.10 not found.
    echo.
    echo Install Python 3.10 from https://www.python.org/downloads/release/python-31011/
    echo and re-run this script.  ^(3.11+ does NOT work: some dependencies are pinned.^)
    exit /b 1
)

echo [1/4] Python 3.10 found: !PY_EXE!

rem --- 2. Create / refresh .venv -----------------------------
if exist ".venv\Scripts\python.exe" (
    echo [2/4] Using existing virtual environment .venv
) else (
    echo [2/4] Creating virtual environment .venv ...
    "!PY_EXE!" -m venv .venv
    if errorlevel 1 (
        echo [error] failed to create .venv
        exit /b 2
    )
)

set "VENV_PY=.venv\Scripts\python.exe"
"%VENV_PY%" -m pip install --quiet --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [error] pip upgrade failed
    exit /b 3
)

rem --- 3. Install extras -------------------------------------
echo [3/4] Installing project + extras ^(may take 3-10 minutes on first run^)...
echo       extras: stt, simpletts, board, postfx
"%VENV_PY%" -m pip install -e ".[beta]"
if errorlevel 1 (
    echo [error] dependency install failed - see pip output above
    exit /b 4
)

rem GPU extra is optional - only pull it if NVIDIA hardware is around.
"%VENV_PY%" -c "import ctypes; ctypes.WinDLL('nvcuda.dll')" 2>nul
if not errorlevel 1 (
    echo       NVIDIA driver detected, installing onnxruntime-gpu...
    "%VENV_PY%" -m pip install --quiet -e ".[gpu]" >nul
    if errorlevel 1 (
        echo       ^(onnxruntime-gpu install failed, will fall back to CPU at runtime^)
    )
) else (
    echo       no NVIDIA driver detected, skipping GPU extras
)

rem --- 4. Bootstrap .env -------------------------------------
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo [4/4] Created .env from .env.example
    ) else (
        echo [warn] .env.example missing, cannot create .env
    )
) else (
    echo [4/4] .env already exists, left untouched
)

echo.
echo ============================================================
echo  Setup complete.
echo ============================================================
echo.
echo  Next steps:
echo    1. Open .env or use the board's «File - Connections settings»
echo       to set your LLM API key ^(OpenAI / Anthropic / DeepSeek / Yandex^).
echo    2. ^(Optional^) Start LM Studio with bge-m3 on :22227 for RAG embeddings.
echo    3. Run start_tutor_v2.bat to launch the tutor + the board.
echo.
echo  Test material:
echo    samples\test_courses\01_classical_ml\  (Classical ML pack + methodology)
echo    samples\test_courses\02_nlp_neural\    (NLP pack + methodology)
echo.

endlocal
