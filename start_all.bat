@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   Start BOTH backend and frontend
echo ============================================
echo.

if not exist "start_backend.bat" (
  echo [ERROR] start_backend.bat not found in %CD%
  pause
  exit /b 1
)
if not exist "start_frontend.bat" (
  echo [ERROR] start_frontend.bat not found.
  echo Please put start_frontend.bat in the same root folder.
  pause
  exit /b 1
)

echo [1/2] Opening BACKEND window, port 8000 ...
start "RN-Backend" /D "%~dp0" cmd /k start_backend.bat

echo [2/2] Opening FRONTEND window, port 5173 ...
start "RN-Frontend" /D "%~dp0" cmd /k start_frontend.bat

echo.
echo URLs:
echo   Backend health : http://127.0.0.1:8000/api/health
echo   Frontend app   : http://localhost:5173/AI-coding/
echo.
echo Waiting 8 seconds for them to boot, then opening the frontend page ...
timeout /t 8 >nul
start "" http://localhost:5173/AI-coding/

echo Done. Two windows were opened - keep BOTH of them running.
exit /b 0
