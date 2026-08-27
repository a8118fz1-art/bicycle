# Arduino 韌體

## ems_head_unit — EMS Bike 獨立測試用手把單元

取代上控 HMI 的硬體測試裝置。不需要電腦或瀏覽器，單機對下控跑完整的
`SET_CONTROL → START` 序列，顯示 ACK 結果、ERROR 旗標與鏈路狀態。

序列、逾時、`_confirmedRunning()` 判斷全部對照 `uart_session.js`，封包
組建與 CRC 已與 `uart.js` 逐位元組交叉比對過。

**硬體**：BLE-Nano 4.2（ATmega328P-AU）+ SSD1306 128x64 OLED + 4 顆按鍵
**相依**：U8g2、AltSoftSerial
**燒錄**：開發板 Arduino Nano，處理器 ATmega328P（失敗改 Old Bootloader）

按鍵與接線見 `docs/` 下的操作說明。

## ems_ble_bridge — BLE ↔ UART 透明測試棒

較早的另一個工具：把下控的 UART 透過 BLE 轉給電腦，讓 `uart_test.html`
不用拉線也能連。**尚未上機驗證**，目前沒有在用。

## docs/

`head-unit-guide.html` 是操作說明的原始檔，PDF 由它產生：

```bash
chrome.exe --headless=new --no-pdf-header-footer --virtual-time-budget=15000 \
  --print-to-pdf="docs/EMS手把測試單元_操作說明.pdf" "file:///<絕對路徑>/head-unit-guide.html"
```

列印樣式寫在 HTML 的 `@media print` 裡，用瀏覽器列印會得到同一份結果。
