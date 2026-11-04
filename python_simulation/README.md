
> 已新增 CPU / GPU（CUDA）選項，最新裝置與計時說明請看 README_DEVICE_SELECTION.md。

# LDPC 圖片傳輸：Normalized Min-Sum / BF

## 啟動

雙擊 `run_simulation.cmd`。依序選通道雜訊與解碼器、鏡頭拍一張或本機照片，完成後輸出到 `results`。預設主解碼器 NMS、alpha=0.75，另跑同一通道樣本的 BF 基準（`bf_baseline` 子資料夾）。建議先選 AWGN、Eb/N0=6 dB、NMS。

### 開始前設定 iteration

雙擊啟動後，第一個「通道與解碼器設定」視窗現在可以輸入：
- **最大迭代次數**：例如 30，也可設 0、20、50。
- **要比較的輪次**：例如 0, 1, 3, 5, 10, 30，支援逗號、中文頓號或空白分隔。
- 自動包含第 0 輪及最後一輪；留空時只比較這兩輪。重複輪次會合併。
- 比較輪次必須介於 0 與最大值之間；錯誤輸入會留在設定視窗提示，不會開始模擬。

按「下一步：拍照或選照片」後才會使用這些設定解碼。所有比較圖片共用同一次通道產生的雜訊。
例如最多 30 輪、比較 0/1/3/5/10/30，輸出 decoded_iter_000.png、decoded_iter_001.png 等選定輪次，
並產生 iteration_comparison.png；run_config.json 記錄實際設定。
軟體仍依固定預算呼叫迭代，已通過校驗的碼字會凍結，因此後續圖片可能相同。

保留原程式檔名 `ldpc_bf_image_sim.py`，但預設已改為 NMS。需要 Python 3.10+、numpy、Pillow>=10.1；鏡頭另需 opencv-python，本機 vendor 已安裝。換電腦可 `python -m pip install -r requirements.txt`。

```powershell
./run_simulation.cmd --channel awgn --ebn0-db 6
./run_simulation.cmd --channel bsc --noise 0.01
./run_simulation.cmd --image photo.jpg --channel awgn --ebn0-db 4 --iterations 30 --alpha 0.75 --output results_awgn4
./run_simulation.cmd --demo --max-size 96 --channel awgn --ebn0-db 6 --output results_demo
./run_simulation.cmd --decoder bf --channel bsc --noise 0.005
./run_simulation.cmd --self-test
```

`--no-bf-comparison` 關閉額外基準。`--image` / `--demo` 跳過通道視窗，未指定 channel 時使用 BSC。其他參數：`--grayscale`、`--seed 2026`、`--batch-size 256`、`--z 64`、`--max-size 256`（0保留原尺寸）、`--snapshots 0 1 2 5 10 20`、`--camera-index 1`。

每次使用不同 `--output` 可保留實驗；相同資料夾的同名檔案會覆寫，不同輪次的舊圖片不會自動清除。

## 整體流程

1. 圖片處理：EXIF方向校正、RGB/灰階、等比例縮到最長邊256（可調）。不是直接保護JPEG壓縮檔，而是保護像素bytes。
2. 像素bytes轉MSB-first bits，補零到資訊區塊長度。
3. 系統式QC-LDPC編碼，確認所有傳送碼字 Hc=0。
4. 完整碼字（含parity）經BSC或BPSK/AWGN通道。
5. 產生channel LLR，NMS逐輪交換訊息並硬判決。
6. 每個frame滿足全部parity check時凍結，直到其他frame或最大輪次完成。
7. 抽出資訊位元、移除補零、還原圖片，記錄每輪BER/FER。

## NMS 每一輪的流程

LLR定義為 log(P(bit=0|y)/P(bit=1|y))：正值偏向0，負值偏向1，絕對值是可信度。

### 初始化

- AWGN：BPSK 0->+1、1->-1，Es=1。R=k/n，Eb為資訊位元能量；sigma²=1/(2*R*10^(EbN0_dB/10))，channel LLR=2*y/sigma²。
- BSC：接收bit為b，LLR=(1-2*b)*log((1-p)/p)。p=0或1用有限飽和值處理，p=0.5時LLR=0。p>0.5時合理似然會反轉對接收bit的偏好。
- 無雜訊：正負30的LLR。
- Channel及variable-to-check訊息限制在[-30,30]，使用float32。這是浮點參考模型，尚非定點硬體版本。
- 每條edge的variable-to-check訊息q，初始化為該bit的channel LLR。

### Check-node update

對每條 check m -> variable n 的訊息，排除目的地n那條edge：

`r[m,n] = alpha * product(sign(q[m,n'])) * min(abs(q[m,n']))  (n' != n)`

實作每個check的符號總乘積（可對應XOR）、第一與第二最小絕對值，再針對目的edge選正確最小值。重複最小值和零值已納入測試。alpha預設0.75，降低一般Min-Sum過度自信的影響。

### Variable-node update

`posterior[n] = channel_llr[n] + sum(r[m,n])`

下一輪要送給check m時，排除剛從m收到的訊息：

`q_next[m,n] = clip(posterior[n] - r[m,n], -30, 30)`

排除自身回傳是extrinsic訊息的關鍵，避免同一份證據直接反覆算回自己。

### 判決與停止

posterior<0判為1，其餘判為0。檢查H*c mod2；全零則該frame凍結。停止條件不使用原圖或真實BER。錯誤碼字也可能通過檢查，因此通過syndrome不等於保證正確。

本實作用flooding schedule：同輪check update完成後再做全部variable update，不是layered NMS。適合先做跨frame/check平行化；之後可研究layered schedule，但要重新對齊比較條件。

## 輸出

- `original.png`：真正送入編碼器的圖片。
- `decoded_iter_000.png`、`decoded_iter_XXX.png`：各輪還原圖，NMS iteration0為channel LLR的初始判決。
- `iteration_comparison.png`：原圖與各輪圖片對照。
- `ber_vs_iteration.png` / `.csv`：主解碼器逐輪payload/codeword BER、FER、unsatisfied frames。
- `decoder_comparison.png`：NMS與BF逐輪BER比較。
- `bf_baseline/`：相同碼字、通道設定與seed重現同一channel realization的BF完整結果。可比對兩個NPZ中的tx/rx確認。
- `run_config.json`：channel、seed、碼率、LLR規則、alpha、schedule及decoder_step_seconds。
- `accelerator_vectors.npz`：checks、variables、variable_edges（check-major flatten edge索引）、H、QC shifts、資訊位元位置、tx/rx、channel_llr、原始payload。NMS硬體需讀LLR，不能只讀rx硬位元。

Payload BER排除padding/parity；codeword BER包含完整傳送碼字；FER是錯誤碼字比例。每輪都評估同一批資料，不挑最低BER輪次。量測包含尚未收斂與已凍結frame。

## 碼型與限制

仍使用原本的自訂QC-LDPC，以隔離decoder變因：3×6 circulant blocks、Z=64、n=384、check degree6、variable degree3，排除4-cycle。GF(2)rank決定k，預設194；不是WiFi/5G標準碼。更換成NMS不代表碼型已最佳化，也不宣稱接近Shannon limit。BER仍不保證每輪單調下降。

本次示例：96×72 RGB demo，seed2026，AWGN Eb/N0=6 dB，856 frames。NMS payload BER由0.022575、第1輪0.001405、第2輪0.000012、第5輪本批未觀測到錯誤。BF同一樣本第20輪約0.244912。零觀測錯誤不等於真實BER=0；不同圖片、noise及seed結果會不同。

正式通訊評估應掃Eb/N0、累計更多frames/seeds及錯誤事件，報告BER/FER；iteration曲線只能顯示收斂，不能用來宣稱距離容量極限多遠。

## 加速與驗證

主核心為`nms_check_update`、`nms_step`。硬體主要是XOR、min1/min2、加減、縮放和訊息記憶體。alpha=.75可在定點設計中以移位加法近似，但需另定義rounding/saturation並重新驗證。BF運算更便宜，NMS糾錯能力的提升不代表Python速度也提升。

目前計時只包含每輪Python核心呼叫，不含初始化、通道、metrics、I/O及畫圖，不是端到端加速比。逐frame停止使用mask凍結，Python仍會計算批次內部分已停止frame的中間運算，不能把此計時當理想硬體early-stop性能。

`--self-test`保留BF/encoder測試。`test_decoder.py`另驗證NMS check-node更新（獨立逐edge參考、ties/zeros/signs）、3輪variable/extrinsic更新、無雜訊、LLR端點。使用 `python test_decoder.py`。

算法參考：https://www.mathworks.com/help/comm/ug/block-codes.html （本程式採flooding，參考文件亦介紹layered版本，排程不同）。

本程式由OpenAI Codex依本次對話需求生成，未直接複製上述來源程式。課程提交請標註AI使用並保留prompts，自行理解與驗證程式。

## 解碼時間 / latency 比較

執行完成會列出 NMS、BF 的 timing 表，並儲存 latency_comparison.csv。各自 run_config.json 也記錄相同指標：

- decoder_total_ms：所有批次的解碼初始化＋指定輪數核心呼叫時間總和。
- mean_batch_decoder_ms / p95_batch_decoder_ms：批次解碼運算時間平均與第95百分位。批次最大為 batch-size，最後一批可能較小。
- amortized_us_per_codeword：總解碼運算時間除以碼字數，是攤提成本，不是獨立單碼字 latency。
- ber_vs_iteration.csv 新增 iteration_core_ms 與 cumulative_decoder_ms（後者包含解碼初始化）。

計時排除矩陣建立、編碼、通道與LLR生成、BER統計、圖片暫存、檔案輸出與畫圖。使用perf_counter累計核心區段，包含首次呼叫影響；是單次Python量測，尚無多次重複benchmark。依固定最大迭代數比較；已收斂frame的判決會凍結，但批次向量化運算仍繼續，故不是最佳化early-stop效能。BF可能更快但錯誤率較高，請一起看最後BER/FER。關閉BF comparison時只顯示所選decoder的時間。

