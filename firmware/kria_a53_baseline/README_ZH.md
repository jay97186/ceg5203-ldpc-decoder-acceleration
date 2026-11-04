# Kria A53 純 C 對照測試

CPU 設定：1,333,333,008 Hz（約 1.333 GHz）；PL0 設定：99.999001 MHz（約 100 MHz）。
XTime 計時器為 99,999,001 Hz；不是 CPU 執行時脈。以上來自目前 pfv2 BSP / Vivado 設定，並非即時時脈量測。

本程式不呼叫 PL 解碼器或 AXI DMA。單核心 plain C，GCC -O3 -ffp-contract=off，float32。
使用與 FPGA 相同的 LDPC(384,194)、NMS alpha=.75、clip +/-30、每碼字零 syndrome 提前停止、最多20輪。
輸入直接重用 FPGA request_4 的 input_llr.f32（6081個碼字），沒有重新縮圖、加雜訊。
計時包含 NMS 初始化/校驗/更新及逐碼字控制，排除 JTAG、輸入輸出 staging copies、驗證、UART。
CPU I/D cache 開啟，運算 buffers 在 cacheable DDR；mailbox/JTAG staging 保持 non-cacheable。
先預熱一次，再量5次取中位數。FPGA對照目前是既有單次1119.457ms，嚴謹報告應也重複測量。

## Vitis 操作（保留原 FPGA App）
1. 等 FPGA 請求完成，關閉黑色圖片助手，保留 RealTerm。
2. 打開原 ldpc_dma_test 的 Settings > launch.json，新增獨立 launch configuration，取名 kria_cpu_baseline。
   使用 pfv2 的 FSBL、相同 A53 processor、Reset Entire System 勾選；可沿用現有 bitstream。
   在下方 processor/application 表格，把 Application ELF 路徑改為本資料夾的 kria_cpu_baseline.elf。
   此次使用已編譯 ELF，不必覆蓋原 main.c；不要按原 launch 的 Run。
3. 儲存並執行新的 launch（上方三角形）。RealTerm 應出現 KRIA A53 CPU BASELINE READY。
4. TASK: XSDB CONSOLE 輸入下列 source 指令（程式已 Run 後執行）：

    source {C:/Users/jay/Documents/Codex/2026-10-23/hi/outputs/kria_cpu_baseline/run_cpu.tcl}

   若尚未連接，先輸入 connect -url tcp:127.0.0.1:3121。
   腳本將先上傳資料，再預熱及量測。等待6筆 A53 run 和 DONE；執行期間不要按 Run / Stop。
5. 雙擊本資料夾 Analyze_Results.cmd。會驗證輸出及迭代 histogram 與原 FPGA 相同，輸出 comparison.json。
   speedup = A53 median ms / FPGA+DMA ms；大於1表示 FPGA 加速。
6. 完成後用原 ldpc_dma_test launch Run，再啟動圖片助手，便能恢復 FPGA RealTerm 模式。

## 交付與來源
main.c / nms_cpu.c / nms_decoder.h / nms_tables.h 是可在 Vitis standalone App 建置的來源。
若自行新建 App，使用 pfv2、A53 standalone、加入上述4檔、compiler設 -O3 -ffp-contract=off。
可直接執行 Build.ps1 重新產生本 ELF；不會修改原 FPGA App。
程式由 OpenAI Codex 協助產生/編輯；演算法及固定碼表源自現有 ldpc_pl_axis，請在簡報標註。
host_validation.json 是電腦執行相同 C 解碼的正確性驗證（與實際 FPGA逐位一致），不是 A53 latency。
目前未在板上執行本 A53 ELF，因此沒有填入或推估 A53 實測時間。
