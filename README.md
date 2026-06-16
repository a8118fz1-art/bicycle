# EMS Bike Web HMI - UART Validation

This workspace contains a web-based HMI and a minimal UART validation flow for testing EMS controller frames.

目標
- 在瀏覽器端快速建立、送出與解析 EMS UART 封包（CRC16-CCITT，SOF=55 AA，EOF=0x0D，LEN = CMD+DATA 長度）。

目前功能
- `index.html` + `app.js`：主要 HMI 與 BLE 控制邏輯。
- `uart_test.html`：獨立的手動測試頁面，可建立任意 CMD + DATA 的封包，並使用 Web Serial 送出與接收。

快速開始（在 Windows + Chromium-based browser）
1. 確認使用 Chromium-based 瀏覽器（Chrome/Edge/Brave）支援 Web Serial。Chrome 79+ 支援，Edge 79+ 支援。
2. 如果你暫時沒有 MCU，可用下列方法模擬或 loopback：
   - 硬體 loopback：使用 USB-UART 轉接器，將 TX 接到 RX（短接），開啟通訊埠即可看到回傳的封包。
   - 虛擬 COM 連線：使用 com0com 或其它虛擬序列埠工具（Windows）建立 pair，另一端可用範例程式回應。

3. 在專案根目錄打開 `uart_test.html`（可直接用檔案協定開啟，或啟動簡單靜態伺服器）：

```powershell
# 以 Python 簡單啟動本機伺服器 (在 d:\bicycle-main):
python -m http.server 8000
# 然後瀏覽器開啟 http://localhost:8000/uart_test.html
```

4. 使用流程（手動測試）
- 在 `CMD` 輸入 1 byte 的十六進位碼（例如 `10` 表 SET_CONTROL）。
- 在 `DATA` 填入資料 bytes（空白分隔，例如 `01 FA 00`）。
- 按 `Build Packet` 檢視產生的完整封包。
- 按 `Open UART Port` 選擇實體或虛擬 COM 埠（預設 19200 8-N-1）。
- 按 `Send` 發送封包。回應會顯示在 `Serial Log`。

5. 在沒有 MCU 的情況下驗證
- 使用 USB-UART loopback：送出的封包會被 echo 回來，確認 `Serial Log` 顯示相同 bytes。
- 使用虛擬 COM pair（com0com）：在其中一端打開 `uart_test.html` 的 port，另一端用 `tools/uart_mock.py` 讀取並回送一個 STATUS_REPORT 範例。

STATUS_REPORT 範例
- 範例 frame: `55 AA 0E 80 ... CRC_L CRC_H 0D`（LEN=14 = CMD(1)+DATA(13)）

## Python UART Mock

你可以使用 `tools/uart_mock.py` 來模擬 MCU 回應。此程式會開啟指定的 COM port，監聽收到的 UART 封包，並在接到 `SET_CONTROL` (`0x10`) 時回送一個 `STATUS_REPORT` (`0x80`) 範例封包。

### 安裝 pyserial

```powershell
python -m pip install pyserial
```

### 直接與實體裝置測試

```powershell
python tools/uart_mock.py COM5
```

### 使用虛擬 COM pair / com0com

1. 建立 pair 埠，例如 `COM5 <-> COM6`。
2. 在瀏覽器的 `uart_test.html` 中開啟 `COM5`。
3. 在另一端執行：

```powershell
python tools/uart_mock.py COM6
```

這樣當你在網頁按 `Send` 送出 `SET_CONTROL` 封包時，`uart_mock.py` 會自動回送一個 `STATUS_REPORT` 封包，並在 `Serial Log` 中顯示接收到的回應。

### 測試步驟

1. 先啟動 `uart_test.html`。
2. 按 `Open UART Port` 選擇 `COM5`。
3. 執行 `python tools/uart_mock.py COM6`。
4. 按 `Send` 發送 `CMD=10 DATA=01 FA 00`。
5. 確認 `Serial Log` 顯示 `RX:` 回應封包內容。

後續
- 若要我幫你：
  - 在主 UI 中加入更友善的 UART 面板與解析結果。
  - 增加 `uart_mock.py` 的回應選單（STATUS_REPORT、ERROR_REPORT、ACK）等選擇。

如果你要我直接產生一個用 `pyserial` 模擬 STATUS_REPORT 的小程式，我可以接著新增 `tools/uart_mock.py` 並示範如何連到 `uart_test.html` 進行整合測試。
# bicycle
bicycle
