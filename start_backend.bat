@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================
echo  Research Navigator - backend
echo  http://127.0.0.1:8000/api/health
echo  Swagger: http://127.0.0.1:8000/docs
echo ============================================
echo.

"%PY%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
pause
