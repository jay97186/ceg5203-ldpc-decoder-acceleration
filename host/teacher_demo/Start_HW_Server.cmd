@echo off
setlocal
title LDPC FPGA - Xilinx hw_server
echo Keep this window open while using LDPC FPGA Image Lab.
echo If another hw_server already owns port 3121, use the existing one.
echo.
call "C:\Xilinx\2025.1\Vitis\bin\hw_server.bat"
echo.
echo hw_server has stopped. Read the message above.
pause
