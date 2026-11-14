@echo off
setlocal

set "COMFY_ROOT=C:\Users\Rion\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI"
set "COMFY_PY=%COMFY_ROOT%\standalone-env\python.exe"
set "MAKEPOINT=%LOCALAPPDATA%\makepoint\makepoint.py"

echo.
echo ========================================
echo        ComfyUI Makepoint
echo ========================================
echo.

if not exist "%COMFY_PY%" (
    echo [ERROR] ComfyUI Python not found:
    echo %COMFY_PY%
    echo.
    pause
    exit /b 1
)

if not exist "%MAKEPOINT%" (
    echo [ERROR] makepoint.py not found:
    echo %MAKEPOINT%
    echo.
    echo Please put makepoint.py here:
    echo %COMFY_ROOT%
    echo.
    pause
    exit /b 1
)

"%COMFY_PY%" "%MAKEPOINT%" %*

set "EXITCODE=%ERRORLEVEL%"

echo.
if "%EXITCODE%"=="0" (
    echo [OK] Operation completed.
) else (
    echo [ERROR] makepoint exited with code %EXITCODE%.
)

echo.

endlocal
exit /b %EXITCODE%