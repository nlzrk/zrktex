@echo off
setlocal

echo [zrktex] Closing any running instance...
taskkill /F /IM zrktex.exe >nul 2>&1
timeout /t 1 /nobreak >nul

echo [zrktex] Building...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name zrktex ^
    --collect-all matplotlib ^
    --collect-all mpl_toolkits ^
    zrktex.py

if %errorlevel% neq 0 (
    echo.
    echo [zrktex] BUILD FAILED.
    pause
    exit /b 1
)

echo.
echo [zrktex] Build complete: dist\zrktex.exe
pause
