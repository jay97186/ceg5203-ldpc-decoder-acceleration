@echo off
setlocal
title LDPC v1 v2 v3 - fixed teammate benchmark
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "DEMO_PYTHON=C:\Users\jay\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%DEMO_PYTHON%" (
  "%DEMO_PYTHON%" "common\demo_runner.py" --version all
) else (
  py -3 "common\demo_runner.py" --version all
)
if errorlevel 1 echo ERROR: Read the message above. No successful average is fabricated.
pause
