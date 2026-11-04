$ErrorActionPreference='Stop'
$bsp='C:\Users\jay\Desktop\CEG_5203\Final_Project\ldpc_ws\pfv2\export\pfv2\sw\standalone_psu_cortexa53_0'
$env:PATH='C:\Xilinx\2025.1\gnu\aarch64\nt\aarch64-none\x86_64-oesdk-mingw32\usr\bin;C:\Xilinx\2025.1\Vitis\gnu\aarch64\nt\aarch64-none\bin;'+$env:PATH
$gcc='C:\Xilinx\2025.1\Vitis\gnu\aarch64\nt\aarch64-none\bin\aarch64-none-elf-gcc.exe'
& $gcc -DSDT -O3 -g -ffp-contract=off -Wall -Wextra "-specs=$bsp/Xilinx.spec" "-I$bsp/include" (Join-Path $PSScriptRoot 'main.c') (Join-Path $PSScriptRoot 'nms_cpu.c') "-L$bsp/lib" "-Wl,-T,$PSScriptRoot/lscript.ld" '-Wl,--start-group' -lxilstandalone -lxiltimer -lxil -lm -lgcc -lc '-Wl,--end-group' -o (Join-Path $PSScriptRoot 'kria_cpu_baseline.elf')
if($LASTEXITCODE -ne 0){throw 'A53 build failed'}
Write-Output 'A53 ELF build succeeded'
