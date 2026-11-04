#ifndef NMS_AXIS_H
#define NMS_AXIS_H
#include "nms_decoder.h"
#include <ap_axi_sdata.h>
#include <hls_stream.h>
typedef ap_axiu<32, 0, 0, 0> nms_axis_word;
void nms_decode_axis(hls::stream<nms_axis_word> &llr_stream,
                     hls::stream<nms_axis_word> &decoded_stream,
                     unsigned int max_iterations,
                     unsigned int &iterations_used);
#endif
