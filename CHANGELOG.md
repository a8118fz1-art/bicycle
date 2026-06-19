# CHANGELOG — EMS Bike FTMS HMI

> 本檔案彙整自 `V16.*_REMARKS.txt` / `VERIFICATION.txt` 共 24 份備註檔。
> 排序：**新 → 舊**。每個版本僅註明實際變更範圍與重點，控制核心（`app.js`）在多數版本中保持不變。

---

## V16.54 — 3-STEP REST 120S FULL SEQUENCE FIX

- **Base**：V16.52
- **變更檔案**：`ui.js`（僅 3-STEP 序列邏輯）
- **未變更**：`app.js` / `index.html` / `style.css` / Home / Free Ride / ERG / Wingate / Intermittent / STOP

**3-STEP 完整序列**：
1. STEP 1 使用「性別 + 體重」計算 KP
2. START 送出 STEP 1 KP，WORK 10 秒
3. STEP 1 結束後清除輸出 KP 進入 REST
4. REST 期間依偵測到的 max RPM 計算下一 STEP KP
5. **REST 時長改為 120 秒**
6. STEP 2 送出計算後 KP，WORK 10 秒 → REST 120 秒
7. STEP 3 送出計算後 KP，WORK 10 秒
8. STEP 3 結束後進入結果頁

---

## V16.52 — HOME STATIC VISUAL SAFE 1280×800

- **Base**：V16.45
- **變更檔案**：`style.css`、`assets/home-static-final-1280x800.jpg`
- **未變更**：`app.js` / `ui.js` / `index.html`

**說明**：
- Home 頁改為靜態視覺呈現
- 原功能按鈕改為透明校準點擊區（transparent calibrated click zones）

---

## V16.45 — DEMO UI 10.1 吋橫向最佳化

- **Base**：V16.44
- **目標裝置**：10.1 吋橫向顯示器，1280×800
- **變更檔案**：`style.css`（僅）
- **未變更**：`app.js` / 控制邏輯 / STOP / KP / ERG / 3-Step 計算

**UI 調整**：
- 新增 901px+ 寬且 ≤850px 高的桌面/DEMO 橫向 media query
- 最佳化 1280×800 全頁顯示，減少垂直捲動
- 縮小 header / metric card / 調整面板 / 按鈕 / 結果卡 / 圖表 / 測試選單高度
- 保留既有響應式行動版 CSS
- Free Ride / ERG / Test Mode / 3-Step / Wingate / Intermittent 功能不變

---

## V16.44 — STOP SOFT + 3-STEP TESTED RANGE FIX

- **變更檔案**：`ui.js`
- **未變更**：`app.js` / FTMS parsing / BLE / Watt DOM binding / Intermittent / Wingate

**修正**：
1. **FREE RIDE / ERG STOP**
   - STOP 改用 `softStopOutputOnly()`
   - 透過既有 `sendKP(0, true)` 清除負載
   - 不呼叫 `app.js` 的 `stopOutput()` / `safeZeroStop()`，避免 forceZero 與即時顯示清空
   - STOP 後 RPM/Watt 通知持續，回到連線閒置狀態
2. **3-STEP 結果峰值功率**
   - 峰值功率掃描範圍改為「實際測試範圍」
   - 搜尋範圍：0.1 KP 至 `min(13.0 KP, 實際 3 步驟中使用的最大 KP)`
   - 避免外推至 13 KP（除非測試步驟真的達到 13 KP）

---

## V16.43 — STOP IDLE + 3-STEP PEAK FIX

- **變更檔案**：`ui.js`
- **未變更**：`app.js` / FTMS parsing / Watt DOM binding / Intermittent / Wingate

**修正**：
1. **FREE RIDE / ERG STOP**
   - STOP 改為 soft stop：僅清除阻力輸出
   - 不呼叫 `app.js` 的 `stopOutput()`（會觸發 forceZero 並停止即時 RPM/WATT 顯示）
   - STOP 後 BLE/FTMS 即時資料持續，回到連線閒置/無負載狀態
2. **3-STEP 結果計算**
   - 鎖定邏輯：以 0.1 KP 為步長掃描 0.1～13.0 KP
   - 最終結果掃描範圍內的最大計算功率
   - 不強制結果為剛好 13 KP

---

## V16.42 — FREE RIDE CONTROL BINDING FIX

- **變更檔案**：`ui.js`
- **未變更**：`app.js` / FTMS / BLE / Control Point / 3-STEP / Intermittent / Wingate / V16.41 Watt DOM binding

**修正**：
- FREE RIDE KP +/- 可見控制明確綁定 `#targetKp` 與 `#kpMirror`
- FREE RIDE ENTER 透過既有 `sendKP()` 送出目前可見 KP
- FREE RIDE STOP 呼叫既有 `stopOutput()`
- 3-STEP / Wingate / Intermittent 自動載入同步範圍限定於自身頁面，避免覆寫 FREE RIDE Target KP

---

## V16.41 — WATT DOM BINDING FIX

- **變更檔案**：`ui.js`
- **未變更**：`app.js` / FTMS parsing / 3-STEP 邏輯

**修正**：
1. 新增 `getCurrentWattNumber()`，從 `#wattText` 讀取最終 Watt DOM 值
2. Intermittent 即時顯示改顯示 **WATT**（非 AVG WATT）
3. Intermittent 即時 WATT 改用 `#wattText` 最終顯示值
4. Intermittent 5 秒衝刺 AVG WATT 改為平均衝刺期間收集的 `#wattText` 樣本
5. Wingate 即時 WATT 改用 `#wattText` 最終顯示值
6. Wingate 每秒結果改由 `#wattText` 樣本按秒分組建構
7. RPM 取樣與 KP 命令流程維持不變

---

## V16.39 — INTER / WINGATE WATT CALC FIX

- **變更檔案**：`ui.js`（僅 Intermittent / Wingate 結果統計）
- **未變更**：`app.js` / FTMS base / 3-STEP flow & calc

**修正**：
1. **Intermittent Test**
   - 計算序列明確化：每 5 秒衝刺 Avg RPM → Avg Watt = KP × Avg RPM × 0.98
   - 不再以瞬時 watt 樣本平均計算回合結果
   - REST 階段仍排除於 RPM/Watt 計算
2. **Wingate Test**
   - 保留 250ms RPM 取樣以穩定擷取 RPM
   - 結果統計正規化為 30 個 1 秒 bucket
   - 每秒先算 Avg RPM，再算 Watt = KP × Avg RPM × 0.98
   - Peak / Average / Fatigue Index 及圖表改用 30 秒正規化 watt 資料（非原始 250ms 樣本）

---

## V16.38 — INTER / WINGATE RPM SAMPLE FIX

- **變更檔案**：`ui.js`
- **未變更**：`app.js` / FTMS connection / parsing / Control Point / ERG / 3-STEP flow & result

**修正**：
- 為新增的 Intermittent / Wingate 模組加入 RPM cache
- Intermittent / Wingate 改為每 **250ms** 取樣 RPM（原為每秒一次）
- 對短暫顯示空隙或 FTMS 更新延遲加入最新有效 RPM 的 fallback
- Intermittent / Wingate 的 RPM 有效門檻降為 **10 rpm**（3-STEP 仍維持 20 rpm）
- Intermittent 仍只於 5 秒衝刺階段計算平均 RPM
- Wingate 仍於 30 秒衝刺期間計算 Watt = KP × RPM × 0.98

**目的**：避免 `correctedRpm` 在測試開始時短暫延遲/空白導致 NO DATA

---

## V16.37 — WINGATE START FIX

- **變更檔案**：`ui.js` / `index.html`
- **未變更**：`app.js` / 3-STEP / Intermittent

**修正**：
- 以 `ui.js` 內的真實 Wingate 測試流程取代靜態 START timeout
- START 施加「體重 × 7.5%」KP 並執行 30 秒測試計時
- 30 秒期間從 `correctedRpm` 收集有效 RPM 樣本
- Watt 計算：watt = kp × rpm × 0.98
- 30 秒後停止輸出並跳轉 Wingate 結果頁
- 結果頁改用實際收集資料（非靜態範例值）

**結果輸出**：Load KP / 有效樣本數 / Peak Power / Average Power / Fatigue Index / 每秒功率曲線

**保護**：RPM < 20 視為無效；無有效 RPM 時結果頁顯示 no-data 狀態

---

## V16.36 — INTERMITTENT TEST

- **變更檔案**：`ui.js` / `index.html` / `style.css`
- **未變更**：`app.js` / 3-STEP 已定案流程

**Intermittent Test 邏輯**：
- 負載 KP = 體重 × 7.5%，四捨五入至 0.1 KP
- 共 10 回合，每回合 = 5 秒 WORK + 20 秒 REST
- RPM 樣本僅於 5 秒 WORK 階段收集
- REST 階段不計入 RPM 平均或 Watt 計算
- 無效 RPM（< 20 rpm）忽略
- 每回合 Avg Watt = KP × Avg RPM × 0.98
- 結果圖：Y 軸 = 每回合平均功率，X 軸 = Round 1～10

**安全/相容**：保留既有 Free Ride / ERG / 3-STEP 頁面與 `app.js` BLE/控制功能；Intermittent 控制優先使用 `app.js` 既有全域 `sendKP()`

---

## V16.35 — 3-STEP RPM STABILITY

- **變更檔案**：`ui.js`（結果資料處理與顯示保護）
- **未變更**：`app.js` / FTMS 命令邏輯 / 3-STEP 計時、步驟轉換、頁面轉換

**修正**：
1. 3-STEP RPM 記錄忽略 < 20 rpm 的無效/無輸入值
2. 每步 max RPM 僅由該 10 秒步驟中實際有效 RPM 樣本計算
3. 每步內部儲存 max RPM / average RPM / 樣本數以供追溯
4. 結果計算仍用 max RPM 作為 Result 1/2/3（與既有方法一致）
5. 迴歸結果顯示完整公式：`rpm = a × kp + b`
6. 計算狀態顯示 R² 供資料品質檢視
7. 任一步驟無有效 RPM 樣本時，結果頁維持 NO DATA 狀態，不產生圖表或功率結果

---

## V16.34 — 3-STEP RESULT CALC FIX

- **變更檔案**：`ui.js` / `index.html`
- **未變更**：`app.js`

**修正**：
1. 移除 3-STEP 結果頁的靜態/範例資料
2. 結果頁僅使用 Step 1/2/3 實際收集的 max RPM
3. 無有效 RPM 時顯示 "No valid RPM data"，不顯示假 RPM 點或假功率結果
4. 迴歸計算：X 軸 = KP，Y 軸 = RPM，由 Result 1/2/3 計算迴歸線
5. 功率計算：`watt = kp × rpm × 0.98`，每 0.1 KP 計算至最大 13.0 KP，顯示範圍內最大計算功率

**驗證重點**：未踩踏時應顯示無有效 RPM 資料（無假 2286 watt、無假 RPM 圖點）；實際 RPM 輸入時應顯示實際 max RPM、迴歸線、功率曲線與最大功率

---

## V16.33 — 3-STEP FLOW FIX

- **Base**：V16.32
- **變更檔案**：`index.html` / `style.css` / `ui.js`
- **未變更**：`app.js`（SHA256 不變）

**修正**：
- 每步 STEP 計時固定 10 秒
- STEP 指示依目前執行 STEP 變化
- STEP 1/2/3 各記錄 max RPM
- STEP 2 KP 由 STEP 1 max RPM 計算；STEP 3 KP 由 STEP 2 max RPM 計算
- STEP 3 完成自動切換至 3-STEP 結果頁

**STEP 2 KP 規則**：
| STEP1 max RPM | STEP2 KP |
|---|---|
| ≥ 180 | base KP + 3 |
| ≥ 150 | base KP + 2 |
| < 150 | base KP + 1 |

**STEP 3 KP 規則**：
| STEP2 max RPM | STEP3 KP |
|---|---|
| ≥ 180 | STEP2 KP + 4 |
| ≥ 150 | STEP2 KP + 3 |
| ≥ 130 | STEP2 KP + 2 |
| < 130 | STEP2 KP + 1 |

> `ui.js` SHA256 由 `3271555c…` 變更為 `ceb68931…`（僅 3STEP FLOW）

---

## V16.32 — 3-STEP KP MAPPING FIX

- **Base**：V16.31
- **變更檔案**：`ui.js` / `index.html`（版本/快取文字）
- **未變更**：`app.js`（SHA256 不變）

**目的**：修正 3-STEP TEST STEP 1 目標 KP 計算；KP 須由性別與體重區間固定，不應隨小幅度體重調整等比例變化

**正確對照**：

| 性別 | 體重 | KP |
|---|---|---|
| 男 | < 60.0 kg | 3.0 |
| 男 | 60.0–79.9 kg | 4.0 |
| 男 | ≥ 80.0 kg | 5.0 |
| 女 | < 50.0 kg | 2.0 |
| 女 | 50.0–69.9 kg | 3.0 |
| 女 | ≥ 70.0 kg | 4.0 |

---

## V16.31 — RESPONSIVE UI PROTO

- **Base**：V16.30
- **變更檔案**：`index.html` / `style.css`
- **未變更**：`app.js` / `ui.js`（SHA256 不變）

**響應式調整**：
- `.page` 不再使用固定 `aspect-ratio: 16/10`，不再鎖定 1280×800
- 改用 `width: 100%`、`min-height: 100dvh`
- 使用 `clamp()` 調整間距
- 桌面維持寬版佈局，行動版切換為堆疊佈局
- 啟用 overflow，小螢幕可捲動

---

## V16.30 — UI MASTER FUNCTION PROTO

- **Base**：V16.25（控制核心維持 v16.17 / v16.21 RPM 修正）
- **規格來源**：`FTMS_UI_Structure_Template-V001.xlsx`
- **變更檔案**：`index.html` / `style.css` / `ui.js`
- **未變更**：`app.js`（SHA256 不變）

**目的**：第一個基於 Excel 頁面結構的功能 UI 原型，以 16:10 / 1280×800 風格頁面取代原頁面 UI，加入頁面載入/路由流程

**頁面結構**：HOME / FREE RIDE / ERG MODE / TEST MODE / 3-STEP TEST / 3-STEP RESULT / WINGATE TEST / WINGATE RESULT / INTERMITTENT TEST / INTERMITTENT RESULT

**功能對應**：
- **FREE RIDE**：ENTER → `sendKpBtn`；STOP → `stopOutputBtn`；+/- → `kpMinus/kpPlus`、`targetKp`
- **ERG MODE**：ENTER → `sendWattBtn`；STOP → 鏡像 `stopOutputBtn`；+/- → `wMinus/wPlus`、`targetWatt`
- **TEST**：沿用 `app.js` 既有 `start3Step` / `startWingate` / `startIntermittent`；結果頁暫為 UI 原型

---

## V16.25 — HOME CONNECTION SINGLE STATUS

- **Base**：V16.24
- **變更檔案**：`index.html` / `style.css` / `assets/home-bg.png`
- **未變更**：`app.js`（SHA256 不變）

**目的**：HOME 頁連線顯示只顯示單一狀態（已連線設備名稱 **或** 連線失敗警告，不同時顯示）

**顯示規則**：
| 狀態 | 顯示 |
|---|---|
| 已連線 | 已連線設備 : {device name} |
| 連線失敗 | 連線失敗 : {failure message} |
| 就緒/未連線 | 請點選 BLE 連接設備 |

> `app.js` 仍寫入隱藏來源元素 `status` / `deviceName` / `controlStatus`，HOME 可見面板僅鏡像這些狀態

---

## V16.24 — PAGE UI SOURCE FIX

- **Base**：V16.23
- **變更檔案**：`index.html` / `style.css`
- **未變更**：`app.js`（SHA256 不變）

**根因**：頁面 UI 的可見值與鏡像值分頁分離，造成來源混淆

**修正**：定義單一標準來源
- `correctedRpm`：`app.js` 更新的原始 RPM 元素
- `wattText`：`app.js` 更新的原始 Watt 元素
- 所有可見頁面值僅鏡像這些標準來源元素

**驗證**：`correctedRpm` ×1、`wattText` ×1、`freeRpmView` ×1、`ergRpmView` ×1

---

## V16.23 — PAGE UI PURE

- **Base**：V16.22
- **變更檔案**：`index.html` / `style.css`
- **未變更**：`app.js`（SHA256 不變）

**目的**：建立正常多頁 UI 結構（UI/頁面路由 only）

**UI 結構**：HOME / FREE RIDE / ERG MODE / TEST MODE（3-STEP / WINGATE / INTERMITTENT）

**實作重點**：
- `app.js` 使用的必要 DOM ID 保留
- 工程/除錯項目隱藏不移除
- 額外頁面切換腳本僅改變可見頁面並鏡像即時值，不修改控制計算或 BLE 命令

---

## V16.22 — UI CLEAN

- **Base**：V16.21
- **變更檔案**：`index.html` / `style.css`
- **未變更**：`app.js`（SHA256 不變）

**UI 變更**：隱藏工程/除錯資訊（Raw Hex / Flags / FTMS Speed / Cadence Field / Resistance / FTMS Power / Debug Log / RPM factor note），保留必要除錯元素 ID 於隱藏 DOM

**一般使用者介面保留**：連線狀態 / Device / Control / RPM / Actual Power / KP·ERG 控制 / Target KP / Target Watt / Safe Stop / Disconnect / Test Programs

---

## V16.21 — ONLY RPM FIX

- **Base**：v16.17
- **變更檔案**：`app.js`（僅 RPM factor）

**修改原則**：每次只改一項；不動穩定功能；不重構 parser；不動 Watt/ERG/Stop；僅修正 RPM factor 邏輯

**變更原因**：
- V16.2 以 `speed <= 10` 為切換條件，但該條件基於 FTMS Speed 而非真實 RPM
- 依 v16.17 測試資料，真實 10 RPM ≈ FTMS Speed 4.92 km/h
- 正確切換點應為 FTMS Speed ≤ 4.92

**修改邏輯**：
- FROM：`speed <= 10 ? speed * 2.03 : speed * 2.44`
- TO：`speed <= 4.92 ? speed * 2.03 : speed * 2.44`

**未修改**：FTMS parser / Watt table / Idle watt / KP range / ERG reverse KP / Anti-overshoot / Stop logic / BLE connection / Control Point / UI（除可見版本/註記文字）

---

## V16.2 — VERIFICATION

- **Base**：v16.17
- **變更檔案**：`app.js`（僅 RPM factor）

**RPM 邏輯**：
- ≤ 10 rpm：`speed * 2.03`
- \> 10 rpm：`speed * 2.44`

**UI 文字更新**：`index.html` 顯示註記由 0.83 / 0.895 更新為 2.03 / 2.44；新增可見標籤 V16.2 RPM FIX

> **注意**：若畫面仍顯示 0.83 / 0.895，代表瀏覽器或 Netlify 仍提供舊快取版本

---

## V16.17 — ONLY RPM FIX（原始驗證）

- **變更檔案**：`app.js`

**僅修改一行**：
- FROM：`return speed<=10?speed*0.83:speed*0.895`
- TO：`return speed<=10?speed*2.03:speed*2.44`

**未修改**：FTMS parser / Watt table / ERG / Stop / Bluetooth / Control Point / UI / Connection logic

---

*本 CHANGELOG 由 24 份 `V16.*_REMARKS.txt` / `VERIFICATION.txt` 彙整而成。*
