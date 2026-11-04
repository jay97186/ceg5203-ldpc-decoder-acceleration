// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2025.1 (64-bit)
// Tool Version Limit: 2025.05
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XNMS_DECODE_AXIS_H
#define XNMS_DECODE_AXIS_H

#ifdef __cplusplus
extern "C" {
#endif

/***************************** Include Files *********************************/
#ifndef __linux__
#include "xil_types.h"
#include "xil_assert.h"
#include "xstatus.h"
#include "xil_io.h"
#else
#include <stdint.h>
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stddef.h>
#endif
#include "xnms_decode_axis_hw.h"

/**************************** Type Definitions ******************************/
#ifdef __linux__
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#else
typedef struct {
#ifdef SDT
    char *Name;
#else
    u16 DeviceId;
#endif
    u64 Control_BaseAddress;
} XNms_decode_axis_Config;
#endif

typedef struct {
    u64 Control_BaseAddress;
    u32 IsReady;
} XNms_decode_axis;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XNms_decode_axis_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XNms_decode_axis_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XNms_decode_axis_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XNms_decode_axis_ReadReg(BaseAddress, RegOffset) \
    *(volatile u32*)((BaseAddress) + (RegOffset))

#define Xil_AssertVoid(expr)    assert(expr)
#define Xil_AssertNonvoid(expr) assert(expr)

#define XST_SUCCESS             0
#define XST_DEVICE_NOT_FOUND    2
#define XST_OPEN_DEVICE_FAILED  3
#define XIL_COMPONENT_IS_READY  1
#endif

/************************** Function Prototypes *****************************/
#ifndef __linux__
#ifdef SDT
int XNms_decode_axis_Initialize(XNms_decode_axis *InstancePtr, UINTPTR BaseAddress);
XNms_decode_axis_Config* XNms_decode_axis_LookupConfig(UINTPTR BaseAddress);
#else
int XNms_decode_axis_Initialize(XNms_decode_axis *InstancePtr, u16 DeviceId);
XNms_decode_axis_Config* XNms_decode_axis_LookupConfig(u16 DeviceId);
#endif
int XNms_decode_axis_CfgInitialize(XNms_decode_axis *InstancePtr, XNms_decode_axis_Config *ConfigPtr);
#else
int XNms_decode_axis_Initialize(XNms_decode_axis *InstancePtr, const char* InstanceName);
int XNms_decode_axis_Release(XNms_decode_axis *InstancePtr);
#endif

void XNms_decode_axis_Start(XNms_decode_axis *InstancePtr);
u32 XNms_decode_axis_IsDone(XNms_decode_axis *InstancePtr);
u32 XNms_decode_axis_IsIdle(XNms_decode_axis *InstancePtr);
u32 XNms_decode_axis_IsReady(XNms_decode_axis *InstancePtr);
void XNms_decode_axis_EnableAutoRestart(XNms_decode_axis *InstancePtr);
void XNms_decode_axis_DisableAutoRestart(XNms_decode_axis *InstancePtr);

void XNms_decode_axis_Set_max_iterations(XNms_decode_axis *InstancePtr, u32 Data);
u32 XNms_decode_axis_Get_max_iterations(XNms_decode_axis *InstancePtr);
u32 XNms_decode_axis_Get_iterations_used(XNms_decode_axis *InstancePtr);
u32 XNms_decode_axis_Get_iterations_used_vld(XNms_decode_axis *InstancePtr);

void XNms_decode_axis_InterruptGlobalEnable(XNms_decode_axis *InstancePtr);
void XNms_decode_axis_InterruptGlobalDisable(XNms_decode_axis *InstancePtr);
void XNms_decode_axis_InterruptEnable(XNms_decode_axis *InstancePtr, u32 Mask);
void XNms_decode_axis_InterruptDisable(XNms_decode_axis *InstancePtr, u32 Mask);
void XNms_decode_axis_InterruptClear(XNms_decode_axis *InstancePtr, u32 Mask);
u32 XNms_decode_axis_InterruptGetEnabled(XNms_decode_axis *InstancePtr);
u32 XNms_decode_axis_InterruptGetStatus(XNms_decode_axis *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
