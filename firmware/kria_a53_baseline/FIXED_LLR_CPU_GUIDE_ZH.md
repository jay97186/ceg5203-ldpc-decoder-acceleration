# A53 固定 LLR 量測

使用原本 kria_cpu_baseline.elf，不需要重新編譯。
先關閉圖片助手，在 Vitis launch.json 選 kria_cpu_baseline，按上方三角形 Run。
等 RealTerm 印出 KRIA A53 CPU BASELINE READY。
在 TASK: XSDB CONSOLE 執行：

```
source {C:/Users/jay/Documents/Codex/2026-10-23/hi/outputs/kria_cpu_baseline/run_cpu_fixed_llr.tcl}
```

這次直接上傳隊友 cases/image_01_awgn_3db/llr.f32；預熱1次、量5次，排除JTAG及staging copy。
此檔SHA256已確認為534fa0ed7245b4d461ecfcd53ce437f5ab72eb76d0d400228e3c3df3412cd2b0。
腳本不重置或載入ELF；必須先透過Vitis重新Run CPU設定，使mailbox為fresh READY。
等6筆A53 run與DONE，再執行 Analyze_Fixed_Results.cmd。
它會驗證A53輸出與新的固定資料FPGA結果以及隊友reference逐位一致，檢查實際迭代histogram。
輸出 comparison_fixed_llr.json，不覆蓋原先重新生成LLR的量測。
比較對象：FPGA realterm_20261024_235333_529436/request_1，1121.042429ms（單次）。
正式報告建議FPGA亦重複量測取中位數。
目前僅準備腳本，尚無本輪固定LLR的A53實測結果。
