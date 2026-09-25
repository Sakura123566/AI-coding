@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0frontend"
title Research Navigator - frontend setup and run

echo ============================================
echo  Frontend dependency install plus dev server
echo  Folder: %CD%
echo ============================================
echo.

if not exist "package.json" (
  echo [ERROR] package.json not found.
  echo This script must sit in the PROJECT ROOT, next to the frontend folder.
  echo Current folder: %CD%
  echo.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found. Please install Node.js first.
  echo Download: https://nodejs.org/
  echo.
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo [1/2] Installing frontend dependencies, this may take 1 to 5 minutes.
  call npm config set registry https://registry.npmmirror.com
  call npm install
  if errorlevel 1 (
    echo [FAILED] npm install failed. See messages above.
    pause
    exit /b 1
  )
) else (
  echo [1/2] node_modules already exists, skip install.
)

echo [2/2] Starting dev server.
echo       Open: http://localhost:5173/AI-coding/
echo       Keep this window OPEN. Press Ctrl+C to stop.
echo.
call npm run dev
echo.
echo Dev server stopped.
pause
