# EMS Bike Web HMI - UART Validation

This workspace contains a web-based HMI and a minimal UART validation flow for testing EMS controller frames.

目標
- 在瀏覽器端快速建立、送出與解析 EMS UART 封包（CRC16-CCITT，SOF=55 AA，EOF=0x0D，LEN = CMD+DATA 長度）。

> **v16.55 起**：阻力控制必須走 `SET_CONTROL(0x10)` → `START(0x01)` 序列，
> 並以 `HEARTBEAT(0x40)` 維持通訊（3 秒無通訊關阻力、30 秒斷電）。
> 詳見 `PROTOCOL_NOTES_2026-08.md`。

目前功能
- `index.html` + `app.js`：主要 HMI 與 BLE 控制邏輯。
- `uart_session.js`：UART 連線階段管理（序列、心跳、ACK 等待、逾時偵測）。
- `uart_test.html`：工廠測試台，含序列梯、STATUS 即時解碼與手動封包工具。
- `uart_test_legacy.html`：舊版純手動封包頁面（保留）。
- `tools/ems_mock.py`：下控模擬器，可用 `--selftest` 在無硬體下驗證狀態機。

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

## KP 阻力等級與功率對照表

`app.js` 的 `POWER_TABLE` 是 **15 列 KP（0～14）× 10 欄 RPM（10～100）＝ 150 個量測點**，
單位瓦特。取值為雙線性內插：先在同一 KP 列沿 RPM 內插（`pAt`），再沿 KP 方向內插
（`powerCorrect`）；超出 10～100 RPM 以端點斜率外推。反查（瓦特 → KP，ERG 模式用）
由 `kpForTargetWatt()` 負責。封包端 `encodeTarget()` 將 KP 乘以 10 送出，0～140 對應 0.0～14.0。

### KP 0 是「無阻力」

KP 0 那一列量的是**無電磁負載**的狀態，與 KP 1～14 的加載狀態是不同的量測條件，
所以整列數值高於 KP 1（比值穩定在 1.40～1.58），不是量測誤差。

因此**不可**在 KP 0 與 KP 1 之間線性內插——那會得到「阻力調高、功率反而下降」的曲線，
而 UI 的 KP 下限是 0.1，這一段使用者調得到。`powerCorrect()` 與 `kpForTargetWatt()`
都只在 KP ≥ 1 的範圍內插；0 < KP < 1 沒有量測資料，一律取 KP 1 的值。

### 已知待查的資料點

`KP 8 @ 20 RPM = 44.3 W` 與 `KP 7 @ 20 RPM` 完全相同，是該欄唯一增量為 0 的位置
（前一格 +10.3、後一格 +31.0）。以其餘 9 欄的 KP8/KP7 平均比值 1.238 推估應在 55 W 左右。
疑似謄寫時複製上一列，**需回查原始量測紀錄後才可更正**，不宜填入推估值。

### 另一套模型（注意不可混用）

`ui.js` 有兩處使用 Monark 立式測功儀的標準式 `watt = kp × rpm × 0.98`
（`ui.js:241` 作為查表失敗的後備，`ui.js:357` 的最大功率掃描則完全不查表）。
本機實測表與該公式的比值介於 **1.39～3.50（平均 2.13）且隨 KP 變動**，
代表本機的 KP 是裝置自訂的阻力索引，不是 Monark 的公斤力，兩者不可互換。
`ui.js:357` 是否應改為查表，取決於 3-Step 判讀標準當初的建立依據，尚待確認。

## 資產快取戳記（改完 JS / CSS 後必跑）

`index.html` 與 `uart_test.html` 引用資產時帶 `?v=<版本>-<內容雜湊>`。
雜湊由檔案內容算出，內容一改網址就變，瀏覽器必定重抓，不必叫使用者按 Ctrl+F5。

**改過任何 `.js` 或 `.css` 之後、commit 之前**，在專案根目錄執行：

```powershell
python tools/stamp_assets.py
```

沒改到就不會動任何檔案。CI 或 commit 前想先確認可加 `--check`，
戳記過期時會列出差異並以 exit code 1 結束：

```powershell
python tools/stamp_assets.py --check
```

兩點說明：

- 只戳記 JS / CSS，**不含 HTML**。HTML 之間的導覽連結若也戳記會形成循環相依
  （`index.html` → `app.js` → `uart_test.html` → `index.html`），改一個就讓下一個失效，
  永遠收斂不了。HTML 由 GitHub Pages 的 Cache-Control 控管，過期會自行重新驗證。
- 雜湊在計算前會把 CRLF 正規化成 LF。本專案 `core.autocrlf=true`，同一份 commit
  在工作目錄可能是 LF（直接解壓縮）也可能是 CRLF（經 git checkout 還原），
  不正規化的話換一台機器 clone 後 `--check` 會誤報。

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
