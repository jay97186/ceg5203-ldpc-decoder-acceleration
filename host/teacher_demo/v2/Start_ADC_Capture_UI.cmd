@echo off
setlocal
title LDPC v2 - ZCU111 ADC capture decoded on the FPGA
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "DEMO_PYTHON=C:\Users\jay\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%DEMO_PYTHON%" (
  "%DEMO_PYTHON%" "..\common\adc_ui.py" --version v2
) else (
  py -3 "..\common\adc_ui.py" --version v2
)
if errorlevel 1 echo ERROR: Read the message above.
pause
