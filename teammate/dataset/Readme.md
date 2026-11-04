# 固定 AWGN 3 dB LDPC 測試資料集

本資料集沿用原 `dataset/images/` 的 **10 張測試圖像**，每張均為 **256×192、RGB、8 位元通道**。
圖像像素保持不變，並非重新產生另一組圖片。每張圖像各建立一個 **BPSK + AWGN、Eb/N0 = 3 dB** 的固定案例。
3 dB 表示每個資訊位元的能量與雜訊功率譜密度之比，不是 3% 的雜訊或錯誤率。

用途：讓 plain C CPU、OpenCL GPU，以及隊友的 A53/FPGA 使用相同的輸入和校驗結構，進行正確性與效能比較。
原 `dataset`、C 程式及已有實驗結果均未修改。

## 資料規模與參數

| 項目 | 數值 |
|---|---|
| 原圖與信道案例數量 | 10 張原圖、10 組 3 dB 案例 |
| 每張尺寸 | 寬 256 × 高 192，RGB |
| 每張有效資訊位元 | 1,179,648 |
| 每張碼字數量 | 6,081 |
| 全部碼字數量 | 60,810 |
| 每個碼字 | n=384，k=194，m=192 |
| 校驗節點度數／變量節點度數 | 6／3，共 1,152 條邊 |
| 每張末尾補零 | 66 位元 |
| 每張輸入 LLR | float32[6081,384]，9,340,416 位元組 |
| 每張參考輸出 | uint8[6081,384]，每個位元使用一個位元組 |
| 譯碼演算法 | NMS，flooding，alpha=0.75，q 裁剪至 [-30,30] |
| 完整參考迭代次數 | 20 輪；通過校驗的碼字凍結，整批不提前結束 |
| 首輪參考 | 每個案例前 256 個碼字的 words 和 q |
| 碼結構種子 | 5203，z=64 |
| 雜訊種子 | image_01 至 image_10 分別為 2026～2035 |

資料已固定，不需要每次測試重新加雜訊。同一張圖與原資料集的 6 dB 案例使用相同種子，改變的是雜訊強度。
20 輪參考輸出不保證完全恢復原圖；它代表此演算法在這份輸入上的實際結果。

## 目錄與檔案

```text
dataset_3db/
  Readme.md
  manifest.json                 參數、形狀、雜訊種子、SHA-256 和錯誤統計
  generate_dataset.py           重新產生資料的腳本
  verify_dataset.py             檢查資料完整性與基本正確性
  preview.png                   10 張原圖的總覽
  images/
    image_01.png ... image_10.png
    image_01_tx.u8 ...           發送前的完整碼字，僅供評價
  code/
    checks.i32                  [192,6]，校驗節點連接的變量編號
    variable_edges.i32          [384,3]，變量連接的展平邊編號
    info.i32                    [194]，資訊位元的位置
    variables.i32 / pivots.i32 / shifts.i32 / H.u8 / parity_map.u8
  cases/
    image_01_awgn_3db/ ... image_10_awgn_3db/
      llr.f32                   加雜訊後的固定譯碼輸入 [6081,384]
      reference_words.u8        20 輪 Python 參考輸出 [6081,384]
      step1_words.u8            首輪判決 [256,384]
      step1_q.f32               首輪消息 [256,192,6]
      received.png              初始硬判決恢復的圖片，未經糾錯
      decoded.png               20 輪參考譯碼恢復的圖片
```

所有二進位陣列均無檔案頭、無壓縮，採用行優先排列：

- `.f32`：小端 IEEE-754 單精度浮點數，每項 4 位元組。
- `.i32`：小端有符號 32 位元整數，每項 4 位元組。
- `.u8`：無符號 8 位元整數；每個比特儲存為一個 0 或 1，未打包。
- `llr[frame*n+variable]` 對應一個碼字的一個比特。
- 邊編號為 `check*6+lane`，q 的位置為 `frame*1152+edge`。
- 資訊位元應按照 `info.i32` 提取，不是直接取碼字前 194 位。

## C / OpenCL 如何使用

以第一張圖片為例，將程式中的路徑設定成：

```c
const char *checks_path = "dataset_3db/code/checks.i32";
const char *edges_path = "dataset_3db/code/variable_edges.i32";
const char *info_path = "dataset_3db/code/info.i32";
const char *llr_path = "dataset_3db/cases/image_01_awgn_3db/llr.f32";
const char *reference_path = "dataset_3db/cases/image_01_awgn_3db/reference_words.u8";
const char *step1_words_path = "dataset_3db/cases/image_01_awgn_3db/step1_words.u8";
const char *step1_q_path = "dataset_3db/cases/image_01_awgn_3db/step1_q.f32";
```

以上路徑假定從 `ldpc` 工作目錄執行。其他圖片將四個案例路徑的 `image_01` 一起改成對應編號。
需要計算真實錯誤率時，另外讀取對應的 `dataset_3db/images/image_XX_tx.u8`。

1. 讀取鄰接表與 LLR，配置輸出與工作陣列。
2. 每批初始化 `words=(llr<0)`、`q=llr[:,checks]`。
3. 依相同規則執行 NMS；以 20 輪輸出對照 `reference_words.u8`。
4. 若測試 0～19 輪，不要要求結果等於 20 輪參考；使用 tx 評估錯誤率。
5. 用 `info` 提取資訊位元，拼接後保留前 1,179,648 位，移除 66 位補零。
6. 若要恢復圖片，每 8 位以最高位在前打包，重新排列為 [192,256,3]。

`tx` 和參考輸出只能用於驗證，不能提供給譯碼核心作為正確答案。
比較計算平台時使用相同案例、batch、精度、迭代次數和停止規則；每次重測重新初始化。
檔案讀取、驗證、圖片輸出應放在譯碼計時之外。FPGA 若改用定點數，另行記錄量化規則與誤碼差異。

## 與原 Python 流程的差異

使用本資料集後，測試程式可以省略圖片選擇或攝影機、`make_code()`、圖片轉比特、`encode()` 和 `apply_channel()`。
因為碼結構、編碼結果與加雜訊後的 LLR 均已儲存。仍須執行狀態初始化、校驗、節點更新、迭代與輸出驗證。
原 `ldpc.py` 沒有自動讀取此目錄的功能，直接執行它仍會重新產生輸入。

## 驗證與重建

在 `ldpc` 工作目錄執行，Python 需要 NumPy 和 Pillow：

```bash
python3 dataset_3db/verify_dataset.py
python3 dataset_3db/generate_dataset.py --output dataset_3db_rebuilt
python3 dataset_3db/verify_dataset.py --root dataset_3db_rebuilt
```

生成器拒絕覆寫已有 manifest 的資料集。重建需要保留 `../ldpc.py` 與原 `../dataset/images/`；
正常讀取和驗證本資料集不需要原資料集。Python、NumPy、Pillow 版本與參考原始碼雜湊記錄在 manifest。
跨版本重建可能有差異；平台比較優先直接共用已固定的檔案。

本機本次使用既有執行環境，沒有安裝系統套件：

```bash
/home/aksrrt/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 dataset_3db/verify_dataset.py
```

此為教學用自訂 QC-LDPC，非標準 Wi-Fi/5G 碼，也不代表真實無線鏈路的誤碼保證。
演算法來源為 `../ldpc.py`；生成器與文件由 Codex 協助編寫，課程提交時請保留來源與 AI 使用聲明。

## 本次生成與驗證結果

共 89 個資料檔通過雜湊與尺寸檢查；10 張原圖像素、發送碼字及共用碼結構均與原資料集一致。第一張 3 dB 的二進位向量亦與既有案例完全一致。

二進位與 PNG 檔案合計 154,230,437 位元組（約 147.09 MiB），不含腳本與文件。

下表錯誤數均指每張圖的 1,179,648 個有效資訊位元；20 輪結果為 NumPy 參考輸出，並非 FPGA/OpenCL 測試結果。

| 圖片 | 未糾錯資訊位元錯誤數 | 20 輪後錯誤數 | 20 輪後 BER |
|---|---:|---:|---:|
| image_01_awgn_3db | 92,286 | 120 | 0.00010173 |
| image_02_awgn_3db | 91,726 | 103 | 0.00008731 |
| image_03_awgn_3db | 91,551 | 57 | 0.00004832 |
| image_04_awgn_3db | 91,666 | 74 | 0.00006273 |
| image_05_awgn_3db | 91,826 | 110 | 0.00009325 |
| image_06_awgn_3db | 91,740 | 113 | 0.00009579 |
| image_07_awgn_3db | 91,711 | 85 | 0.00007206 |
| image_08_awgn_3db | 92,128 | 102 | 0.00008647 |
| image_09_awgn_3db | 91,701 | 114 | 0.00009664 |
| image_10_awgn_3db | 91,737 | 157 | 0.00013309 |
