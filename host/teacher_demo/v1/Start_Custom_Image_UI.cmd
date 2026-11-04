@echo off
setlocal
title LDPC v1 custom image UI
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "DEMO_PYTHON=C:\Users\jay\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%DEMO_PYTHON%" (
  "%DEMO_PYTHON%" "..\common\custom_launcher.py" --version v1
) else (
  py -3 "..\common\custom_launcher.py" --version v1
)
if errorlevel 1 echo ERROR: Read the message above. No successful average is fabricated.
pause
