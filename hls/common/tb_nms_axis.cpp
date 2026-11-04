#include "nms_axis.h"
#include "nms_vectors.h"
#include <cstdio>
#include <cstring>
int main() {
    static_assert(sizeof(float) == 4 && sizeof(unsigned int) == 4,
                  "Protocol needs 32-bit float and unsigned int");
    unsigned int failures = 0;
    for (int test = 0; test < NMS_NUM_TESTS; ++test) {
        hls::stream<nms_axis_word> input("input"), output("output");
        for (int i = 0; i < NMS_N; ++i) {
            unsigned int raw;
            std::memcpy(&raw, &NMS_TEST_LLR[test][i], sizeof(float));
            nms_axis_word packet;
            packet.data = raw;
            packet.keep = 0xF;
            packet.strb = 0xF;
            packet.last = (i == NMS_N - 1);
            input.write(packet);
        }
        unsigned int used = 999;
        nms_decode_axis(input, output, NMS_TEST_LIMIT[test], used);
        unsigned int errors = 0;
        for (int i = 0; i < NMS_N; ++i) {
            if (output.empty()) { ++errors; break; }
            const nms_axis_word packet = output.read();
            if (packet.data.to_uint() != NMS_TEST_EXPECTED[test][i]) ++errors;
            if (packet.keep.to_uint() != 0xF || packet.strb.to_uint() != 0xF) ++errors;
            if (packet.last.to_uint() != static_cast<unsigned int>(i == NMS_N - 1)) ++errors;
        }
        if (!input.empty() || !output.empty()) ++errors;
        if (used != NMS_TEST_USED[test]) ++errors;
        if (errors) {
            ++failures;
            std::printf("FAIL test=%d %s errors=%u used=%u expected=%u\n",
                        test, NMS_TEST_NAMES[test], errors, used, NMS_TEST_USED[test]);
        }
    }
    if (failures) { std::printf("FAIL: %u AXI-stream cases failed.\n", failures); return 1; }
    std::printf("PASS: all %d AXI-stream cases matched (bits, iterations, packet length and sidebands).\n", NMS_NUM_TESTS);
    return 0;
}
