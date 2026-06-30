@echo off
cd /d "%~dp0"
set "PATH=%PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links"
.venv\Scripts\streamlit.exe run src\app.py
pause
