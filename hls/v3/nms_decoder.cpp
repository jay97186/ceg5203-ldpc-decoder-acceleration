#include "nms_decoder.h"
#include "nms_tables.h"
#include <cfloat>

// Generated/edited with OpenAI Codex.
// Validate C simulation, RTL co-simulation and implementation timing.

static float clip_message(float value) {
    if (value > 30.0f) return 30.0f;
    if (value < -30.0f) return -30.0f;
    return value;
}

static bool checks_pass(const unsigned char bits[NMS_N]) {
#pragma HLS INLINE

    bool failed[4] = {false, false, false, false};
#pragma HLS ARRAY_PARTITION variable=failed complete dim=1

    syndrome_groups:
    for (int base = 0; base < NMS_M; base += 4) {
#pragma HLS PIPELINE II=1

        for (int p = 0; p < 4; ++p) {
#pragma HLS UNROLL

            unsigned char parity = 0;

            for (int lane = 0; lane < NMS_DC; ++lane) {
#pragma HLS UNROLL
                parity ^=
                    bits[static_cast<int>(
                        NMS_CHECKS[base + p][lane])];
            }

            failed[p] = failed[p] || (parity != 0);
        }
    }

    return !(failed[0] || failed[1] ||
             failed[2] || failed[3]);
}

void nms_decode(
    const float llr_in[NMS_N],
    unsigned char decoded[NMS_N],
    unsigned int max_iterations,
    unsigned int *iterations_used
) {
#pragma HLS ARRAY_PARTITION variable=decoded complete dim=1

#pragma HLS ARRAY_PARTITION variable=NMS_VARIABLE_EDGES complete dim=2
#pragma HLS ARRAY_PARTITION variable=NMS_VARIABLE_EDGES block factor=12 dim=1

#pragma HLS ARRAY_PARTITION variable=NMS_CHECKS complete dim=2
#pragma HLS ARRAY_PARTITION variable=NMS_CHECKS cyclic factor=4 dim=1

    // This implementation targets the existing fixed QC-LDPC matrix:
    // N=384, M=192, DV=3, DC=6.
    static_assert(NMS_N == 384, "Expected NMS_N = 384");
    static_assert(NMS_M == 192, "Expected NMS_M = 192");
    static_assert(NMS_DV == 3, "Expected NMS_DV = 3");
    static_assert(NMS_DC == 6, "Expected NMS_DC = 6");
    static_assert(
        NMS_E == NMS_M * NMS_DC,
        "Unexpected edge count"
    );

    float llr[NMS_N];
#pragma HLS ARRAY_PARTITION variable=llr block factor=12 dim=1

    // Twelve banks support twelve consecutive writes
    // from two check nodes in the extrinsic stage.
    float q[NMS_E];
#pragma HLS ARRAY_PARTITION variable=q cyclic factor=12 dim=1

    float r[NMS_DV][NMS_N];
#pragma HLS ARRAY_PARTITION variable=r complete dim=1
#pragma HLS ARRAY_PARTITION variable=r cyclic factor=6 dim=2

    float posterior[NMS_N];
#pragma HLS ARRAY_PARTITION variable=posterior block factor=12 dim=1

    const float alpha = 0.75f;

    *iterations_used = 0;

    const unsigned int limit =
        max_iterations > NMS_MAX_ITERS
            ? NMS_MAX_ITERS
            : max_iterations;

    initialize_llr:
    for (int bit = 0; bit < NMS_N; ++bit) {
        llr[bit] = clip_message(llr_in[bit]);
        decoded[bit] = llr[bit] < 0.0f ? 1 : 0;
    }

    initialize_q:
    for (int check = 0; check < NMS_M; ++check) {
#pragma HLS PIPELINE II=1

        for (int lane = 0; lane < NMS_DC; ++lane) {
#pragma HLS UNROLL

            const int edge = check * NMS_DC + lane;
            const int bit =
                static_cast<int>(NMS_CHECKS[check][lane]);

            q[edge] = llr[bit];
        }
    }

    iterations:
    for (unsigned int iteration = 0;
         iteration < NMS_MAX_ITERS;
         ++iteration) {

        if (iteration >= limit || checks_pass(decoded)) {
            break;
        }

        // Check-node update.
        // Preserve minimum selection, ties and arithmetic order.
        check_nodes:
        for (int check = 0; check < NMS_M; ++check) {
            float min1 = FLT_MAX;
            float min2 = FLT_MAX;
            int min_lane = 0;
            bool negative_parity = false;

            for (int lane = 0; lane < NMS_DC; ++lane) {
                const float value =
                    q[check * NMS_DC + lane];

                const bool negative = value < 0.0f;
                const float magnitude =
                    negative ? -value : value;

                negative_parity ^= negative;

                if (magnitude < min1) {
                    min2 = min1;
                    min1 = magnitude;
                    min_lane = lane;
                } else if (magnitude < min2) {
                    min2 = magnitude;
                }
            }

            for (int lane = 0; lane < NMS_DC; ++lane) {
                const int edge = check * NMS_DC + lane;

                const bool outgoing_negative =
                    negative_parity ^ (q[edge] < 0.0f);

                const float magnitude =
                    alpha * (
                        lane == min_lane ? min2 : min1
                    );

                r[edge / NMS_N][edge % NMS_N] =
                    outgoing_negative
                        ? -magnitude
                        : magnitude;
            }
        }

        // Four independent variable-node updates per launch.
        // For the existing fixed table, the four addresses
        // in each r row use distinct cyclic-six banks.
        variable_node_quads:
        for (int group = 0;
             group < NMS_N / 4;
             ++group) {
#pragma HLS PIPELINE II=1

            for (int p = 0; p < 4; ++p) {
#pragma HLS UNROLL

                const int bit =
                    group + p * (NMS_N / 4);

                const int edge0 =
                    static_cast<int>(
                        NMS_VARIABLE_EDGES[bit][0]);

                const int edge1 =
                    static_cast<int>(
                        NMS_VARIABLE_EDGES[bit][1]);

                const int edge2 =
                    static_cast<int>(
                        NMS_VARIABLE_EDGES[bit][2]);

                float sum = r[0][edge0];
                sum = sum + r[1][edge1 - NMS_N];
                sum = sum + r[2][edge2 - 2 * NMS_N];

                posterior[bit] = llr[bit] + sum;

                decoded[bit] =
                    posterior[bit] < 0.0f ? 1 : 0;
            }
        }

        // Extrinsic update: two check nodes concurrently.
        // Each launch updates 2 * DC = 12 edges.
        // Achieved II must be checked in the synthesis report.
        extrinsic_check_pairs:
        for (int base = 0;
             base < NMS_M;
             base += 2) {
#pragma HLS PIPELINE II=1

            for (int p = 0; p < 2; ++p) {
#pragma HLS UNROLL

                const int check = base + p;

                for (int lane = 0;
                     lane < NMS_DC;
                     ++lane) {
#pragma HLS UNROLL

                    const int edge =
                        check * NMS_DC + lane;

                    const int bit =
                        static_cast<int>(
                            NMS_CHECKS[check][lane]);

                    const float own_message =
                        r[edge / NMS_N][edge % NMS_N];

                    q[edge] = clip_message(
                        posterior[bit] - own_message
                    );
                }
            }
        }

        *iterations_used = iteration + 1;
    }
}