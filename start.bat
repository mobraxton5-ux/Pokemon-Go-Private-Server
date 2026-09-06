@echo off
REM Double-click to start the PoGO private server (DNS + game server in one).
REM Optional: pass the IP the phone should point at, e.g.  start.bat 203.0.113.7
cd /d "%~dp0"
py run.py %*
pause
