#include "nms_axis.h"
#include <cstring>
void nms_decode_axis(hls::stream<nms_axis_word> &llr_stream,
                     hls::stream<nms_axis_word> &decoded_stream,
                     unsigned int max_iterations,
                     unsigned int &iterations_used) {
#pragma HLS INTERFACE axis port=llr_stream
#pragma HLS INTERFACE axis port=decoded_stream
#pragma HLS INTERFACE s_axilite port=max_iterations bundle=control
#pragma HLS INTERFACE s_axilite port=iterations_used bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    float llr[NMS_N];
    unsigned char bits[NMS_N];
    unsigned int used = 0;
    // Fixed-length protocol. Input TLAST/KEEP are not validated by this wrapper.
    receive_llrs:
    for (int i = 0; i < NMS_N; ++i) {
#pragma HLS PIPELINE II=1
        const nms_axis_word packet = llr_stream.read();
        unsigned int raw = packet.data.to_uint();
        // Reinterpret IEEE-754 bits, not a numeric integer-to-float conversion.
        std::memcpy(&llr[i], &raw, sizeof(float));
    }
    nms_decode(llr, bits, max_iterations, &used);
    iterations_used = used;
    send_bits:
    for (int i = 0; i < NMS_N; ++i) {
#pragma HLS PIPELINE II=1
        nms_axis_word packet;
        // One decoded bit per uint32 word, NOT packed bits.
        packet.data = static_cast<unsigned int>(bits[i]);
        packet.keep = 0xF;
        packet.strb = 0xF;
        packet.last = (i == NMS_N - 1);
        decoded_stream.write(packet);
    }
}
