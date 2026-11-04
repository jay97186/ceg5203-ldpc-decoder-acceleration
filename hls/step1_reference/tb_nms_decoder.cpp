#include "nms_decoder.h"
#include "nms_vectors.h"
#include <cstdio>

int main() {
    unsigned int failures = 0;
    for (int test = 0; test < NMS_NUM_TESTS; ++test) {
        unsigned char decoded[NMS_N];
        unsigned int used = 999;
        nms_decode(NMS_TEST_LLR[test], decoded, NMS_TEST_LIMIT[test], &used);
        unsigned int mismatches = 0;
        for (int bit = 0; bit < NMS_N; ++bit) {
            if (decoded[bit] != NMS_TEST_EXPECTED[test][bit]) ++mismatches;
        }
        if (mismatches || used != NMS_TEST_USED[test]) {
            ++failures;
            std::printf("FAIL test=%d %s: bit mismatches=%u, iterations=%u expected=%u\n",
                        test, NMS_TEST_NAMES[test], mismatches, used, NMS_TEST_USED[test]);
        }
    }
    if (failures) {
        std::printf("FAIL: %u / %d cases disagreed with Python NMS.\n", failures, NMS_NUM_TESTS);
        return 1;
    }
    std::printf("PASS: all %d Python-reference cases matched (bits and iteration counts).\n", NMS_NUM_TESTS);
    return 0;
}
