@echo off
setlocal
title LDPC v2 - Vitis Run first - FIRST IMAGE - 5 measured runs
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "DEMO_PYTHON=C:\Users\jay\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%DEMO_PYTHON%" (
  "%DEMO_PYTHON%" "..\common\demo_runner.py" --version v2 --attach-running --case image_01_awgn_3db
) else (
  py -3 "..\common\demo_runner.py" --version v2 --attach-running --case image_01_awgn_3db
)
if errorlevel 1 echo ERROR: Read the message above. No successful average is fabricated.
pause
