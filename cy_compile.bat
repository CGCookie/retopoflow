@echo off
setlocal enabledelayedexpansion

:: Use Python 3.11 specifically (adjust path as necessary for latest Blender python version)
set PYTHON_PATH="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"

:: Get the directory of the batch script
cd "%~dp0"

"%PYTHON_PATH%" -m pip install --upgrade cython numpy
"%PYTHON_PATH%" cy_setup.py build_ext -i -v --inplace --force

if %errorlevel% neq 0 (
    echo Compilation failed.
    pause
    exit /b 1
)
