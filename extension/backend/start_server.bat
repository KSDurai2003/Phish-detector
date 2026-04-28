@echo off
title Silent Guard API Server
echo ============================================================
echo   Silent Guard - Phishing URL Detection API
echo   Starting backend server on http://127.0.0.1:5000
echo ============================================================
echo.

REM Install dependencies if missing
pip install flask flask-cors onnxruntime numpy --quiet

REM Start server
python "%~dp0api_server.py"
pause
