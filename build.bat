@echo off
REM Build the server straight into the RELEASE folder -- that is the only place
REM a build should ever land. Building into dist\ and copying by hand is how you
REM end up testing one exe while the phone talks to another one.
REM
REM The server must be CLOSED first: Windows locks a running .exe and the build
REM fails at the very last step with "Permission denied".

setlocal
set HERE=%~dp0
set RELEASE=%HERE%..\..\RELEASE

tasklist /FI "IMAGENAME eq Start-Pokemon-GO-Server.exe" 2>nul | find /I "Start-Pokemon-GO-Server.exe" >nul
if not errorlevel 1 (
  echo.
  echo   The server is running, so its .exe cannot be replaced.
  echo   Close the server window, then run this again.
  echo.
  exit /b 1
)

py -m PyInstaller "%HERE%Start-Pokemon-GO-Server.spec" --distpath "%RELEASE%" --noconfirm --clean
if errorlevel 1 exit /b 1

echo.
echo   Built to: %RELEASE%\Start-Pokemon-GO-Server.exe
echo.
