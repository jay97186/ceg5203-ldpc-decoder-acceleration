@echo off
setlocal
title LDPC FPGA - teacher demo
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "DEMO_PYTHON=C:\Users\jay\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%DEMO_PYTHON%" (
  "%DEMO_PYTHON%" "common\demo_ui.py" --version v3
) else (
  py -3 "common\demo_ui.py" --version v3
)
if errorlevel 1 echo ERROR: Read the message above. No successful average is fabricated.
pause
