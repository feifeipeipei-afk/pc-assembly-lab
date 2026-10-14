@echo off
cd /d "%~dp0"

echo ==================================================
echo   Quiz App  -  Computer Assembly ^& Repair
echo --------------------------------------------------
echo   Student : http://127.0.0.1:5001
echo   Admin   : http://127.0.0.1:5001/admin
echo   LAN     : http://172.16.145.205:5001
echo ==================================================
echo.
echo Starting... keep this window OPEN while teaching.
echo.

".venv\Scripts\python.exe" app.py

echo.
echo [!] Server stopped.
pause
