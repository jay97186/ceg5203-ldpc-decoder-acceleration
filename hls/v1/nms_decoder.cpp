#include "nms_decoder.h"
#include "nms_tables.h"
#include <cfloat>

static float clip_message(float value) {
    if (value > 30.0f) return 30.0f;
    if (value < -30.0f) return -30.0f;
    return value;
}

static bool checks_pass(const unsigned char bits[NMS_N]) {
    bool valid = true;
    for (int check = 0; check < NMS_M; ++check) {
        unsigned char parity = 0;
        for (int lane = 0; lane < NMS_DC; ++lane) {
            parity ^= bits[static_cast<int>(NMS_CHECKS[check][lane])];
        }
        if (parity != 0) valid = false;
    }
    return valid;
}

void nms_decode(const float llr_in[NMS_N],
                unsigned char decoded[NMS_N],
                unsigned int max_iterations,
                unsigned int *iterations_used) {
    // V1: three conflict-free message banks, one per QC check block row.
    // Keep float32 arithmetic order and early stopping identical to V0.
    float llr[NMS_N];
    float q[NMS_E];
    float r[NMS_DV][NMS_N];
#pragma HLS ARRAY_PARTITION variable=r complete dim=1
#pragma HLS ARRAY_PARTITION variable=r cyclic factor=6 dim=2
    float posterior[NMS_N];
    const float alpha = 0.75f;

    *iterations_used = 0;
    const unsigned int limit = max_iterations > NMS_MAX_ITERS
        ? NMS_MAX_ITERS : max_iterations;
    for (int bit = 0; bit < NMS_N; ++bit) {
        llr[bit] = clip_message(llr_in[bit]);
        decoded[bit] = llr[bit] < 0.0f ? 1 : 0;
    }
    for (int check = 0; check < NMS_M; ++check) {
        for (int lane = 0; lane < NMS_DC; ++lane) {
            q[check * NMS_DC + lane] = llr[static_cast<int>(NMS_CHECKS[check][lane])];
        }
    }

    for (unsigned int iteration = 0; iteration < NMS_MAX_ITERS; ++iteration) {
        if (iteration >= limit || checks_pass(decoded)) break;

        // Check nodes: sign parity, minimum and second minimum.
        for (int check = 0; check < NMS_M; ++check) {
            float min1 = FLT_MAX;
            float min2 = FLT_MAX;
            int min_lane = 0;
            bool negative_parity = false;
            for (int lane = 0; lane < NMS_DC; ++lane) {
                const float value = q[check * NMS_DC + lane];
                const bool negative = value < 0.0f;
                const float magnitude = negative ? -value : value;
                negative_parity ^= negative;
                if (magnitude < min1) {
                    min2 = min1;
                    min1 = magnitude;
                    min_lane = lane;
                } else if (magnitude < min2) {
                    // Includes ties: the second minimum can equal the first.
                    min2 = magnitude;
                }
            }
            for (int lane = 0; lane < NMS_DC; ++lane) {
                const int edge = check * NMS_DC + lane;
                const bool outgoing_negative = negative_parity ^ (q[edge] < 0.0f);
                const float magnitude = alpha * (lane == min_lane ? min2 : min1);
                r[edge / NMS_N][edge % NMS_N] = outgoing_negative ? -magnitude : magnitude;
            }
        }

        // Each variable has exactly one edge in each of the three banks.
        // The generated table was checked for this property before making V1.
        variable_nodes:
        for (int bit = 0; bit < NMS_N; ++bit) {
#pragma HLS PIPELINE II=1
            const int edge0 = static_cast<int>(NMS_VARIABLE_EDGES[bit][0]);
            const int edge1 = static_cast<int>(NMS_VARIABLE_EDGES[bit][1]);
            const int edge2 = static_cast<int>(NMS_VARIABLE_EDGES[bit][2]);
            float sum = r[0][edge0];
            sum = sum + r[1][edge1 - NMS_N];
            sum = sum + r[2][edge2 - 2 * NMS_N];
            posterior[bit] = llr[bit] + sum;
            decoded[bit] = posterior[bit] < 0.0f ? 1 : 0;
        }

        // Extrinsic message: remove the destination check's own contribution.
        for (int check = 0; check < NMS_M; ++check) {
            for (int lane = 0; lane < NMS_DC; ++lane) {
                const int edge = check * NMS_DC + lane;
                q[edge] = clip_message(posterior[static_cast<int>(NMS_CHECKS[check][lane])] - r[edge / NMS_N][edge % NMS_N]);
            }
        }
        *iterations_used = iteration + 1;
    }
}
