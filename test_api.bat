@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Research Navigator - API smoke test

echo ============================================
echo  Auto test: main API + empty keyword (6 cases)
echo  It starts its own temp server on port 8123.
echo  Your running backend on port 8000 is not affected.
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Please run run_backend_setup.bat first.
  echo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" scripts\smoke_test.py
echo.
echo ============================================
echo  Done. Check each [PASS] / [FAIL] above.
echo ============================================
pause
