// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2025.1 (64-bit)
// Tool Version Limit: 2025.05
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2025 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xnms_decode_axis.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XNms_decode_axis_CfgInitialize(XNms_decode_axis *InstancePtr, XNms_decode_axis_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Control_BaseAddress = ConfigPtr->Control_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XNms_decode_axis_Start(XNms_decode_axis *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_AP_CTRL) & 0x80;
    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XNms_decode_axis_IsDone(XNms_decode_axis *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XNms_decode_axis_IsIdle(XNms_decode_axis *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XNms_decode_axis_IsReady(XNms_decode_axis *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XNms_decode_axis_EnableAutoRestart(XNms_decode_axis *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_AP_CTRL, 0x80);
}

void XNms_decode_axis_DisableAutoRestart(XNms_decode_axis *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_AP_CTRL, 0);
}

void XNms_decode_axis_Set_max_iterations(XNms_decode_axis *InstancePtr, u32 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_MAX_ITERATIONS_DATA, Data);
}

u32 XNms_decode_axis_Get_max_iterations(XNms_decode_axis *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_MAX_ITERATIONS_DATA);
    return Data;
}

u32 XNms_decode_axis_Get_iterations_used(XNms_decode_axis *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_ITERATIONS_USED_DATA);
    return Data;
}

u32 XNms_decode_axis_Get_iterations_used_vld(XNms_decode_axis *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_ITERATIONS_USED_CTRL);
    return Data & 0x1;
}

void XNms_decode_axis_InterruptGlobalEnable(XNms_decode_axis *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_GIE, 1);
}

void XNms_decode_axis_InterruptGlobalDisable(XNms_decode_axis *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_GIE, 0);
}

void XNms_decode_axis_InterruptEnable(XNms_decode_axis *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_IER);
    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_IER, Register | Mask);
}

void XNms_decode_axis_InterruptDisable(XNms_decode_axis *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_IER);
    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_IER, Register & (~Mask));
}

void XNms_decode_axis_InterruptClear(XNms_decode_axis *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XNms_decode_axis_WriteReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_ISR, Mask);
}

u32 XNms_decode_axis_InterruptGetEnabled(XNms_decode_axis *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_IER);
}

u32 XNms_decode_axis_InterruptGetStatus(XNms_decode_axis *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XNms_decode_axis_ReadReg(InstancePtr->Control_BaseAddress, XNMS_DECODE_AXIS_CONTROL_ADDR_ISR);
}

