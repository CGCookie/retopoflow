@echo off
setlocal enabledelayedexpansion

:: Use Python 3.11 specifically (adjust path as necessary for latest Blender python version)
set PYTHON_PATH="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

:: Get the directory of the batch script
cd "%~dp0"

:: Blender 4.3 - Python 3.11.9 - Cython '0.29.30' - Numoy '1.24.x'
:: Blender 4.4 - Python 3.11.11 - Cython '3.0.11' - Numoy '1.26.4'
set CYTHON_VERSION=3.0.11
set NUMPY_VERSION=1.26.4

"%PYTHON_PATH%" -m pip install --upgrade numpy==%NUMPY_VERSION% cython==%CYTHON_VERSION%
"%PYTHON_PATH%" cy_setup.py build_ext -i -v --inplace --force --dev

if %errorlevel% neq 0 (
    echo Compilation failed.
    pause
    exit /b 1
)
