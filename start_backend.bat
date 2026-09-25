@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Research Navigator - backend (setup + run)

echo ============================================
echo  Research Navigator - backend
echo  (first run auto-installs, then starts)
echo  http://127.0.0.1:8000/api/health
echo  Swagger: http://127.0.0.1:8000/docs
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  echo Please install Python 3.10+ from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during install.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment .venv ...
  python -m venv .venv
  if errorlevel 1 ( echo [ERROR] Failed to create venv. & pause & exit /b 1 )
) else (
  echo [1/3] .venv already exists, skip.
)

echo [2/3] Installing dependencies (first time may take 1-3 minutes) ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ( echo [ERROR] pip install failed. Check your network and retry. & pause & exit /b 1 )

if not exist ".env" (
  echo [3/3] Creating .env from .env.example ...
  copy ".env.example" ".env" >nul
) else (
  echo [3/3] .env already exists, skip.
)

echo.
echo ============================================
echo  Starting backend ...
echo  Health : http://127.0.0.1:8000/api/health
echo  Swagger: http://127.0.0.1:8000/docs
echo  KEEP THIS WINDOW OPEN. Press Ctrl+C to stop.
echo ============================================
echo.
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
