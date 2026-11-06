# LDPC Decoder Acceleration on Kria KV260: Cortex-A53 vs. HLS FPGA

NUS CEG5203 final project. A QC-LDPC(384,194) Normalized Min-Sum decoder is used to
recover an image sent through a noisy channel, and the same decoding task is run on
the Kria KV260 Cortex-A53 CPU and on an HLS accelerator in the programmable logic (PL),
connected through AXI DMA. Three HLS versions (v1 → v3) were measured on the board.

Team: LIN KAI-CHIEH, XIONG BINZHI

## Results (Kria KV260, measured on the board)

Same input for every platform: teammate dataset `image_01_awgn_3db`
(256×192 RGB, 1,179,648 payload bits, 6,081 codewords, Eb/N0 3 dB, LLR SHA-256 `534fa0ed…`),
max 20 iterations, per-codeword early stop when the syndrome is zero.

| Platform | Clock | Latency (image_01) | Speedup vs A53 |
|---|---|---|---|
| Cortex-A53, plain C, 1 core, `-O3` | 1.333 GHz | **1680.82 ms** (median of 5) | 1.00× |
| FPGA + DMA, HLS **v1** | PL 100 MHz | **1061.96 ms** (mean of 5) | 1.58× |
| FPGA + DMA, HLS **v2** | PL 100 MHz | **368.56 ms** (mean of 5) | 4.56× |
| FPGA + DMA, HLS **v3** | PL 125 MHz | **214.17 ms** (mean of 5) | **7.85×** |

- Every run used 1 warm-up + 5 measured runs; run-to-run spread is below 0.1 ms for the FPGA.
- Correctness: all versions and the A53 produce the same decoded bits as the teammate's
  reference decoder; 120 / 1,179,648 payload bits remain wrong after 20 iterations
  (this is the channel, not a decoder error). Mean actual iterations: 4.53.
- v1 and v2 were also run on all 10 dataset images: 1060.26 ms and 368.00 ms average.
- HLS report: one decoding iteration took 2957 cycles in v1 and 892 cycles in v2
  (`docs/hls_screenshots/`).

Raw data: `results/kria_fpga/v*_summary.csv`, per-run records `results/kria_fpga/v*_image_01_runs.csv`
(each run: `dataset_reference_bit_mismatches = 0`) and `firmware/kria_a53_baseline/a53_fixed_reports.txt`.

### Timing scope

| | Included | Excluded |
|---|---|---|
| FPGA + DMA | A53 control loop, DMA setup, PS DDR ↔ PL transfers, PL decoding, completion polling | PC image/dataset preparation, JTAG upload/readback, image reconstruction, validation, UART |
| A53 CPU | message initialization, NMS updates, syndrome checks, per-codeword early stop | JTAG, staging copies, validation, output, UART |

The FPGA number is **FPGA + DMA latency**, not a pure PL-core latency. PL clock and CPU
clock are configuration values (A53 1,333,333,008 Hz; timer 99,999,001 Hz).

## Real RF channel decoded on the Kria FPGA

The ZCU111 photo link (`zcu111_photo_link/`) and the Kria decoder are connected: an ADC capture of the
QPSK 30×30 photo is demodulated on the PC, and its LLRs (8 codewords) are decoded by the HLS decoder in
the Kria PL through the ADC Capture UI (`host/teacher_demo/vN/Start_ADC_Capture_UI.cmd`).

Board test, HLS **v3**, capture `qpsk30_pep-5p2dB` (DAC −5.2 dBFS, 303 / 3072 channel bit errors):

| Iteration limit | FPGA + DMA | Remaining bit errors | Image | FPGA vs PC NMS |
|---|---|---|---|---|
| 0 | 0.130 ms | 303 | CRC failed | 0 bits |
| 15 | 0.394 ms | 0 | CRC OK | 0 bits |
| 20 | 0.396 ms | 0 | CRC OK | 0 bits |

Mean actual iterations at limits 15 and 20: 8.00 (read from the PL decoder's register), matching the
per-codeword convergence of the PC reference (3, 8, 7, 7, 3, 7, 14, 15). With only 8 codewords the time is
dominated by per-codeword control and DMA, so it is not comparable with the full-image latency above.
Single run; only v3 was tested with the ADC capture.

## Decoder

| Item | Value |
|---|---|
| Code | custom QC-LDPC, N = 384, K = 194, M = 192, Z = 64, check degree 6, variable degree 3, 1,152 edges |
| Algorithm | flooding Normalized Min-Sum, α = 0.75, float32, messages clipped to ±30 |
| Stopping | at most 20 iterations; each codeword stops once its syndrome is zero |

## System

```
PC helper ──JTAG──> PS DDR (LLRs)            RealTerm/UART: commands + summary only
                     │
          Cortex-A53 host ──AXI DMA──> PL nms_decode_axis (HLS) ──AXI DMA──> PS DDR (decoded bits)
```

The board runs standalone (no Linux, no SD card). The PC tools in `host/teacher_demo/` drive XSDB
(installed with Vitis) directly: switch the boot mode to JTAG, reset, program the bitstream, run the FSBL,
download the controller ELF, upload LLRs to DDR and read the decoded bits back — the same steps as a
Vitis *Run*, without opening the IDE. The controller only configures AXI DMA, starts the HLS IP and
polls it; there is no software decoder in the firmware.

## Repository layout

| Path | Content |
|---|---|
| `hls/common/` | HLS top `nms_decode_axis` (AXI-Stream wrapper), headers, code tables, C/RTL testbench and test vectors (identical for v1–v3) |
| `hls/v1`, `hls/v2`, `hls/v3` | `nms_decoder.cpp` of each version (the only file that changes) |
| `hls/step1_reference/` | first non-AXIS HLS reference and `generate_vectors.py` (builds `nms_tables.h` / `nms_vectors.h`) |
| `vivado/v1..v3/` | Vivado block designs (`design_1.bd`) and the exported hardware (`ldpc_vN.xsa`, includes the bitstream) used on the board |
| `firmware/kria_fpga_host/` | Vitis standalone A53 controller for the FPGA path (DMA, timer, RealTerm commands) and the HLS-generated driver |
| `firmware/kria_a53_baseline/` | A53 plain-C NMS baseline, XSDB scripts, analysis scripts and the raw timer reports |
| `host/teacher_demo/` | PC tools used for the demonstration: XSDB/JTAG bridge, fixed-LLR batch runner (1 warm-up + 5 runs) and three UIs with one result card per iteration limit — Custom image, Fixed teammate LLR, and **ZCU111 ADC capture → Kria FPGA** (`ADC_Capture_使用說明.txt`) |
| `results/kria_fpga/` | per-version summary CSVs (mean/median/min/max, payload errors, iterations) |
| `docs/` | HLS / Vivado screenshots, board start-up guide (Chinese) |
| `teammate/` | XIONG BINZHI's PC CPU decoder (`pc_cpu/LDPC.c`) and dataset generator (code tables, images, manifest) |
| `python_simulation/` | early software simulation of LDPC image transmission (bit-flipping / NMS) |
| `zcu111_photo_link/` | extra demo: LDPC-coded photo over a real ZCU111 RFSoC DAC → ADC link, BPSK/QPSK, iteration-by-iteration correction ([README](zcu111_photo_link/README.md)) |

## Building

- **HLS** (Vitis HLS 2025.1, part `xck26-sfvc784-2LV-c`, top `nms_decode_axis`):
  add all files from `hls/common/` plus `hls/vN/nms_decoder.cpp`; clock 10 ns for v1/v2,
  8 ns for v3. Run C simulation, synthesis, RTL co-simulation, then export the IP.
- **Vivado**: block design with the Zynq UltraScale+ PS, AXI DMA and the exported HLS IP
  (`vivado/vN/design_1.bd`); generate the bitstream and export the `.xsa`.
- **Vitis**: platform from the `.xsa`, standalone A53 application from `firmware/kria_fpga_host/`.
- The exported `.xsa` of v1–v3 is included (`vivado/vN/`); stand-alone `.bit` and ELF files are not,
  they are rebuilt from the `.xsa` and the sources above.

The helper scripts (`*.cmd`, `*.tcl`, some JSON configs) were written for the original lab
PC and contain its absolute paths; adjust them before use.

## Not included

- PC x86 CPU and OpenCL GPU results: the teammate's C decoder is in `teammate/pc_cpu/`;
  the GPU code and its measurements are not part of this repository.
- Large datasets (LLR files, transmitted codewords) and Vivado/Vitis build directories.

## Acknowledgements

The LDPC code tables and the fixed-LLR dataset were produced by the teammate's dataset
generator (`teammate/dataset/`). Parts of the code and documentation were written with AI
assistance (OpenAI Codex, Anthropic Claude); all reported numbers come from board measurements
stored in this repository. The HLS-generated driver files (`xnms_decode_axis*`) are
AMD/Xilinx-generated code.
