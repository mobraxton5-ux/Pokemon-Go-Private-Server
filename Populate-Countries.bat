@echo off
REM Double-click to open the "populate a country" page in your browser.
cd /d "%~dp0"
py populate_app.py
pause
