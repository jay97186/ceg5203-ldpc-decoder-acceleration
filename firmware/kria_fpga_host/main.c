#include <stdint.h>
#include <string.h>
#include "xparameters.h"
#include "xaxidma.h"
#include "xnms_decode_axis.h"
#include "xiltimer.h"
#include "xil_mmu.h"
#include "xil_printf.h"

#define N 384U
#define MAX_FRAMES 8192U
#define MB_ADDR 0x10000000UL
#define INPUT_ADDR 0x10200000UL
#define OUTPUT_ADDR 0x11200000UL
#define MAGIC 0x4C445055U
#define READY 1U
#define BUSY 2U
#define DONE 3U
#define ERROR 4U
#define CANCELLED 5U

static XAxiDma dma;
static XNms_decode_axis decoder;
static volatile u32 *const mb = (volatile u32 *)MB_ADDR;

static void barrier(void)
{
    __asm__ volatile("dsb sy" ::: "memory");
}

/* Initialize the generated driver without a BSP config table. */
static int decoder_initialize(void)
{
    XNms_decode_axis_Config config = {0};

    config.Control_BaseAddress = XPAR_NMS_DECODE_AXIS_0_BASEADDR;
    return XNms_decode_axis_CfgInitialize(&decoder, &config);
}

/* Host phases may overlap hardware execution.
 * WAIT includes DMA, PL, stream stalls and ARM polling.
 * UART output and conversions occur outside the batch timer. */
static XTime profile_setup_ticks;
static XTime profile_wait_ticks;
static XTime profile_finish_ticks;

static void profile_print_time(const char *name, u64 ticks, u64 total)
{
    const u64 hz = (u64)COUNTS_PER_SECOND;
    const u64 us = (ticks / hz) * 1000000ULL +
                   ((ticks % hz) * 1000000ULL) / hz;
    const u32 percent100 =
        total ? (u32)((ticks * 10000ULL) / total) : 0U;

    xil_printf("%s=%u.%03u ms (%u.%02u percent)\r\n",
               name,
               (u32)(us / 1000ULL),
               (u32)(us % 1000ULL),
               percent100 / 100U,
               percent100 % 100U);
}

static void profile_print_batch(unsigned seq,
                                unsigned complete,
                                int error,
                                u64 ticks)
{
    const u64 sum = (u64)profile_setup_ticks +
                    (u64)profile_wait_ticks +
                    (u64)profile_finish_ticks;
    const u64 remainder = ticks >= sum ? ticks - sum : 0;

    xil_printf(
        "\r\nHOST PHASE PROFILE: request=%u completed_frames=%u error=%d\r\n",
        seq, complete, error);

    profile_print_time("BATCH_TOTAL", ticks, ticks);
    profile_print_time("SETUP_AND_LAUNCH", profile_setup_ticks, ticks);
    profile_print_time("WAIT_DMA_AND_IP", profile_wait_ticks, ticks);
    profile_print_time(
        "FINISH_AND_BOOKKEEPING", profile_finish_ticks, ticks);
    profile_print_time("LOOP_AND_TIMER_REMAINDER", remainder, ticks);

    xil_printf(
        "WAIT is DMA + PL + ARM polling, not pure decoder time.\r\n");
    xil_printf(
        "Timer reads add profiling overhead. "
        "Failed runs are partial measurements.\r\n");
}

static int decode_frame(unsigned frame, unsigned *used)
{
    const UINTPTR tx = INPUT_ADDR + (UINTPTR)frame * N * 4U;
    const UINTPTR rx = OUTPUT_ADDR + (UINTPTR)frame * N * 4U;

    XTime start, now;
    XTime profile_begin, profile_started, profile_done, profile_end;
    int done = 0;

    XTime_GetTime(&profile_begin);

    XAxiDma_IntrAckIrq(
        &dma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DMA_TO_DEVICE);
    XAxiDma_IntrAckIrq(
        &dma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DEVICE_TO_DMA);

    (void)XNms_decode_axis_IsDone(&decoder);

    if (XAxiDma_SimpleTransfer(
            &dma, rx, N * 4U, XAXIDMA_DEVICE_TO_DMA)
            != XST_SUCCESS)
        return 2;

    XNms_decode_axis_Start(&decoder);

    if (XAxiDma_SimpleTransfer(
            &dma, tx, N * 4U, XAXIDMA_DMA_TO_DEVICE)
            != XST_SUCCESS)
        return 3;

    XTime_GetTime(&profile_started);
    start = profile_started;

    for (;;) {
        const u32 a = XAxiDma_ReadReg(
            dma.RegBase,
            XAXIDMA_TX_OFFSET + XAXIDMA_SR_OFFSET);
        const u32 b = XAxiDma_ReadReg(
            dma.RegBase,
            XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);

        if ((a | b) & XAXIDMA_ERR_ALL_MASK)
            return 4;

        if (XNms_decode_axis_IsDone(&decoder))
            done = 1;

        if (done &&
            !XAxiDma_Busy(&dma, XAXIDMA_DMA_TO_DEVICE) &&
            !XAxiDma_Busy(&dma, XAXIDMA_DEVICE_TO_DMA))
            break;

        XTime_GetTime(&now);

        if (now - start > (XTime)COUNTS_PER_SECOND * 5U)
            return 5;
    }

    XTime_GetTime(&profile_done);

    *used = XNms_decode_axis_Get_iterations_used(&decoder);

    profile_setup_ticks += profile_started - profile_begin;
    profile_wait_ticks += profile_done - profile_started;

    XTime_GetTime(&profile_end);
    profile_finish_ticks += profile_end - profile_done;

    return *used > 20U ? 6 : 0;
}

/* UART carries commands and PC paths.
 * The PC helper reads files and supplies LLRs via JTAG. */
#include "xuartps_hw.h"
#include "terminal_commands.h"

#define CB_ADDR 0x10001000UL
#define CB_MAGIC 0x4C445052U
#define CB_PATH (CB_ADDR + 0x100UL)

static volatile u32 *const cb = (volatile u32 *)CB_ADDR;
static TerminalSettings settings;
static char line_input[TERMINAL_LINE_CAP];

static unsigned line_length;
static unsigned line_overflow;
static unsigned last_was_cr;
static unsigned request_seq;
static unsigned last_reply;

static void console_prompt(void)
{
    xil_printf("ldpc> ");
}

static void console_status(void)
{
    if (settings.input_mode) {
        xil_printf(
            "llr=%s\r\n"
            "iter=%u; fixed input: SNR/seed/size/noise from dataset, "
            "no new noise.\r\n",
            settings.image, settings.limit);
        return;
    }

    int milli = (int)(
        settings.db * 1000.0f +
        (settings.db < 0 ? -0.5f : 0.5f));
    unsigned magnitude =
        (unsigned)(milli < 0 ? -milli : milli);

    xil_printf(
        "image=%s\r\n"
        "Eb/N0=%s%u.%03u dB iter=%u seed=%u size=%ux%u noise=%s\r\n",
        settings.image,
        milli < 0 ? "-" : "",
        magnitude / 1000U,
        magnitude % 1000U,
        settings.limit,
        settings.seed,
        settings.width,
        settings.height,
        settings.no_noise ? "OFF" : "ON");
}

static void console_command(char *line)
{
    const char *error;
    enum TerminalAction action =
        terminal_parse(&settings, line, &error);

    if (action == TERM_HELP) {
        xil_printf(
            "image <Windows path> | image sample | "
            "llr <dataset llr.f32 path>\r\n"
            "snr <Eb/N0 dB, -10..20> | iter <0..20>\r\n"
            "seed <0..2147483647> | size <64|128|256>\r\n"
            "noise <on|off> | status | run | help\r\n"
            "PC bridge must stay open. "
            "Smaller dB means stronger noise.\r\n");
    } else if (action == TERM_STATUS) {
        console_status();
    } else if (action == TERM_UPDATED) {
        xil_printf("OK\r\n");
    } else if (action == TERM_BAD) {
        xil_printf("ERROR: %s\r\n", error);
    } else if (action == TERM_RUN) {
        if (request_seq != last_reply) {
            xil_printf("BUSY: wait for this run to finish.\r\n");
        } else {
            u32 db_bits;
            memcpy(&db_bits, &settings.db, 4);

            cb[5] = db_bits;
            cb[6] = settings.limit;
            cb[7] = settings.seed;
            cb[8] = settings.width;
            cb[9] = settings.height;
            cb[10] = settings.input_mode ? 2U : settings.no_noise;
            cb[11] = (u32)strlen(settings.image);
            cb[12] = 0;

            volatile uint8_t *dst =
                (volatile uint8_t *)CB_PATH;

            for (unsigned i = 0; i <= cb[11]; ++i)
                dst[i] = (uint8_t)settings.image[i];

            cb[4] = 1;
            barrier();
            cb[2] = ++request_seq;
            barrier();

            xil_printf(
                "REQUEST %u: waiting for PC image preparation "
                "and FPGA DMA...\r\n",
                request_seq);
        }
    }

    console_prompt();
}

static void console_init(void)
{
    terminal_defaults(&settings);

    for (unsigned i = 0; i < 64U; ++i)
        cb[i] = 0;

    cb[1] = 2;
    barrier();
    cb[0] = CB_MAGIC;

    xil_printf(
        "\r\nLDPC FPGA RealTerm Console [HOST PROFILE]\r\n"
        "Vitis Run active. PC helper: "
        "Start_Picture_Bridge_After_Vitis_Run.cmd; "
        "UART: 115200 8N1, no flow control.\r\n"
        "Fixed dataset LLR supported: llr <path>, iter 20, run. "
        "Type help for image mode.\r\n");

    console_status();
    console_prompt();
}

static void console_poll(void)
{
    static unsigned heartbeat_divider;

    if (++heartbeat_divider >= 4096U) {
        ++cb[25];
        heartbeat_divider = 0;
    }

    if (request_seq != last_reply && cb[3] == request_seq) {
        barrier();
        last_reply = request_seq;

        if (cb[12]) {
            xil_printf(
                "\r\nERROR: PC bridge/run error %u. "
                "See the PC bridge window.\r\n",
                cb[12]);
        } else {
            xil_printf(
                "\r\nDONE: frames=%u payload_errors=%u/%u "
                "unconverged_frames=%u\r\n"
                "FPGA_PLUS_DMA_US=%u "
                "(excludes JTAG and PC preparation)\r\n"
                "Images and metrics saved by the PC bridge.\r\n",
                cb[13], cb[14], cb[15], cb[19], cb[16]);
        }

        console_prompt();
    }

    for (unsigned count = 0;
         count < 32U &&
         XUartPs_IsReceiveData(XPAR_XUARTPS_0_BASEADDR);
         ++count) {
        unsigned char c = (unsigned char)XUartPs_ReadReg(
            XPAR_XUARTPS_0_BASEADDR, XUARTPS_FIFO_OFFSET);

        if (c == '\n' && last_was_cr) {
            last_was_cr = 0;
            continue;
        }

        last_was_cr = (c == '\r');

        if (c == '\r' || c == '\n') {
            xil_printf("\r\n");
            line_input[line_length] = 0;

            if (line_overflow) {
                xil_printf("ERROR: command line too long.\r\n");
                console_prompt();
            } else {
                console_command(line_input);
            }

            line_length = 0;
            line_overflow = 0;
        } else if (c == 8 || c == 127) {
            if (line_length && !line_overflow) {
                --line_length;
                xil_printf("\b \b");
            }
        } else if (c >= 32) {
            if (line_length + 1U < sizeof(line_input) &&
                !line_overflow) {
                line_input[line_length++] = (char)c;
                XUartPs_SendByte(XPAR_XUARTPS_0_BASEADDR, c);
            } else {
                line_overflow = 1;
            }
        }
    }
}

int main(void)
{
    /* Non-cacheable exchange area shared by JTAG, ARM and DMA.
     * ELF sections must remain outside this reserved area. */
    for (UINTPTR addr = MB_ADDR;
         addr < 0x12000000UL;
         addr += 0x200000UL)
        Xil_SetTlbAttributes(addr, NORM_NONCACHE);

    for (unsigned i = 0; i < 64U; ++i)
        mb[i] = 0;

    mb[1] = 1;
    mb[9] = (u32)(u64)COUNTS_PER_SECOND;
    mb[10] = (u32)((u64)COUNTS_PER_SECOND >> 32);

    XAxiDma_Config *cfg =
        XAxiDma_LookupConfig(XPAR_XAXIDMA_0_BASEADDR);

    if (!cfg ||
        XAxiDma_CfgInitialize(&dma, cfg) != XST_SUCCESS ||
        XAxiDma_HasSg(&dma) ||
        decoder_initialize() != XST_SUCCESS) {
        mb[8] = 1;
        mb[2] = ERROR;
        barrier();
        mb[0] = MAGIC;

        xil_printf("FAIL: DMA or LDPC driver initialization.\r\n");
        for (;;) {}
    }

    XAxiDma_IntrDisable(
        &dma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DMA_TO_DEVICE);
    XAxiDma_IntrDisable(
        &dma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DEVICE_TO_DMA);

    mb[2] = READY;
    barrier();
    mb[0] = MAGIC;

    console_init();

    unsigned last_seq = 0;

    for (;;) {
        console_poll();

        const unsigned seq = mb[3];
        if (seq == last_seq)
            continue;

        barrier();
        last_seq = seq;

        const unsigned frames = mb[5];
        const unsigned limit = mb[6];

        mb[7] = 0;
        mb[8] = 0;
        mb[2] = BUSY;

        if (!frames || frames > MAX_FRAMES || limit > 20U) {
            mb[8] = 7;
            mb[4] = seq;
            barrier();
            mb[2] = ERROR;
            continue;
        }

        unsigned histogram[21] = {0};
        unsigned sum = 0;
        unsigned maximum = 0;
        unsigned complete = 0;
        int error = 0;
        XTime start, end;

        profile_setup_ticks = 0;
        profile_wait_ticks = 0;
        profile_finish_ticks = 0;

        XNms_decode_axis_Set_max_iterations(&decoder, limit);

        XTime_GetTime(&start);

        for (unsigned frame = 0; frame < frames; ++frame) {
            if (mb[17]) {
                error = 8;
                break;
            }

            unsigned used = 0;
            error = decode_frame(frame, &used);

            if (error)
                break;

            ++histogram[used];
            sum += used;

            if (used > maximum)
                maximum = used;

            ++complete;

            if ((complete & 31U) == 0U)
                mb[7] = complete;
        }

        XTime_GetTime(&end);

        const u64 ticks = end - start;
        const u64 hz = (u64)COUNTS_PER_SECOND;
        const u64 us =
            (ticks / hz) * 1000000ULL +
            ((ticks % hz) * 1000000ULL) / hz;

        mb[7] = complete;
        mb[11] = (u32)ticks;
        mb[12] = (u32)(ticks >> 32);
        mb[13] = (u32)us;
        mb[14] = (u32)(us >> 32);
        mb[15] = maximum;
        mb[16] = sum;

        for (unsigned i = 0; i <= 20U; ++i)
            mb[20U + i] = histogram[i];

        /* Print only after timing, before publishing DONE. */
        profile_print_batch(seq, complete, error, ticks);

        /* Pack uint32 output bits into bytes after timing.
         * Forward in-place packing is safe. */
        if (!error) {
            volatile u32 *src = (volatile u32 *)OUTPUT_ADDR;
            volatile uint8_t *dst =
                (volatile uint8_t *)OUTPUT_ADDR;

            for (unsigned i = 0; i < frames * N; ++i) {
                u32 bit = src[i];

                if (bit > 1U) {
                    error = 9;
                    break;
                }

                dst[i] = (uint8_t)bit;
            }
        }

        mb[18] = error ? 0U : frames * N;
        mb[19] = frames * N * 4U;
        mb[8] = (u32)error;
        mb[4] = seq;

        barrier();
        mb[2] = error == 8 ? CANCELLED : error ? ERROR : DONE;
        barrier();
    }
}