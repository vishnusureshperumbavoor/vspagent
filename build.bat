@echo off
REM VSP Agent Build Script for Windows

echo ====================================
echo VSP Agent - Build Script
echo ====================================
echo.

REM Check if build tools are installed
echo [1/4] Checking build tools...
pip show build >nul 2>&1
if %errorlevel% neq 0 (
    echo Installing build tools...
    pip install build twine
) else (
    echo Build tools already installed!
)
echo.

REM Clean previous builds
echo [2/4] Cleaning previous builds...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist vspagent.egg-info rmdir /s /q vspagent.egg-info
echo Previous builds cleaned!
echo.

REM Build the package
echo [3/4] Building package...
python -m build
if %errorlevel% neq 0 (
    echo ERROR: Build failed!
    pause
    exit /b 1
)
echo Package built successfully!
echo.

REM Check the package
echo [4/4] Checking package...
twine check dist/*
if %errorlevel% neq 0 (
    echo WARNING: Package check failed!
) else (
    echo Package check passed!
)
echo.

echo ====================================
echo Build Complete!
echo ====================================
echo.
echo Next steps:
echo 1. Test locally: pip install -e .
echo 2. Upload to PyPI: twine upload dist/*
echo.
echo See README.md for install and release steps.
echo.

pause


