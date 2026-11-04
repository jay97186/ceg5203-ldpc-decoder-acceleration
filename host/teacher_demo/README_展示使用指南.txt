老師展示套件 / LDPC FPGA Teacher Demo

一、內容
v1、v2、v3 各自有獨立 bitstream、FSBL、設定與啟動按鈕。
v1/v2 約100 MHz，v3 約125 MHz；v3加速同時包含架構與時脈變更。
三版共用同一份已成功運作的ARM控制程式，統一主機端量測範圍。
hardware_manifest.json記錄硬體來源與SHA256。舊版bitstream取自各自XSA，不依資料夾中的可能過期runs結果判定。
source_snapshot 是來源參考，未保證能完全重建每個歷史硬體；實際展示以封裝bitstream及其hash為準。

二、展示前
1. 板子接電源與JTAG USB。此套件使用standalone，不需要Linux或SD卡。
2. 停止Vitis Run/Debug，關閉舊PC bridge、其他FPGA UI，不要同時控制板子。
3. 若hw_server尚未啟動，雙擊Start_HW_Server.cmd並保持視窗開啟。
4. 首次可雙擊Verify_Package.cmd，驗證10張圖的LLR、碼表、參考輸出及硬體hash，不會操作板子。
5. 程式使用這台電腦已安裝的Python及Vitis 2025.1。搬到別台電腦需修改啟動檔的Python路徑及各版config.json的xsdb路徑；需NumPy、Pillow、Tk。

三、正式五次平均測試
雙擊Run_All_Versions_5x.cmd：依序v1、v2、v3，每版測試10張圖。
只測單一版本：開v1/v2/v3資料夾，雙擊Run_All_Images_5x.cmd。
每張圖：輸入LLR只準備/上傳一次，暖機1次不計入，再測量5次，取算術平均。
預設max_iterations=20，early stopping維持硬體原行為；不是強迫每個codeword都做20輪。
每次下載解碼結果並檢查參考輸出；發現錯誤或重跑結果不一致即中止，失敗資料不會當成功平均。
整組三版共30張圖測試、150次正式量測，加30次暖機。JTAG下載可能耗時，並非只有FPGA運算的幾百毫秒。
不要在測試途中按Vitis Run或另外開UI。重新啟動會建立新結果資料夾，不會覆蓋以前量測。

四、結果在哪裡
results/batch_時間/summary.csv：每張圖5次的mean_ms（正式平均）、median_ms、min/max/stdev。
results/batch_時間/comparison.csv：三版同一張圖的平均時間及加速比（全版本測試才有全部比值）。
results/batch_時間/v*/image_*/runs.csv：暖機與5次原始量測，phase區分warmup/measured。
每次run_01到run_05：decoded.u8、iteration_20.png、comparison_20.png、results.json。
transport：原始mailbox、XSDB log及每次獨立輸出；results.json保存LLR SHA256和量測狀態。
本套件不內填先前214ms等數字；正式結果只能由實體FPGA產生。

五、UI單次展示（不做平均）
根目錄Start_Demo_UI.cmd或各版Start_Fixed_LLR_UI.cmd。
英文黑白介面：選v1/v2/v3、隊友圖片、iteration清單，按Run FPGA。
預設1,2,5,10,20，各迭代上限各執行一次，表格顯示單次FPGA+DMA時間、錯誤率及平均實際迭代。
畫面顯示Original、Noisy received（由固定LLR符號還原）、FPGA decoded。
Eb/N0固定3 dB；因為採用隊友的LLR，不另產生noise、不改resize、不改seed。
隊友參考輸出是20輪，其他iteration的Reference mismatch標成N/A，不會假稱已匹配。
展示圖片沿用原本RGB，介面為黑白；不把圖片轉灰階，避免改變測試位元。
UI每次自動初始化對應硬體，不用先Vitis Run。切換版本會重新載入正確bitstream與FSBL。

六、自選照片的額外UI
各版Start_Custom_Image_UI.cmd保留選照片、調Eb/N0和iteration功能，單次執行、不做平均。
這個模式會產生新AWGN，與隊友固定noise分布不同；正式公平速度比較請使用Fixed LLR UI或五次平均批次。

七、量測範圍
FPGA+DMA時間讀自ARM XTime/mailbox，包含整張圖所有codewords的ARM控制、DMA設定及DDR傳輸、PL解碼、完成輪詢與統計。
不包含讀圖/LLR驗證、JTAG上傳下載、圖片重建、輸出打包或UART列印。不是純PL核心latency。
比較CPU時也要同一LLR hash、同一iteration上限，並確認輸出一致。
GPU/OpenCL及A53 CPU量測不包含在這個三版FPGA展示套件。

八、驗證界限與來源
套件會進行本機資料完整性與程式測試。各版批次首次自動初始化相容性仍需在板上確認；展示前請先跑一版。
資料集來源：teamate/dataset_3db/dataset_3db（原Readme及generate_dataset.py隨附）。
主機UI、bridge及整理程式由OpenAI Codex協助產生/修改；codec及既有演算法沿用原專案，來源註解保留。
不要把套件產生的未執行狀態宣稱為實測結果。

【新增：先 Vitis Run，再 CMD 量測】
v1、v2、v3 各有 After_Vitis_Run_5x.cmd 與 Vitis_Run_使用步驟.txt。
先在 Vitis 的 launch configuration 指定該版本 hardware 資料夾內的 bitstream、FSBL、controller.elf，按 Run；再執行該版本的 After_Vitis_Run_5x.cmd。
每張隊友固定 LLR 圖片：暖機 1 次不計入，再正式 5 次取算術平均。結果在 results/batch_時間/summary.csv。
此模式不重新初始化板子，不下載 controller 韌體，不重新燒錄 bitstream。只會在計時外暫停 A53 上傳 LLR，接著恢復執行。
版本由你在 Vitis 與 CMD 選擇，程式無法自動證明板上 bitstream 的版本。不同版本請分別先在 Vitis Run，再執行對應 CMD。
不要同時執行舊 bridge、UI 或其他控制板子的程式。

【展示入口更新】
v1/v2/v3 的 After_Vitis_Run_5x.cmd 現在只測第一張 image_01_awgn_3db。
共解碼 6 次：第 1 次暖機不計入平均，第 2～6 次為正式 5 次算術平均。
Run_All_Images_5x.cmd 和 Run_All_Versions_5x.cmd 仍保留完整資料集測試用途。
