# CPU / GPU（CUDA）裝置選擇

兩個專案的啟動選單都提供 CPU / GPU（CUDA），預設 CPU。GPU僅指NVIDIA CUDA，不適用AMD Radeon或Intel顯卡。沒有可用CUDA時會顯示原因，不會靜默改用CPU並誤標GPU。

## YOLO

雙擊 `run_photo.cmd` 或 `run_webcam.cmd`，在單張拍照設定的「運算裝置」下拉選CPU或GPU (CUDA)。預覽不持續推論，拍照後只推論一張。

命令列：

```powershell
./run_photo.cmd --device cpu
./run_photo.cmd --device cuda
```

`cuda`、`cuda:0`、`0`為第一張CUDA顯卡的別名。輸出CSV/JSON與終端機會標明實際裝置、CUDA runtime與裝置名稱。FP32、TF32關閉；暖機後才量測。CUDA計時前後同步，避免只量到非同步提交時間。原連續版 `yolo_webcam_latency.py` 也提供CPU/GPU下拉選項。

YOLO CPU仍用PyTorch，GPU用PyTorch CUDA；CUDA不是OpenCL。

## LDPC

雙擊 `run_simulation.cmd`。第一個通道/解碼器視窗新增運算裝置：

- CPU：原本NumPy NMS/BF。
- GPU：新增PyTorch CUDA NMS/BF，矩陣鄰接表、訊息與各輪運算移到GPU。

LDPC啟動檔優先共用旁邊 `../yolo_sw_sim/.venv` 環境。若整個專案搬動，請保留兩個資料夾的相對位置，或調整啟動檔的Python路徑。找不到該環境時退回原有Python，CPU仍可用，但CUDA需另安裝PyTorch。

```powershell
./run_simulation.cmd --channel awgn --ebn0-db 6 --device cpu
./run_simulation.cmd --channel awgn --ebn0-db 6 --device cuda
```

編碼、通道雜訊、LLR生成、BER統計與畫圖仍在CPU；選GPU指的是decoder核心，不是把整個圖片模擬搬到GPU。相同seed、圖片、通道與碼型可重現相同RX和LLR。NMS/BF比較都使用選定裝置。

GPU先做固定圖表上傳與3輪暖機，排除於decoder timing。decoder_total_ms包含每批輸入/初始化、指定輪數核心呼叫、最後一輪結果傳回CPU；每段GPU計時都有同步。為了畫每輪BER，額外的中間結果診斷傳輸記錄為diagnostic_device_to_host_ms，排除於核心總時間，但這些診斷仍可能干擾執行/快取，並非無干擾的正式吞吐量benchmark。final_device_to_host_ms另列最後輸出傳輸。小批次也可能因CUDA launch/transfer overhead比CPU慢。

目前CPU baseline是NumPy而GPU是PyTorch，差異包含後端實作，不是只換硬體的嚴格對照。做正式研究時可增加PyTorch CPU對照；`ldpc_torch_backend.py` 支援CPU裝置用於逐輪驗證。`test_device_backends.py` 對照NumPy與PyTorch，若CUDA可用會額外在GPU跑驗證，否則明確標示skip。

## CUDA環境

`yolo_sw_sim/setup_cuda.cmd` 可安裝PyTorch 2.8.0 / torchvision 0.23.0 CUDA12.8版（官方wheel來源），CPU也能繼續使用。不會安裝/變更NVIDIA驅動。相容NVIDIA硬體與驅動仍是必要條件；安裝CUDA版PyTorch不會讓AMD顯卡變成CUDA顯卡。

`setup_environment.cmd` 是原本的CPU環境安裝檔；要保留GPU功能時請使用 `setup_cuda.cmd`。

本次工具環境檢查：CUDA driver介面回報12.8，但cuInit回報無裝置；目前能列出的顯示卡為AMD Radeon 860M。因此不可宣稱已在此機器完成實體CUDA推論/解碼測速。CPU流程、CUDA計算程式的CPU等價對照、不可用裝置錯誤處理可獨立驗證。

使用者補充：實體顯卡為 RTX 5060。PyTorch 2.8 的 CUDA12.8版支援Blackwell系列；本工具環境只能看到AMD整合顯示卡並回報CUDA device_count=0，不代表電腦沒有獨立NVIDIA GPU。已安裝torch 2.8.0+cu128與torchvision 0.23.0+cu128；請在一般桌面直接執行 yolo_sw_sim/check_cuda.cmd，若CUDA available=True且列出RTX5060，再於兩份程式選GPU。若仍False，需檢查驅動/顯卡是否啟用，不能當作GPU測速成功。

最後驗證：新CUDA版套件環境下，YOLO單張CPU推論與檔案輸出通過；LDPC NumPy/PyTorch CPU逐輪對照通過，實體CUDA測試因工具看不到GPU而skip。
