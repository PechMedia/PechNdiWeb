@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  PECH NDI-to-WebRTC Streaming Bridge Server
echo ============================================================
echo  Config: settings.json
echo  URL:    http://localhost:8123
echo  REST:   http://localhost:8123/api/stream/control
echo ============================================================
echo.

if exist "PECH_NDI_WebRTC.exe" (
    PECH_NDI_WebRTC.exe --config settings.json %*
) else (
    python main.py --config settings.json %*
)

if errorlevel 1 (
    echo.
    echo [ERROR] Server exited with code %errorlevel%
    pause
)
