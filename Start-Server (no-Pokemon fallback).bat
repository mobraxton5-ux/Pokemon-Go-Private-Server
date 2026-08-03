@echo off
REM Fallback launcher: runs the server WITHOUT the game master, so the client
REM reaches the walkable map + PokeStops but shows NO wild Pokemon. Use this only
REM if the normal Start-Pokemon-GO-Server.exe gets the phone stuck on the loading
REM screen. Normally just double-click Start-Pokemon-GO-Server.exe instead.
set SERVE_GAME_MASTER=0
"%~dp0Start-Pokemon-GO-Server.exe"
pause
