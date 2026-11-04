@echo off
setlocal
cd /d "%~dp0"
set "LDPC_PYTHON=%~dp0..\yolo_sw_sim\.venv\Scripts\python.exe"
if not exist "%LDPC_PYTHON%" set "LDPC_PYTHON=C:\Users\jay\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%LDPC_PYTHON%" (
    "%LDPC_PYTHON%" "%~dp0ldpc_bf_image_sim.py" %*
) else (
    py -3 "%~dp0ldpc_bf_image_sim.py" %*
)
if errorlevel 1 echo See the error above. CUDA requires NVIDIA GPU and CUDA-enabled PyTorch.
pause
