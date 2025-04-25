@echo off
setlocal enabledelayedexpansion

:: Script requires Blender version (e.g., "4.3" or "4.4") as the first argument
if "%~1"=="" (
    echo Error: Missing Blender version argument.
    echo Usage: cy_compile.bat [version]
    echo Example: cy_compile.bat 4.4
    pause
    exit /b 1
)
set BLENDER_TARGET_VERSION=%~1

:: === Configuration for Different Blender Versions ===
:: Adjust PYTHON_PATH values for your system if needed!

if "%BLENDER_TARGET_VERSION%"=="4.3" (
    echo --- Configuring for Blender 4.3 ---
    : REM Assuming 3.11.9 for 4.3
    set PYTHON_PATH="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    : REM THE Cython version really 0.29.30, but we can use 3.0.11 for now as it's supported and 0.X.X gives issues as a lot of things change.
    set CYTHON_VERSION=3.0.11
    set NUMPY_VERSION=1.24.4
    set OUTPUT_SUFFIX=43
) else if "%BLENDER_TARGET_VERSION%"=="4.4" (
    echo --- Configuring for Blender 4.4 ---
    : REM Assuming 3.11.11 for 4.4 - CHANGE IF DIFFERENT
    set PYTHON_PATH="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    set CYTHON_VERSION=3.0.11
    set NUMPY_VERSION=1.26.4
    set OUTPUT_SUFFIX=44
) else (
    echo Error: Unsupported Blender version "%BLENDER_TARGET_VERSION%". Only "4.3" or "4.4" supported.
    pause
    exit /b 1
)

:: Define the output directory based on version
set BASE_CY_DIR=retopoflow\cy
set TYPES_CY_DIR=%BASE_CY_DIR%\bl_types
set OUTPUT_DIR=%BASE_CY_DIR%\compiled\%OUTPUT_SUFFIX%

:: Get the directory of the batch script
cd "%~dp0"

:: Install specific dependencies for the target version (no --upgrade)
echo Installing dependencies: numpy==%NUMPY_VERSION% cython==%CYTHON_VERSION%
"%PYTHON_PATH%" -m pip install numpy==%NUMPY_VERSION% cython==%CYTHON_VERSION%
if %errorlevel% neq 0 (
    echo Dependency installation failed.
    pause
    exit /b 1
)

:: Run the build script (compiles inplace next to .pyx files)
echo Running Cython build (build_ext --inplace)...
"%PYTHON_PATH%" cy_setup.py build_ext --inplace --force --dev --blender-version %BLENDER_TARGET_VERSION%
if %errorlevel% neq 0 (
    echo Compilation failed.
    pause
    exit /b 1
)

:: --- File moving is now handled by cy_setup.py --- 
echo Build successful. Artifact moving delegated to cy_setup.py.

echo --- Compilation process for Blender %BLENDER_TARGET_VERSION% successful --- 

:: pause
exit /b 0
