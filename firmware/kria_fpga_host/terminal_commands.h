#ifndef LDPC_TERMINAL_COMMANDS_H
#define LDPC_TERMINAL_COMMANDS_H
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <errno.h>
#define TERMINAL_PATH_CAP 768U
#define TERMINAL_LINE_CAP 1024U
typedef struct {
 char image[TERMINAL_PATH_CAP];
 float db;
 uint32_t limit,seed,width,height,no_noise,input_mode;
} TerminalSettings;
enum TerminalAction { TERM_EMPTY,TERM_HELP,TERM_STATUS,TERM_UPDATED,TERM_RUN,TERM_BAD };
static void terminal_defaults(TerminalSettings *s) {
 memset(s,0,sizeof(*s)); strcpy(s->image,"sample");
 s->db=3.0f; s->limit=20; s->seed=2026; s->width=128; s->height=96;
}
static int term_space(char c) { return c==' ' || c=='\t' || c=='\r' || c=='\n'; }
static char *term_trim(char *p) {
 while(term_space(*p)) ++p;
 size_t n=strlen(p); while(n && term_space(p[n-1])) p[--n]=0;
 return p;
}
static int term_equal(const char *a,const char *b) {
 while(*a && *b) {
  char c=*a++; if(c>='A' && c<='Z') c=(char)(c+'a'-'A');
  if(c!=*b++) return 0;
 }
 return *a==*b;
}
static int term_uint(const char *p,uint32_t maximum,uint32_t *out) {
 if(!*p || *p=='-') return 0;
 char *end; errno=0; unsigned long value=strtoul(p,&end,10);
 while(term_space(*end)) ++end;
 if(errno || end==p || *end || value>maximum) return 0;
 *out=(uint32_t)value; return 1;
}
static enum TerminalAction terminal_parse(TerminalSettings *s,char *line,const char **error) {
 char *cmd=term_trim(line),*arg=cmd;
 *error="Invalid command. Type help.";
 if(!*cmd) return TERM_EMPTY;
 while(*arg && !term_space(*arg)) ++arg;
 if(*arg) *arg++=0;
 arg=term_trim(arg);
 if(term_equal(cmd,"help") || term_equal(cmd,"?")) return *arg?TERM_BAD:TERM_HELP;
 if(term_equal(cmd,"status")) return *arg?TERM_BAD:TERM_STATUS;
 if(term_equal(cmd,"run")) return *arg?TERM_BAD:TERM_RUN;
 if(term_equal(cmd,"image") || term_equal(cmd,"llr")) {
  size_t n=strlen(arg);
  if(n>=2 && ((arg[0]=='"' && arg[n-1]=='"') || (arg[0]=='\'' && arg[n-1]=='\''))) {
   arg[n-1]=0; ++arg; n-=2;
  }
  if(!n || n>=sizeof(s->image)) { *error="Input path must contain 1..767 UTF-8 bytes."; return TERM_BAD; }
  memcpy(s->image,arg,n+1); s->input_mode=term_equal(cmd,"llr")?1U:0U; return TERM_UPDATED;
 }
 if(s->input_mode && (term_equal(cmd,"snr") || term_equal(cmd,"ebn0") ||
     term_equal(cmd,"seed") || term_equal(cmd,"size") || term_equal(cmd,"noise"))) {
  *error="Fixed LLR: SNR/seed/size/noise come from the dataset. Use image <path> to return to image mode.";
  return TERM_BAD;
 }
 if(term_equal(cmd,"snr") || term_equal(cmd,"ebn0")) {
  char *end; errno=0; float value=strtof(arg,&end);
  while(term_space(*end)) ++end;
  if(errno || end==arg || *end || !isfinite(value) || value<-10.0f || value>20.0f) {
   *error="Eb/N0 must be a finite number from -10 to 20 dB."; return TERM_BAD;
  }
  s->db=value; return TERM_UPDATED;
 }
 if(term_equal(cmd,"iter") || term_equal(cmd,"iterations")) {
  uint32_t value; if(!term_uint(arg,20,&value)) { *error="Iteration limit must be an integer from 0 to 20."; return TERM_BAD; }
  s->limit=value; return TERM_UPDATED;
 }
 if(term_equal(cmd,"seed")) {
  uint32_t value; if(!term_uint(arg,2147483647U,&value)) { *error="Seed must be an integer from 0 to 2147483647."; return TERM_BAD; }
  s->seed=value; return TERM_UPDATED;
 }
 if(term_equal(cmd,"size")) {
  if(strcmp(arg,"64")==0 || strcmp(arg,"64x48")==0) {s->width=64;s->height=48;}
  else if(strcmp(arg,"128")==0 || strcmp(arg,"128x96")==0) {s->width=128;s->height=96;}
  else if(strcmp(arg,"256")==0 || strcmp(arg,"256x192")==0) {s->width=256;s->height=192;}
  else {*error="Size must be 64, 128 or 256 (image fits 4:3 bounds).";return TERM_BAD;}
  return TERM_UPDATED;
 }
 if(term_equal(cmd,"noise")) {
  if(term_equal(arg,"off")) s->no_noise=1;
  else if(term_equal(arg,"on")) s->no_noise=0;
  else {*error="Use noise on or noise off.";return TERM_BAD;}
  return TERM_UPDATED;
 }
 return TERM_BAD;
}
#endif
