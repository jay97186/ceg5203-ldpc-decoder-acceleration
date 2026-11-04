#ifndef NMS_DECODER_H
#define NMS_DECODER_H

// Fixed-code, floating-point functional baseline; no AXI/DMA wrapper yet.
// Generated/edited with OpenAI Codex. Validate before hardware use.
enum {
    NMS_N = 384,
    NMS_K = 194,
    NMS_M = 192,
    NMS_DC = 6,
    NMS_DV = 3,
    NMS_E = 1152,
    NMS_MAX_ITERS = 20
};

// Input: finite float32 channel LLRs in [-30, 30]. Positive means bit 0.
// Output: all N codeword bits, not only the K information bits.
// max_iterations is clamped to 20; zero is valid.
// Early exit on zero syndrome matches the frozen decisions of Python NMS.
void nms_decode(const float llr_in[NMS_N],
                unsigned char decoded[NMS_N],
                unsigned int max_iterations,
                unsigned int *iterations_used);

#endif
