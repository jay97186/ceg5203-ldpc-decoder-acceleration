# 第一步：在 Vitis 2025.1 跑 NMS C Simulation

本資料夾與 `for_xiong` 分開，不更動給隊友的精簡 Python 套件。

本階段只驗證 decoder 核心，不需要 Kria、不需要 DMA、不需要 PYNQ，也尚未產生可上板的完整加速器。

## 目前檔案

| 檔案 | 用途 | HLS 分類 |
|---|---|---|
| `nms_decoder.cpp` | 可綜合風格的 NMS C++ 核心 | Design source |
| `nms_decoder.h` | 固定參數與 top function 宣告 | Design header |
| `nms_tables.h` | 從 Python 匯出的節點連接表 | Design header |
| `tb_nms_decoder.cpp` | 自動比較 Python 參考結果的測試程式 | Testbench |
| `nms_vectors.h` | 125 組輸入與 Python 實際判決 | Testbench header |
| `generate_vectors.py` | 重產生 tables/vectors，不加入 HLS | 工具 |
| `vectors_metadata.json` | seed、參考程式 SHA256 與規格 | 記錄 |

`nms_vectors.h` 只屬於 testbench，不能放進硬體核心；原始正確碼字不是用來替代 decoder 輸出的答案。錯誤率高、未收斂的案例也必須與 Python 實際判決一致。

## 操作步驟

1. 開啟 **Vitis Unified IDE 2025.1**。
2. 開啟你要使用的 workspace，建立新的 **HLS Component**，命名 `ldpc_nms_v0`。
3. Configuration File 選新建空白設定檔。此步先使用 GUI，不需要自己寫 Tcl。
4. 在 **Design Files** 加入 `nms_decoder.cpp`、`nms_decoder.h`、`nms_tables.h`。
5. 將 **Top Function** 設成 `nms_decode`。不是 `main`。
6. 在 **Test Bench Files** 加入 `tb_nms_decoder.cpp`、`nms_vectors.h`。測試程式的 `main()` 只在 testbench。
7. 選擇 KV260/K26 對應的 part。一般商規 KV260 為 `xck26-sfvc784-2LV-c`；請與隊友現有 Vivado 專案的 part 核對。
8. Settings 的 **flow_target 選 Vivado IP**，不要選 Vitis kernel。初始 clock 設 **10 ns / 100 MHz**（介面若用另一種單位，填相同頻率）。
9. 完成 component 建立。確認這個 component 是 active。
10. 在 Flow Navigator 的 **C SIMULATION** 下按 **Run**。這一步先不要按 C Synthesis 或生成 bitstream。

如果勾選 Copy Sources，務必把上述 header 一起加入，避免複製 cpp 後找不到同目錄的 header。若出現 `file not found`，檢查來源檔案和 include search path。

## 正確結果

Testbench 應顯示：

```text
PASS: all 125 Python-reference cases matched (bits and iteration counts).
```

接著工具應顯示 `CSim done with 0 errors` 或相應的成功狀態。若 testbench 顯示 FAIL 或 main 回傳非零，不能繼續上板。

執行完成後把 Console 的最後結果貼給我。下一階段才檢查 C Synthesis report，再增加 AXI-Stream 包裝並與隊友的 DMA 介面對接。

## 核心規格與比較條件

- N=384、K=194、M=192、check degree=6、variable degree=3、edges=1152。
- 固定自訂 QC 碼，matrix seed=5203、Z=64，與目前 Python 相同。
- 浮點 float32、alpha=0.75、訊息 clipping ±30。
- 輸入是有限且已限制到 [-30,30] 的 channel LLR；正值偏向 bit 0。
- 輸出完整384個 codeword bits；還原圖片要再使用資訊位元位置表。
- 最多20輪，傳入0輪時只做初始判決。
- 若 syndrome=0，提前返回；這與 Python 後續各輪維持相同判決的結果等價，但實際時間政策不同。正式 C/FPGA benchmark 要讓兩邊停止規則一致。
- `iterations_used` 是實際執行的更新輪數；收到超過20的上限會限制為20。
- 第一版沒有 unroll、pipeline、AXI、DMA 或定點最佳化。不可把這一步的 C simulation 時間當 FPGA latency。

## 驗證狀態

Python 參考資料已產生。提供的 testbench 會比對不同通道與0/1/2/5/20輪結果。工具執行環境未找到可直接呼叫的 Vitis/C++ compiler，因此尚未在此環境完成真正的 C compilation、HLS synthesis 或 RTL simulation；要由你在 2025.1 執行上述 C Simulation 確認。

## 重新產生測資（一般不需要）

```powershell
python generate_vectors.py
```

需要 NumPy 與目前 Python reference 所需的 Pillow。預設 reference 是相鄰 `../for_xiong/ldpc/ldpc.py`；若單獨搬走本資料夾，使用 `--reference` 指定原本 Python 程式。

程式由 OpenAI Codex 依本次專題需求產生，請保留 AI 使用及來源標註。

官方操作參考：

- https://docs.amd.com/r/2025.1-English/ug1399-vitis-hls/Creating-an-HLS-Component
- https://docs.amd.com/r/2025.1-English/ug1399-vitis-hls/Running-C-Simulation
