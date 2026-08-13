# EMS Bike UART — 廠商回饋處理紀錄（2026-08）

對應通訊協定：`EMS Bike UART通訊協定-2026-06-12.pdf` v0.1
上控版本：v16.54 → **v16.55**

---

## 一、上控端的三個實際缺陷

廠商回報「SET_CONTROL 後下控不產生阻力」，比對程式碼後確認上控端有三個問題，
其中第 2 項即使補上 START 也一樣不會有正確阻力，必須一起修。

| # | 問題 | 原始程式 | 修正後 |
|---|------|----------|--------|
| 1 | **從未送出 START(0x01)** | 全專案搜尋不到 `0x01`，只送 `SET_CONTROL` | 新增 `uart_session.js`，`arm()` 執行 SET_CONTROL → ACK_OK → START → ACK_OK |
| 2 | **CONTROL_MODE 對應整體錯一位** | KP 送 `mode=0x01`（實為 ERG）、Watt 送 `mode=0x02`（實為 DUTY） | 依協定 §6 更正為 KP=0 / ERG=1 / DUTY=2 |
| 3 | **完全沒有 HEARTBEAT** | 無 0x40 相關程式 | 串口開啟即以 1000 ms 週期送出，關閉才停止 |

第 2 項的實際後果：畫面設定 KP 5.0 → 送出 `mode=1, target=50`，
下控會理解成「ERG 50 W」；設定 250 W → 送出 `mode=2, target=250`，
下控會理解成「DUTY 25.0%」。兩者都不會是預期的阻力。

補充：上控原本只解析 `STATUS_REPORT(0x80)`，`ACK(0xF0)` 與 `ERROR_REPORT(0xF1)` 全部丟棄，
所以即使下控早就回了 `ACK_INVALID_STATE`，畫面上也看不到。這版一併補上。

---

## 二、心跳的生命週期（重要設計決定）

廠商說明的兩個逾時是不同層級的：

- 阻力 ON 時 **3 秒**無通訊 → 阻力輸出關閉，狀態切 OFF
- **30 秒**無通訊 → 下控直接斷電

因此心跳不能綁在 START ~ STOP，而要綁在 **串口開啟 ~ 關閉**。
按下 STOP 只是關阻力，此時若停掉心跳，30 秒後整台會斷電。
`uart_session.js` 依此實作：`begin()` 開心跳、`end()` 或 `SHUTDOWN` 才停。

心跳週期：協定 §12 寫 100 ms，廠商說 1 秒即可。目前預設 **1000 ms**（對 3 秒逾時有 3 倍餘裕），
測試台可切換 100 / 500 / 1000 ms 比對。

---

## 三、協定文件建議修訂（v0.1 → v0.2）

1. **新增狀態機章節**。目前文件只列指令表，沒有寫「SET_CONTROL 不會自行開啟輸出」。
   建議明列：`IDLE → (SET_CONTROL) → READY → (START) → RUNNING`，
   以及 RUNNING 的離開條件：STOP / 3s TIMEOUT / SHUTDOWN / ERROR。
2. **§12 Timeout Action 與實機不符**。文件寫「EMS OFF → ERR_COMM_TIMEOUT → Wait 5 sec → Power OFF HMI」，
   廠商實作為 3 秒關阻力、30 秒斷電。請更新為實機值。
3. **§12 Heartbeat Interval** 建議改為「標稱 100 ms，上控實作 ≤1000 ms 皆可」，
   與 §13 STATUS_REPORT 的 100 ms 分開描述。
4. **§7 SET_CONTROL** 補上「本指令僅設定參數，輸出狀態不變；ON 狀態下可直接改模式與目標值」。
5. **§14 Boot Sequence** 已有正確順序，建議在 §5 指令表加註「0x10 需搭配 0x01」互相對照。

---

## 四、待廠商確認事項

1. **3 秒逾時的計時基準**：是「任何合法上控封包」都會重置，還是只認 HEARTBEAT？
   （目前上控假設為前者，SET_CONTROL 也算通訊。）
2. **30 秒斷電的起算點**：從最後一次通訊起算 30 秒，還是從 3 秒逾時事件再加 30 秒？
3. **逾時後的恢復流程**：`ERR_COMM_TIMEOUT` 置起後，是否必須先送 `RESET_ERROR(0x03)`
   才能再 START？若直接 START，回的是 `ACK_OK` 還是 `ACK_INVALID_STATE`？
4. **STOP 後的參數保留**：STOP 之後 target 是保留還是歸零？
   再送 START 是沿用舊值，還是必須重送 SET_CONTROL？
5. **EMS BRAKE 電流回報欄位**：手工板已可偵測 EMS BRAKE 電流，
   `STATUS_PACKET.est_current_mA` 是否改為實測值？或另加欄位、改變 DATA 長度？
   若長度改變請一併更新 §11 與版本號，上控需以 `GET_VERSION` 做相容判斷。
6. **線圈規格**：+32V / DUTY 100% 約 1.5 A 是廠內舊線圈的實測值；
   量產線圈若更換，Current Mapping Table 與 est_watt 特性表需重新標定，
   請確認量產線圈料號是否與測試線圈相同。
7. **UART TOOL 封包紀錄**：來信提到「相關傳輸封包如附件」，但附件未收到，
   請補寄實際 log，以便逐一比對 CRC 與時序。

---

## 五、驗證方式

無實機時可用下控模擬器跑完整序列：

```bash
python -m pip install pyserial
python tools/ems_mock.py --selftest        # 純狀態機驗證，不需硬體
python tools/ems_mock.py COM6              # 搭配 com0com pair，網頁端開 COM5
```

模擬器已依廠商描述實作：SET_CONTROL 不開輸出、START 才 ON、3 秒關阻力、30 秒斷電、
est_current 依 1.5 A @ DUTY 100% 換算。

`uart_test.html` 為工廠測試台，序列梯會即時顯示走到哪一步，
右側直接解出 RPM / est_current / duty / STATUS_FLAG / ERROR_FLAG。
