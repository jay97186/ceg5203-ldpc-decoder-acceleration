# LDPC NMS AXI-Stream wrapper
Top: nms_decode_axis. Part: xck26-sfvc784-2LV-c; clock: 10ns; Vivado IP.

Design files: nms_axis.cpp, nms_axis.h, nms_decoder.cpp, nms_decoder.h, nms_tables.h.
Testbench files: tb_nms_axis.cpp, nms_vectors.h. Do not add the old testbench main.
Run C simulation, synthesis and RTL cosimulation before packaging.
New wrapper not yet compiled or validated in Vitis.

## Fixed packet protocol: one codeword per invocation
Input: 384 float32 LLRs, 32-bit stream, 1536 bytes. Positive means bit 0.
Transfer raw IEEE-754 bits, not numeric uint32 conversions. Finite inputs only.
Output: 384 uint32 words containing 0 or 1, 1536 bytes, NOT packed bits.
All 384 codeword bits are returned; extract information bits on PS separately.
KEEP=STRB=0xF, TLAST only on word 383 for both streams.
Wrapper counts 384 input words and does not validate input TLAST or KEEP.
Short input can block indefinitely; provide exactly 384 words each invocation.
AXI-Lite control: max_iterations (clamped to 20), iterations_used, start/done.
Read iterations_used after done; use the generated register map for offsets.

## Future DMA integration
Use matching 32-bit DMA stream widths. PYNQ send buffer float32[384]; receive
buffer uint32[384]. Each transfer is 1536 bytes. Arm receive DMA, configure and
start IP, start send DMA; wait for both transfers and IP done. Maintain cache
coherency through PYNQ buffer APIs. This core receives, decodes, then sends;
there is no cross-frame overlap. AXI-Lite is for control, streams for data.

Copied V1 core and 125-case golden vectors are byte-identical to originals.
Tests compare bits, iteration counts, output count, TLAST, KEEP and STRB.
C simulation does not validate real DMA or hardware backpressure.
Prepared with OpenAI Codex.
