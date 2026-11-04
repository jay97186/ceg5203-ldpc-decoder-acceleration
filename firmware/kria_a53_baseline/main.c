/* Kria A53 plain C baseline. Generated/edited with OpenAI Codex.
 * No FPGA accelerator / AXI DMA driver calls. Single A53 core, optimized C.
 * JTAG staging and staging<->cached-buffer copies are OUTSIDE timing.
 * Timer includes input/message initialization, NMS, stopping checks and loop.
 */
#include <stdint.h>
#include "xparameters.h"
#include "xiltimer.h"
#include "xil_mmu.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include "nms_decoder.h"
#define FRAMES_MAX 8192U
#define MAGIC 0x43505542U
static volatile uint32_t *const mb=(volatile uint32_t *)0x10000000UL;
static float input[FRAMES_MAX][384] __attribute__((aligned(64)));
static unsigned char output[FRAMES_MAX][384] __attribute__((aligned(64)));
static void barrier(void) { __asm__ volatile("dsb sy" ::: "memory"); }
int main(void) {
 Xil_ICacheEnable(); Xil_DCacheEnable();
 for(UINTPTR a=0x10000000UL;a<0x12000000UL;a+=0x200000UL)
  Xil_SetTlbAttributes(a,NORM_NONCACHE);
 for(unsigned i=0;i<64;++i) mb[i]=0;
 mb[1]=1; mb[2]=1; mb[9]=(uint32_t)(uint64_t)COUNTS_PER_SECOND;
 mb[10]=(uint32_t)((uint64_t)COUNTS_PER_SECOND>>32);
 mb[41]=XPAR_CPU_CORE_CLOCK_FREQ_HZ;
 barrier(); mb[0]=MAGIC;
 xil_printf("\r\nKRIA A53 CPU BASELINE READY (single core, plain C, per-word early stop)\r\nCPU_HZ=%u TIMER_HZ=%u\r\n",mb[41],mb[9]);
 unsigned last=0;
 for(;;) {
  unsigned seq=mb[3]; if(seq==last) continue;
  barrier(); last=seq; mb[2]=2;
  unsigned frames=mb[5],limit=mb[6];
  if(!frames || frames>FRAMES_MAX || limit>20) {
   mb[8]=1;mb[4]=seq;barrier();mb[2]=4;continue;
  }
  volatile const uint32_t *src=(volatile const uint32_t *)0x10200000UL;
  for(unsigned i=0;i<frames*384U;++i) {
   union { uint32_t bits; float value; } word; word.bits=src[i];
   input[i/384U][i%384U]=word.value;
  }
  unsigned histogram[21]={0},sum=0,maxused=0;
  XTime begin,end;
  XTime_GetTime(&begin);
  for(unsigned frame=0;frame<frames;++frame) {
   unsigned used;
   nms_decode(input[frame],output[frame],limit,&used);
   ++histogram[used];sum+=used;if(used>maxused)maxused=used;
  }
  XTime_GetTime(&end);
  uint64_t ticks=end-begin,hz=(uint64_t)COUNTS_PER_SECOND;
  uint64_t us=(ticks/hz)*1000000ULL+((ticks%hz)*1000000ULL)/hz;
  volatile unsigned char *packed=(volatile unsigned char *)0x11200000UL;
  for(unsigned i=0;i<frames*384U;++i) packed[i]=((unsigned char *)output)[i];
  mb[7]=frames;mb[8]=0;mb[11]=(uint32_t)ticks;mb[12]=(uint32_t)(ticks>>32);
  mb[13]=(uint32_t)us;mb[14]=(uint32_t)(us>>32);mb[15]=maxused;mb[16]=sum;
  mb[18]=frames*384U;
  for(unsigned i=0;i<=20;++i) mb[20+i]=histogram[i];
  mb[4]=seq;barrier();mb[2]=3;
  xil_printf("CPU DONE: frames=%u limit=%u CPU_DECODE_US=%u\r\n",frames,limit,(unsigned)us);
 }
}
