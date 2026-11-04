# ZCU111 上板步驟（RF Data Converter Evaluation UI）

接線：J6（DAC Tile 1 - DAC 3）→ SMA 線 → J4（ADC Tile 0 - ADC 01）。

## 1. 準備（只做一次）

1. **Overview → PL Settings → Memory Type 選 BRAM → Apply**，等它跑完。
   DDR 模式在我們的板子上連 single-tone 都會亂，不要用。
2. **Settings** 把 DAC data directory 設成 repo 裡的 `tx\qpsk_30x30`（或 `tx\bpsk_20x20`）。
   ADC 和 Clocking 路徑不要動。

## 2. 發送

1. **DAC Tile 1 - DAC 3** → Signal Type **From File**。
2. 按 File 旁的重新整理 → 選 `photo30q_all_qpsk_407p04MHz`（BPSK 是 `photo20_all_bpsk_407p04MHz`）。
3. Channel 選 **sig**，確認顯示 **25440 Samples**、Sampling rate 6512.640 MHz。
4. 設定 **PEP**，按 **Generate**。DAC 會一直重複播放。

| 想看到的結果 | QPSK 30×30 | BPSK 20×20 |
|---|---|---|
| 幾乎沒有錯誤 | 0 dBFS | 0 dBFS |
| LDPC 幾次迭代就修好 | −3 dBFS | −5 dBFS |
| 需要較多迭代 | −5 ～ −5.2 dBFS | −7 dBFS |
| 修不回來 | −5.3 dBFS 以下 | −10 dBFS |

在門檻附近，同一個 PEP 每次擷取的結果差異很大，建議同一設定多存幾份。

## 3. 接收

1. **ADC Tile 0 - ADC 01** → Samples **16384** → **Acquire**。
   0 MHz 的尖峰是 ADC 的 DC offset，不影響解碼。
2. **File → Export ADC Data to TDMS**，取名例如 `qpsk30_pep-5p2dB_01`。
   **檔名不能有小數點**（UI 會把 `.` 之後截掉），用 `p` 代替，例如 `-5p2`。
   檔案會存到 `C:\Xilinx\RF_DC_Evaluation_UI\Data\ADC`。

## 4. 解碼

```bash
python rx_decode.py "C:\Xilinx\RF_DC_Evaluation_UI\Data\ADC\qpsk30_pep-5p2dB_01.tdms" --tx tx/qpsk_30x30
python rx_iterations.py "C:\Xilinx\RF_DC_Evaluation_UI\Data\ADC\qpsk30_pep-5p2dB_01.tdms" --tx tx/qpsk_30x30 --show 0 2 5 10 15 20
```

`--tx` 一定要對應發送時用的波形（`tx/qpsk_30x30` 或 `tx/bpsk_20x20`）。

`result.json` 重點欄位：

| 欄位 | 意義 |
|---|---|
| `peak_abs_adc` | ADC 峰值，接近 32767 代表削峰 |
| `preamble_correlation`、`preamble_bit_errors` | 同步品質；錯很多代表沒對上 |
| `estimated_symbol_snr_db` | 估計 SNR（QPSK 為每個 bit） |
| `channel_bit_errors` | 沒有 LDPC 時錯幾個 bit |
| `with_ldpc.crc_ok` | LDPC 修正後整張圖是否完全正確 |

## 5. ADC 只能擷取 8192 點時

用 `prepare_tx_*.py` 產生的 `*_pkt1`～`*_pkt4` 波形（10176 samples），每包各 Generate、Acquire、Export 一次，
再把 4 個擷取檔依序一起丟給 `rx_decode.py`。
