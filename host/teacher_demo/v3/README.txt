v3: FPGA/PL 125 MHz
Run_All_Images_5x.cmd: all 10 teammate fixed-LLR cases, one warmup then five measured runs per image.
Start_Fixed_LLR_UI.cmd: fixed noisy input, no averaging.
Start_Custom_Image_UI.cmd: optional custom image / regenerated AWGN; not for fixed-input benchmark comparisons.
All launchers initialize the corresponding FPGA automatically; no Vitis Run or RealTerm command is needed.
