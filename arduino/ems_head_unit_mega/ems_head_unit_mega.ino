/*
  ems_head_unit_mega.ino — EMS Bike 獨立測試用手把單元，Arduino Mega 2560 版

  ★ 這是 ems_head_unit.ino 的 Mega 2560 備援版（2026-10-12，BLE-Nano 5V 對 GND 短路燒毀）。
    功能、按鍵、遙測格式以 Nano 版 FW 0.7 為基礎（0.8M 起 Mega 版另加功能，見 FW_VERSION 註解），只有硬體相關的三處不同：
      1. 下控 UART 改用硬體 Serial1（RX1 = D19、TX1 = D18），不用 AltSoftSerial
      2. OLED I2C 在 Mega 上是 D20 = SDA、D21 = SCL（不是 A4 / A5）
      3. FW_VERSION 標 "0.15M"，回報問題時分得出是哪一版
    同一份也能燒 UNO R3 / Nano（328P），版本顯示 "0.15U"；接線跟 Nano 版一樣（D8/D9、A4/A5），見下方 Nano 版說明。
    Nano 版 ems_head_unit.ino（0.7）已不再維護，328P 板子也燒這份。

  ── 以下為原 Nano 版說明 ──

  用途：不接電腦、不開瀏覽器，單機把 EMS 下控完整操一遍。
        四顆按鍵調目標值與啟停，OLED 顯示下控回報的即時狀態，
        以及測試時最關心的東西：ACK 結果、ERROR 旗標、鏈路是否還活著。

  硬體：任何 ATmega328P 的 Nano 皆可 —— 一般版 Nano 或 BLE-Nano 4.2 都行。
        程式不使用藍牙，D0/D1 只拿來吐 ASCII 遙測；一般版走 USB、
        BLE-Nano 則是 USB 與藍牙模組同時收得到。腳位與行為完全相同。
        0.96" SSD1306 128x64 OLED（硬體 I2C，位址 0x3C）
        4 顆按鍵（INPUT_PULLUP，按下 = LOW）

  接線：
        D0 / D1        USB 序列埠 @115200（只吐 ASCII 遙測，不走協定）
        D8  = RX       ← EMS 下控 TX      AltSoftSerial，@19200 8-N-1
        D9  = TX       → EMS 下控 RX      （D8/D9 在 328P 上是固定的，改不了）
        A4 / A5        OLED I2C
        D2 D4 D6 D7    按鍵（絲印 * # ↓ ↑，功能對照見下方腳位區）

        ⚠ 4 號按鍵必須從 D8 改接 D7 —— D8 被 AltSoftSerial 佔用。
        ⚠ AltSoftSerial 另外會佔掉 D10 的 PWM，本專案用不到。

  兩條線的分工要分清楚，不要弄反：
        AltSoftSerial（D8/D9）＝ EMS 二進位協定，只跑封包
        Serial（D0/D1）        ＝ USB，只吐 ASCII 遙測
        舊案 master.ino 就是在這裡踩過雷：離開 AT 模式後的 Serial.println()
        會直接變成資料送給對端。這裡兩條線是分開的，所以 Serial 可以自由印。

  行為對照 uart_session.js（同一套序列、同一組逾時）：
        開機          → 立刻開始 1Hz HEARTBEAT，狀態 IDLE，不碰阻力
        START         → SET_CONTROL → ACK_OK → START → ACK_OK
        STOP          → 只送 STOP，心跳「不停」（停了 30 秒後下控會斷電）
        長按 #（停止） → 安全歸零：SET_CONTROL(target=0) → STOP
        調整目標值    → 只有在「下控確認 RUNNING」時才推 SET_CONTROL 出去

  與網頁版的一處刻意差異：
        uart_session.js 的 setTarget() 在未啟動時會自動補完整 arm 序列。
        實體單元不這樣做 —— 轉目標值不應該讓阻力自己上來。
        這裡 ↑ / ↓ 只改本地設定值，要按 *（開始）才會真的送出去。
*/

#include <Wire.h>
#include <U8g2lib.h>
/* 同一份原始碼也能燒 UNO R3 / Nano（ATmega328P，2026-11-03 給廠商的第二套）：
   下控改走 AltSoftSerial（D8 = RX、D9 = TX，固定腳位），OLED 走 A4 / A5，按鍵腳位不變。
   版本字尾 M = Mega、U = 328P，回報問題時分得出是哪一塊板子。 */
#if defined(__AVR_ATmega2560__)
#define FW_BOARD           "M"
#elif defined(__AVR_ATmega328P__)
#include <AltSoftSerial.h>
#define FW_BOARD           "U"
#else
#error "只支援 Mega 2560 與 ATmega328P（UNO R3 / Nano）"
#endif
#include <stdarg.h>

/* ==================== 設定 ==================== */
#define FW_VERSION "0.19" FW_BOARD  // 顯示在待機畫面上，回報問題時用來對版本；0.8M 加 SLOWDN / ZDWELL；
                                   // 0.9M：斷線逾時自動中止＋歸零、SET_CONTROL 收 ACK 才算數、SEQ DONE 自動 STOP、序列不受按鍵擋推送
                                   // 0.10M：SET 0 失敗仍送 STOP、BAD_STATE / 已停止就結束歸零、RX 斷時盲送 STOP、斷線暫停計時
                                   // 0.11M：串接計畫 60A / 60B / COMP（段間休息 300 s、對齊功率機的組）、遙測 S 行加 plan 欄位
                                   // 0.12M：功率機最多只能設 10 組 → 60A、COMP 各拆兩個計畫（60A1/60A2、CMP1/CMP2），
                                   //        組數上限改 10（含功率機穩定組）並在編譯期檢查；
                                   //        修正 LINK LOST 會把短暫歸零提早取消（10/19 60B DIP5 只歸零 ~1 s）
                                   // 0.13M：90 rpm 專用 SEQ19～22（最高 80%、每步 25 秒）與計畫 C90A / C90B
                                   // 0.14M：120 rpm 專用 SEQ23 UP0-50 與計畫 C120（UP0-50, DN40Q）
                                   // 0.15M：SEQ24 CAL50（VR1 校正確認：0→50 停 30 s、歸零 60 s × 3）
                                   // 0.16M：接收診斷 —— 每 10 s 一行 DIAG10、LINK LOST 當下一行 DIAG LOST（E 行）
                                   // 0.17M：修正假的 LINK LOST（now 比 lastRxAt 早取 → 無號相減溢位）；ACK 逾時、目標值節流同樣改有號比較
                                   // 0.18M：每 5 秒重問 SYSTEM_INFO，VIN 才會持續更新（以前靠假 LINK UP 順便問）
                                   // 0.19M：OLED 改成每圈主迴圈只畫一頁、只畫落在該頁的那幾行（主迴圈 175 ms → 數十 ms 內，
                                   //        重繪中不再久久才讀一次串口）；待機畫面第 4 行顯示收包統計；定時問 VIN 不蓋掉畫面訊息
#define EMS_BAUD          19200   // 通訊協定 §2
#define TELEM_BAUD       115200   // D0/D1 遙測輸出速率
#define OLED_ADDR          0x3C

#define HEARTBEAT_MS       1000   // 協定 §12 標稱 100ms，廠商說 1 秒即可；對 3 秒逾時有 3 倍餘裕
#define ACK_TIMEOUT_MS      600   // 同 uart_session.js 的 ackTimeoutMs
#define LINK_TIMEOUT_MS    1000   // 下控 STATUS 週期 100ms，1 秒沒收到視為斷線
#define TGT_PUSH_MS         250   // 目標值連續調整時的送出節流
#define TGT_SET_RETRY         3   // SET_CONTROL 沒收到 ACK 時最多補送幾次
/* 序列跑著時鏈路連續中斷超過這麼久就中止序列並歸零。（0.17M 更正：以前以為下控
   每 ~6.5 秒有一次 STATUS 空窗，其實是本韌體誤判，見 loop() 開頭。）5 秒遠大於 STATUS 週期 0.1 秒，不會被誤觸；
   又短於一個量測點 30～40 秒，真斷線時不會在錯的 duty 上停太久。 */
#define SEQ_LINK_ABORT_MS  5000
#define ZERO_RETRY_MS      1000   // 保證歸零：沒成功就每隔這麼久重來一次（SET 0 → STOP），直到成功
#define OLED_REFRESH_MS     150
#define VIN_POLL_MS        5000   // 0.18M：定時重問 SYSTEM_INFO（VIN）
#define TELEMETRY_MS        500   // ASCII 遙測週期，設 0 關閉
/*
  設 1 之後，每收到一筆 STATUS_REPORT 就從 D0/D1 吐一行 "R,<millis>,<rpm>"（10Hz）。
  用來抓 RPM 飄動的原始波形：開序列埠監控存成檔，就能看出是隨機雜訊、
  週期性干擾、還是計數錯誤。平常放 0，需要診斷時才開。
*/
#define RPM_TRACE             0

/* 按鍵時序 */
#define DEBOUNCE_MS          25
#define LONG_MS             800   // 長按門檻
#define REPEAT_DELAY_MS     450   // 按住多久後開始連發
#define REPEAT_RATE_MS      110

/* ==================== 腳位 ==================== */
/*
  實體按鍵絲印與功能對照（借出時的操作說明依此撰寫）：

      按鍵   腳位   功能
       ↑     D7    目標值 +
       ↓     D6    目標值 −
       *     D2    開始 / FAULT 時清除錯誤 / 長按切模式
       #     D4    停止 / 長按安全歸零

  箭頭鍵管目標值加減、* # 管啟停 —— 箭頭本來就是加減的語意，這樣最直覺。
  全靠軟體指定腳位，硬體不用改線。

  巧合但好記：按 * 鍵（開始）之後，畫面上代表「設定未生效」的 * 記號就會消失。

  ⚠ 列舉的 B_UP / B_DOWN 指的是「目標值」增減，剛好對上實體箭頭；
     但 B_START / B_STOP 對到的是 * 與 #，不是箭頭。改程式時別對錯。
*/
enum { B_DOWN = 0, B_UP = 1, B_START = 2, B_STOP = 3 };
static const uint8_t PIN_BTN[4] = { 6, 7, 2, 4 };   // 依序對應 ↓ ↑ * #；D8 → D7 見上方接線說明

/* Mega：下控走硬體 Serial1 —— D19 = RX1 ← 下控 TX，D18 = TX1 → 下控 RX。
   硬體 UART 的 RX 緩衝 64 bytes、由中斷收，比 AltSoftSerial 穩，pumpEms() 照舊呼叫即可。 */
#if defined(__AVR_ATmega2560__)
HardwareSerial &ems = Serial1;
#else
/* 328P：AltSoftSerial 的 RX 緩衝 80 bytes，約 4 包 STATUS（0.38 秒）。
   OLED 重繪中間有呼叫 pumpEms()，不會放著不收超過 40 ms。 */
AltSoftSerial ems;   // 固定 D8 = RX ← 下控 TX、D9 = TX → 下控 RX
#endif
U8G2_SSD1306_128X64_NONAME_1_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);  // _1_ = 分頁模式，只吃 128B

/* ==================== 協定常數 ==================== */
enum : uint8_t {
  CMD_START = 0x01, CMD_STOP = 0x02, CMD_RESET_ERROR = 0x03, CMD_SHUTDOWN = 0x06,
  CMD_SET_CONTROL = 0x10, CMD_GET_VERSION = 0x20, CMD_GET_SYSTEM_INFO = 0x21,
  CMD_HEARTBEAT = 0x40, CMD_STATUS_REPORT = 0x80, CMD_SYSTEM_INFO = 0x81,
  CMD_ACK = 0xF0, CMD_ERROR_REPORT = 0xF1
};

/* §6 CONTROL_MODE */
enum : uint8_t { MODE_KP = 0, MODE_ERG = 1, MODE_DUTY = 2 };

/*
  目標值一律以「協定送出的整數」保存，不用浮點（AVR 上浮點 printf 要另外連結）。
  KP   : 0.1 為單位，0~140   = 0.0~14.0 KP
  ERG  : 瓦特       ，0~3000 W（協定 v0.2 §14）
  DUTY : 0.1% 為單位，0~1000 = 0.0~100.0%
*/
static const uint16_t TGT_MAX[3]  = { 140, 3000, 1000 };
/* DUTY 用 1（＝0.1%）是為了掃低 duty 段 —— 驅動在 duty 2~3 之間電流一步跳 18 mA，
   1% 的解析度根本切不進去。點一下走 0.1%，按住改走 DUTY_PRESET（見 dutyPreset()）。 */
static const uint16_t TGT_STEP[3] = {   1,    5,    1 };

/* DUTY 按住時依序停靠的檔位（0.1% 為單位）。
   功率機量測都是整數點，舊的「連發 15 次後每次跳 8%」很容易衝過頭；
   停靠檔位的話，從 60 降到 30 就是 60→50→40→30，不會越過目標。 */
static const uint16_t DUTY_PRESET[] PROGMEM = {
  0, 50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 750, 800, 900, 1000
};
#define DUTY_PRESET_N     (sizeof(DUTY_PRESET) / sizeof(DUTY_PRESET[0]))
#define DUTY_PRESET_EVERY 4    // 連發每 4 次（約 0.44 秒）走一檔

static const char MODE_N0[] PROGMEM = "KP";
static const char MODE_N1[] PROGMEM = "ERG";
static const char MODE_N2[] PROGMEM = "DUTY";
static const char* const MODE_NAME[] PROGMEM = { MODE_N0, MODE_N1, MODE_N2 };

static const char CN_START[]  PROGMEM = "START";
static const char CN_STOP[]   PROGMEM = "STOP";
static const char CN_RESET[]  PROGMEM = "RESET";
static const char CN_SETCTL[] PROGMEM = "SETCTL";

/* §8 ACK_RESULT */
static const char AR0[] PROGMEM = "OK";
static const char AR1[] PROGMEM = "CRC_ERR";
static const char AR2[] PROGMEM = "PARAM_ERR";
static const char AR3[] PROGMEM = "BUSY";
static const char AR4[] PROGMEM = "UNK_CMD";
static const char AR5[] PROGMEM = "BAD_STATE";
static const char* const ACK_NAME[] PROGMEM = { AR0, AR1, AR2, AR3, AR4, AR5 };

/* ==================== CRC-16/CCITT-FALSE ==================== */
/* init 0xFFFF、poly 0x1021、不反射、不做最終 XOR；涵蓋 LEN + CMD + DATA */
static uint16_t crc16ccitt(const uint8_t *p, uint8_t n) {
  uint16_t crc = 0xFFFF;
  while (n--) {
    crc ^= (uint16_t)(*p++) << 8;
    for (uint8_t i = 0; i < 8; i++)
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
  }
  return crc;
}

static inline uint16_t rd16(const uint8_t *p) { return (uint16_t)p[0] | ((uint16_t)p[1] << 8); }

/* ==================== 堆疊高水位量測 ==================== */
/*
  裝上真正的 AltSoftSerial 之後全域變數吃掉 1233 / 2048 bytes（AltSoftSerial
  自己就佔 303，RPM 波形緩衝再 122）。實機量到的堆疊高水位是 242 bytes，
  對目前剩下的餘裕有 2.8 倍空間。

  註：所有 snprintf 格式字串都改用 snprintf_P + PSTR。AVR 的字面字串預設
  放 RAM，這一項就省了 158 bytes。新增格式字串時記得沿用 _P 版本。

  做法：開機時把堆疊還沒碰過的區域塗成固定樣式，之後數還有多少沒被蓋掉，
  就是真實的剩餘餘裕 —— 中斷處理常式壓的堆疊也算得進去。
*/
#define RAM_PAINT 0xC5
extern uint8_t __heap_start;
extern uint8_t *__brkval;

static uint8_t *heapTop() {
  return (uint8_t *)(__brkval ? (uint16_t)__brkval : (uint16_t)&__heap_start);
}

static void paintFreeRam() {
  uint8_t *p = heapTop();
  uint8_t *sp = (uint8_t *)SP;
  /* 留 32 bytes 不塗，免得蓋掉現在這層自己的呼叫框 */
  while (p < sp - 32) *p++ = RAM_PAINT;
}

/* 回傳「從來沒被堆疊碰過」的位元組數 */
static uint16_t ramHeadroom() {
  uint8_t *p = heapTop();
  uint16_t n = 0;
  while (n < 2048 && p[n] == RAM_PAINT) n++;
  return n;
}

static void copyP(char *out, uint8_t cap, PGM_P src) {
  strncpy_P(out, src, cap - 1);
  out[cap - 1] = 0;
}

/* ==================== 執行階段狀態 ==================== */
static uint8_t  mode   = MODE_KP;
static uint16_t target = 50;        // 開機預設 KP 5.0；還沒送出去，按 START 才生效

/* 下控最近一次 STATUS_REPORT */
static struct {
  uint16_t rpm, mA, watt, dutyX10, tgt, err;
  uint8_t  mode, flags;
  bool     valid;
} sr;

static bool     linkAlive   = false;
static uint32_t lastRxAt    = 0;    // 收到任何合法封包的時刻
static uint32_t lastHbAt    = 0;
static bool     faulted     = false;

/*
  RPM 統計。實機第一次上機就抓到下控回報 RPM_FAIL(0x02)，而且靜止時
  RPM 讀到 1431 —— 「會飄」這種描述沒辦法拿去跟廠商對，所以這裡把
  最小/最大/樣本數記下來，直接給數字。按 * 送 RESET_ERROR 時一併歸零。
*/
static uint16_t rpmMin = 0xFFFF, rpmMax = 0;
static uint32_t rpmSamples = 0;

/*
  RPM 波形環形緩衝。min/max 有個致命盲點：它分不出「大部分正常、偶爾尖峰」
  和「從頭到尾都是垃圾」—— 而這兩種的成因與修法完全不同。
  存最近 TRACE_W 筆（10Hz → 12 秒），RPM_FAIL 亮起時直接畫在畫面上，
  現場不用接電腦就看得出飄動的形狀。
  縱軸以目前的 rpmMax 自動縮放，所以看的是相對形狀而非絕對值。
*/
#define TRACE_W 120
static uint8_t traceBuf[TRACE_W];      // 已縮放到 0..15
static uint8_t traceIdx = 0;
static bool    traceFull = false;

static void rpmStatsReset() {
  rpmMin = 0xFFFF; rpmMax = 0; rpmSamples = 0;
  traceIdx = 0; traceFull = false;
}

/* 目前在等哪一個 cmd 的 ACK；0 = 沒有在等 */
static uint8_t  pendCmd = 0;
static uint32_t pendAt  = 0;

/* 動作序列。對應 uart_session.js 的 arm() / stop() / safeZero() */
enum : uint8_t {
  SQ_NONE, SQ_ARM_SET, SQ_ARM_START, SQ_SET, SQ_STOP, SQ_ZERO_SET, SQ_ZERO_STOP, SQ_RESET,
  SQ_DIP
};
static uint8_t seq = SQ_NONE;

/* 磁滯測試用「降阻力前自動歸零」：DUTY 模式跑著時點一下 START 切換開關。
   開啟後，只要送出的新目標值比上一次送出的低，就先送 duty 0、
   停 DIP_MS[dipIdx] 毫秒、再送新值 —— 這正是要建議廠商做進韌體的邏輯，
   用來量最短要歸零多久才能消掉磁滯。長按 START 換長度。 */
static const uint16_t DIP_MS[] PROGMEM = { 500, 1000, 2000, 5000 };
#define DIP_N (sizeof(DIP_MS) / sizeof(DIP_MS[0]))
static bool     dipAuto  = false;
static uint8_t  dipIdx   = 1;     // 預設 1 秒
static uint8_t  dipPhase = 0;     // 0 = 沒在歸零，1 = 待送 0，2 = 歸零中
static uint8_t  dipRetry = 0;
static uint32_t dipT0    = 0;
static uint16_t dipLenMs = 1000;  // 這一次歸零的長度；手動模式取 DIP_MS[dipIdx]，序列模式由步驟指定
static uint16_t lastSent = 0;     // 最後一次「下控 ACK 確認過」的 SET_CONTROL 目標值（0.9M 起收到 ACK 才更新）
static uint16_t pendVal  = 0;     // 送出中、還在等 ACK 的 SET_CONTROL 目標值
/* 保證歸零（0.9M）：設起來後主迴圈會一直嘗試 SET_CONTROL(0) → STOP，兩個都 ACK OK 才清掉。
   斷線時先等，鏈路回來立刻送；失敗就每 ZERO_RETRY_MS 重來。避免最後一包沒送到、下控停在 30%。 */
static bool     zeroPending = false;
static uint16_t zeroTries   = 0;
static uint32_t zeroAt      = 0;
static PGM_P    zeroWhy     = NULL;   // 0.10M：觸發歸零的原因（SEQ DONE / ABORT），結果訊息附在後面不蓋掉
static uint32_t blindStopAt = 0;      // 0.10M：RX 斷線時盲送 STOP 的節流

/* ==================== 自動測試序列（FW 0.7 起，0.9M 修改） ====================
   磁滯量測要切幾十個 duty、每段停固定秒數，手動按容易按錯（10/08 H 輪衝到 63.6、掉到 0.9）。
   序列跑在 DUTY 協定模式上；畫面上是第 4 個模式「SEQ」，長按 START 切過去。
   每一步：{ duty×10, 停留秒數, 切換前先歸零的毫秒數（0 = 直接切） }。
   功率機轉速由人工設定，序列本身與踏頻無關。 */
struct SeqStep { uint16_t duty, holdS, dipMs; };

/* 每個序列都要在 600 秒內跑完：功率機一次記錄最長 600 秒，而且中途不能存檔。
   所以「讓殘留消失的 5 分鐘」拆成獨立的 REST5，那段不用錄 —— 流程是
   功率機按記錄 → 點 * → SEQ DONE → 功率機存檔 →（需要乾淨狀態時）跑 REST5 → 下一個。
   每個量測序列都以 0/40 開頭（量 tare）、0/30 結尾。 */
static constexpr SeqStep SQS_REST[] PROGMEM = { {0,300,0} };              // 不用錄
static constexpr SeqStep SQS_HOLD[] PROGMEM = {      // 從 60 直接降到 30 後停 5 分鐘：偏差會不會自己回落（480 秒）
  {0,40,0},{300,40,0},{0,30,0},{600,40,0},{300,300,0},{0,30,0} };
static constexpr SeqStep SQS_PTHA[] PROGMEM = {      // 60→30 直接降（220 秒）
  {0,40,0},{300,40,0},{0,30,0},{600,40,0},{300,40,0},{0,30,0} };
static constexpr SeqStep SQS_PTHB[] PROGMEM = {      // 60→50→40→30 分段降，跟 PATH-A 比（230 秒）
  {0,40,0},{600,40,0},{500,40,0},{400,40,0},{300,40,0},{0,30,0} };
static constexpr SeqStep SQS_REVA[] PROGMEM = {      // 60→30→45（190 秒）
  {0,40,0},{600,40,0},{300,40,0},{450,40,0},{0,30,0} };
static constexpr SeqStep SQS_REVB[] PROGMEM = {      // 從 0 直接上 45，跟 REV-A 比（110 秒）
  {0,40,0},{450,40,0},{0,30,0} };
static constexpr SeqStep SQS_UP[]   PROGMEM = {      // 上升曲線低段（350 秒）
  {0,40,0},{100,40,0},{200,40,0},{300,40,0},{400,40,0},{500,40,0},{600,40,0},{700,40,0},{0,30,0} };
static constexpr SeqStep SQS_UPHI[] PROGMEM = {      // 上升曲線高段，分開跑以免功率機熱累積跳保護（160 秒）
  {0,40,0},{800,30,0},{900,30,0},{1000,30,0},{0,30,0} };
static constexpr SeqStep SQS_D100[] PROGMEM = {      // 下降曲線：從 100 往下（440 秒）
  {0,40,0},{1000,30,0},{900,30,0},{800,30,0},{700,40,0},{600,40,0},{500,40,0},{400,40,0},
  {300,40,0},{200,40,0},{100,40,0},{0,30,0} };
static constexpr SeqStep SQS_D80[]  PROGMEM = {      // 380 秒
  {0,40,0},{800,30,0},{700,40,0},{600,40,0},{500,40,0},{400,40,0},{300,40,0},{200,40,0},{100,40,0},{0,30,0} };
static constexpr SeqStep SQS_D60[]  PROGMEM = {      // 310 秒
  {0,40,0},{600,40,0},{500,40,0},{400,40,0},{300,40,0},{200,40,0},{100,40,0},{0,30,0} };
static constexpr SeqStep SQS_D40[]  PROGMEM = {      // 230 秒
  {0,40,0},{400,40,0},{300,40,0},{200,40,0},{100,40,0},{0,30,0} };
/* 降阻力前歸零 N 毫秒：每個都自帶「從 0 升上來的 30」當同一檔的基準（各 220 秒） */
static constexpr SeqStep SQS_DP05[] PROGMEM = { {0,40,0},{300,40,0},{0,30,0},{600,40,0},{300,40,500},{0,30,0} };
static constexpr SeqStep SQS_DP1[]  PROGMEM = { {0,40,0},{300,40,0},{0,30,0},{600,40,0},{300,40,1000},{0,30,0} };
static constexpr SeqStep SQS_DP2[]  PROGMEM = { {0,40,0},{300,40,0},{0,30,0},{600,40,0},{300,40,2000},{0,30,0} };
static constexpr SeqStep SQS_DP5[]  PROGMEM = { {0,40,0},{300,40,0},{0,30,0},{600,40,0},{300,40,5000},{0,30,0} };
static constexpr SeqStep SQS_SLOW[] PROGMEM = {  // 0→60 後每 10 秒降 1% 至 30，停 40 秒→0（440 秒）
  {0,40,0},{600,40,0},
  {590,10,0},{580,10,0},{570,10,0},{560,10,0},{550,10,0},{540,10,0},{530,10,0},{520,10,0},
  {510,10,0},{500,10,0},{490,10,0},{480,10,0},{470,10,0},{460,10,0},{450,10,0},{440,10,0},
  {430,10,0},{420,10,0},{410,10,0},{400,10,0},{390,10,0},{380,10,0},{370,10,0},{360,10,0},
  {350,10,0},{340,10,0},{330,10,0},{320,10,0},{310,10,0},
  {300,40,0},{0,30,0} };
static constexpr SeqStep SQS_ZDWL[] PROGMEM = {  // 純 0→30→0 停 10/30/120 秒再上 30（390 秒）
  {0,40,0},{300,40,0},{0,10,0},{300,40,0},{0,30,0},{300,40,0},{0,120,0},{300,40,0},{0,30,0} };
/* 0.13M：90 rpm 專用（Q = quick）。
   · 最高只到 80%：90 rpm 時 KP14 只需要 duty 約 77%，90～100% 產品用不到；
     而且 90 rpm 的功率約是 60 rpm 的 1.55 倍（duty 80 ≈ 1350 W），10/19 60A2 在 60 rpm 的 DN100
     熱機時就在 50% 跳保護，90 rpm 照原樣跑一定撐不住。
   · 每步 25 秒（duty 10 維持 40 秒，它穩得慢）：10/19 60A1 / 60B 共 30 個平台實測，
     扭力 90% 在 13.1 秒內穩定，12～25 秒的平均與 40 秒全段平均差中位 0.07%、最大 0.51%。
     熱量也少約三分之一。
   · 40 / 60 rpm 的 SEQ7～12 不動：舊板、新板要用同一份腳本比。 */
static constexpr SeqStep SQS_U80Q[] PROGMEM = {  // 上升到 80（265 秒）
  {0,25,0},{100,40,0},{200,25,0},{300,25,0},{400,25,0},{500,25,0},{600,25,0},{700,25,0},{800,25,0},{0,25,0} };
static constexpr SeqStep SQS_D80Q[] PROGMEM = {  // 從 80 往下（265 秒）
  {0,25,0},{800,25,0},{700,25,0},{600,25,0},{500,25,0},{400,25,0},{300,25,0},{200,25,0},{100,40,0},{0,25,0} };
static constexpr SeqStep SQS_D60Q[] PROGMEM = {  // 從 60 往下（215 秒）
  {0,25,0},{600,25,0},{500,25,0},{400,25,0},{300,25,0},{200,25,0},{100,40,0},{0,25,0} };
static constexpr SeqStep SQS_D40Q[] PROGMEM = {  // 從 40 往下（165 秒）
  {0,25,0},{400,25,0},{300,25,0},{200,25,0},{100,40,0},{0,25,0} };
/* 0.14M：120 rpm 只做到 50%。120 rpm 時 KP14 需要 duty 約 75%（約 1.75 kW），已碰到功率機
   冷機最高紀錄 1748 W，全範圍做不到；50% 約 1.28 kW、只停 25 秒。50% 以上用 90 rpm 的高 duty 補。 */
static constexpr SeqStep SQS_U50Q[] PROGMEM = {  // 上升到 50（190 秒）
  {0,25,0},{100,40,0},{200,25,0},{300,25,0},{400,25,0},{500,25,0},{0,25,0} };
/* 0.15M：VR1 校正確認（2026-10-22 改標準：60 rpm、duty 50 = 600 W ±1%，取代 duty 100 = 1000 W）。
   每次都從 0 直接上 50（不從高往下降，避開磁滯），停 30 秒取 15～30 秒的讀值，歸零 60 秒，共 3 次。
   全長 300 秒，功率機一組就錄得完（F2 → 穩定後 F1 + * → SEQ DONE 後 F1）。 */
static constexpr SeqStep SQS_CAL50[] PROGMEM = {
  {0,30,0},{500,30,0},{0,60,0},{500,30,0},{0,60,0},{500,30,0},{0,60,0} };

struct SeqDef { const char *name; const SeqStep *steps; uint8_t n; };
static const char SN1[]  PROGMEM = "REST5";  static const char SN2[]  PROGMEM = "HOLD5";
static const char SN3[]  PROGMEM = "PATH-A"; static const char SN4[]  PROGMEM = "PATH-B";
static const char SN5[]  PROGMEM = "REV-A";  static const char SN6[]  PROGMEM = "REV-B";
static const char SN7[]  PROGMEM = "UP0-70"; static const char SN8[]  PROGMEM = "UP80+";
static const char SN9[]  PROGMEM = "DN100";  static const char SN10[] PROGMEM = "DN80";
static const char SN11[] PROGMEM = "DN60";   static const char SN12[] PROGMEM = "DN40";
static const char SN13[] PROGMEM = "DIP.5";  static const char SN14[] PROGMEM = "DIP1";
static const char SN15[] PROGMEM = "DIP2";   static const char SN16[] PROGMEM = "DIP5";
static const char SN17[] PROGMEM = "SLOWDN"; static const char SN18[] PROGMEM = "ZDWELL";
static const char SN19[] PROGMEM = "UP0-80"; static const char SN20[] PROGMEM = "DN80Q";
static const char SN21[] PROGMEM = "DN60Q";  static const char SN22[] PROGMEM = "DN40Q";
static const char SN23[] PROGMEM = "UP0-50"; static const char SN24[] PROGMEM = "CAL50";
#define SQN(a) (uint8_t)(sizeof(a) / sizeof(a[0]))
#define SQ(n, a) { n, a, SQN(a) }
static constexpr SeqDef SEQS[] PROGMEM = {
  SQ(SN1, SQS_REST), SQ(SN2, SQS_HOLD), SQ(SN3, SQS_PTHA), SQ(SN4, SQS_PTHB),
  SQ(SN5, SQS_REVA), SQ(SN6, SQS_REVB), SQ(SN7, SQS_UP),   SQ(SN8, SQS_UPHI),
  SQ(SN9, SQS_D100), SQ(SN10, SQS_D80), SQ(SN11, SQS_D60), SQ(SN12, SQS_D40),
  SQ(SN13, SQS_DP05), SQ(SN14, SQS_DP1), SQ(SN15, SQS_DP2), SQ(SN16, SQS_DP5),
  SQ(SN17, SQS_SLOW), SQ(SN18, SQS_ZDWL),
  SQ(SN19, SQS_U80Q), SQ(SN20, SQS_D80Q), SQ(SN21, SQS_D60Q), SQ(SN22, SQS_D40Q),
  SQ(SN23, SQS_U50Q), SQ(SN24, SQS_CAL50) };
#define SEQ_N SQN(SEQS)

/* ==================== 串接計畫（0.11M） ====================
   一個計畫 = 幾個 SEQ 依序跑，段與段之間插一段休息（REST5 同一個序列：阻力 0、下控持續 RUNNING），
   最後一段後面不休息，直接 PLAN DONE → 保證歸零（SET 0 → STOP），跟 SEQ DONE 走同一條路。
   每一段、每一段休息都是功率機設定頁的「一組」，所以組數 = 2 × 段數 − 1。

   時間軸（秒，從操作員按下 * 開始計畫、同時在功率機按第一下 F1 那一刻算起）：
     第 k 組的 Mega 長度   M_k = 該 SEQ 各步秒數總和（休息組 = REST5 = 300）
     功率機設定頁組長      G_k = M_k + PLAN_MARGIN_S，進位到 10 秒
     第 k 組開始（送 F1）  T_k = Σ_{j<k} (G_j + PLAN_GAP_S)
   Mega 在 T_k 才開始第 k 組（絕對排程，不會越跑越偏）；內容跑完到 T_{k+1} 之間停在阻力 0 等待（HOLD）。
   功率機在 T_k + G_k 就停錄這一組，所以內容（含 0.10M 斷線暫停延長）拖到 T_k + G_k − PLAN_LATE_GUARD_MS 還沒跑完
   → PLAN ABORT: LATE ＋ 保證歸零（最後一組也一樣），不讓內容被靜默截斷或跟功率機錯組。
   對齊：操作員「先按功率機 F1，3 秒內再按 *」；planT0 取在按 * 那一刻，比 F1 晚 ≤3 s，從 30 s 餘裕扣。
   dyno_f1timer/gen_plans.py 直接解析本檔這些表與常數產生 plans.json，不要手抄到別處。 */
#define PLAN_REST_SEQ       1    // 休息用哪個 SEQ（1 = REST5，{0,300}）
#define PLAN_MARGIN_S      30    // 組長餘裕：F1 對時誤差 + 0.10M 斷線暫停計時的累積（見 arduino/docs/DYNO_GROUP_TABLE.md）
#define PLAN_GAP_S          5    // 功率機上一組錄完到下一次 F1 的間隔（REVIEW.md H1）
#define PLAN_LATE_GUARD_MS 6000  // 內容必須在功率機這組停錄前至少這麼久跑完：* 比 F1 晚 ≤3 s ＋ F1 延遲 ＋ 時鐘漂移（REVIEW_2_claude M2）
/* 0.12M：實際功率機設定頁最多只能設 10 組（第 11 組以後畫面顯示不出來，2026-10-19 確認），
   其中第 1 組是 F2 開始的穩定組，所以 Mega 一個計畫最多 9 組 = 5 段 + 4 段休息。 */
#define PLAN_MAX_GROUPS    10    // 功率機設定頁最多 10 組（含穩定組）
#define DYNO_GROUP_MAX_S  600    // 功率機每組上限 600 秒

struct PlanDef { const char *name; const uint8_t *segs; uint8_t n; };
/* 段 = SEQ 編號（1 起算，跟畫面上 SEQn 一樣）。名稱最多 4 字（畫面 PLAN %-4s、事件 P%s G…）。
   0.12M：60A、COMP 原本各 6 段（11 組）超過上限，各拆成兩個 3 段計畫（5 組，功率機設 6 組）。
   COMP 拆法刻意把兩個最重的段 UP80+（SEQ8）與 DN100（SEQ9）分到不同計畫：
   90 rpm 時這兩段各要連續 90 秒吃 1.35～1.56 kW，放同一輪功率機容易熱累積跳保護。
   升、降曲線之間都隔 5 分鐘休息、互不影響，所以段的先後不影響數據。 */
static constexpr uint8_t PLS_60A1[] PROGMEM = { 18, 7, 8 };          // ZDWELL, UP0-70, UP80+
static constexpr uint8_t PLS_60A2[] PROGMEM = { 9, 10, 11 };         // DN100, DN80, DN60
static constexpr uint8_t PLS_60B[]  PROGMEM = { 12, 13, 14, 15, 16 }; // DN40, DIP.5, DIP1, DIP2, DIP5
static constexpr uint8_t PLS_CMP1[] PROGMEM = { 7, 8, 11 };          // UP0-70, UP80+, DN60
static constexpr uint8_t PLS_CMP2[] PROGMEM = { 9, 10, 12 };         // DN100, DN80, DN40
/* 0.13M：90 rpm 專用，兩個計畫之間讓功率機冷卻 15～20 分鐘。兩個最重的段（UP0-80 的 60～80、
   DN80Q 的 80～50）分在不同計畫，各配一個輕的段。 */
static constexpr uint8_t PLS_C90A[] PROGMEM = { 19, 21 };            // UP0-80, DN60Q
static constexpr uint8_t PLS_C90B[] PROGMEM = { 20, 22 };            // DN80Q, DN40Q
/* 0.14M：120 rpm（冷機開始，跑前確認功率機額定功率） */
static constexpr uint8_t PLS_C120[] PROGMEM = { 23, 22 };            // UP0-50, DN40Q
static const char PN1[] PROGMEM = "60A1"; static const char PN2[] PROGMEM = "60A2";
static const char PN3[] PROGMEM = "60B";  static const char PN4[] PROGMEM = "CMP1";
static const char PN5[] PROGMEM = "CMP2"; static const char PN6[] PROGMEM = "C90A";
static const char PN7[] PROGMEM = "C90B"; static const char PN8[] PROGMEM = "C120";
/* 順序 = 計畫編號（遙測 plan / sel 欄）；head_unit_logger.html 的 PLAN_NAME 與 dyno_f1timer.py 的 PLAN_IDS 要同步 */
static constexpr PlanDef PLANS[] PROGMEM = {
  { PN1, PLS_60A1, SQN(PLS_60A1) }, { PN2, PLS_60A2, SQN(PLS_60A2) }, { PN3, PLS_60B, SQN(PLS_60B) },
  { PN4, PLS_CMP1, SQN(PLS_CMP1) }, { PN5, PLS_CMP2, SQN(PLS_CMP2) },
  { PN6, PLS_C90A, SQN(PLS_C90A) }, { PN7, PLS_C90B, SQN(PLS_C90B) }, { PN8, PLS_C120, SQN(PLS_C120) } };
#define PLAN_N SQN(PLANS)

/* ---- 編譯期檢查：只在編譯時讀表（執行時 PROGMEM 一律走 pgm_read） ---- */
/* 包在 struct 裡：Arduino 會把自由函式的原型搬到檔案最前面（那時 SeqStep 還沒宣告） */
struct Cx {
  static constexpr uint32_t cxStepsSum(const SeqStep *p, uint8_t n) {
  return n ? (uint32_t)p[n - 1].holdS + cxStepsSum(p, (uint8_t)(n - 1)) : 0; }
  static constexpr uint32_t cxSeqS(uint8_t no) { return cxStepsSum(SEQS[no - 1].steps, SEQS[no - 1].n); }
  static constexpr uint8_t  cxGroups(uint8_t n) { return n ? (uint8_t)(2 * n - 1) : 0; }
  static constexpr uint32_t cxDynoS(uint32_t megaS) { return (megaS + PLAN_MARGIN_S + 9) / 10 * 10; }
  static constexpr bool cxSegsOk(const uint8_t *g, uint8_t n) {
  return n == 0 || (g[n - 1] >= 2 && g[n - 1] <= SEQ_N && cxDynoS(cxSeqS(g[n - 1])) <= DYNO_GROUP_MAX_S &&
                      cxSegsOk(g, (uint8_t)(n - 1))); }
  static constexpr bool cxPlansOk(uint8_t i) {
  return i == 0 || (PLANS[i - 1].n >= 1 && cxGroups(PLANS[i - 1].n) + 1 <= PLAN_MAX_GROUPS &&   // +1 = 穩定組
                      cxSegsOk(PLANS[i - 1].segs, PLANS[i - 1].n) && cxPlansOk((uint8_t)(i - 1))); }
};
static_assert(Cx::cxSeqS(PLAN_REST_SEQ) == 300, "休息段必須是 REST5（300 s）");
static_assert(Cx::cxDynoS(Cx::cxSeqS(PLAN_REST_SEQ)) <= DYNO_GROUP_MAX_S, "休息組超過功率機每組上限");
static_assert(Cx::cxPlansOk(PLAN_N), "某計畫功率機超過 10 組（含穩定組，即 Mega 最多 5 段）、某組超過 600 s，或段不是 SEQ2～SEQ_N");
static_assert(SEQ_N + PLAN_N < 255, "選單索引溢位");
static_assert(PLAN_MARGIN_S * 1000UL > PLAN_LATE_GUARD_MS + 3000UL + 1000UL + 5000UL,
              "餘裕要大於 LATE 保護 + F1/* 對時 3 s + arm 1 s + 至少 5 s 斷線暫停");
/* LATE 保護的預算：狀態檔延遲 / F1 延遲 ~2 s ＋ 第 1 組 * 3 s ＋ 組內漂移 ≤1.3 s ≈ 6 s；太大會白白吃掉斷線容許（REVIEW_4 R4-L6） */
static_assert(PLAN_LATE_GUARD_MS >= 6000UL && PLAN_LATE_GUARD_MS <= 8000UL, "PLAN_LATE_GUARD_MS 應在 6000～8000");

static bool     uiSeq      = false;   // 畫面在 SEQ 模式（協定上仍是 MODE_DUTY）
static uint8_t  seqSel     = 0;       // 選中的序列（0 起算）
static bool     seqActive  = false;
static bool     seqStarted = false;   // 下控確認 RUNNING 之後才開始計時
static uint8_t  seqIdx     = 0;
static uint32_t seqStepT0  = 0;
static uint32_t seqNotRun  = 0;       // 開始後下控不在 RUNNING 的起點，超過 3 秒就中止
static uint8_t  uiSel      = 0;       // 0.11M：SEQ 畫面選單（0..SEQ_N-1 = 單一序列，之後 = 計畫）
static bool     planActive = false;   // 0.11M：計畫執行中（seqActive 也會是 true）
static uint8_t  planId     = 0;       // 1 起算，0 = 沒有計畫（遙測用）
static uint8_t  planGrp    = 0;       // 目前第幾組（0 起算）
static bool     planHold   = false;   // 這組內容跑完，阻力 0 等下一組
static uint32_t planT0     = 0;       // 計畫開始（= 功率機第一下 F1）
static uint32_t planNextAt = 0;       // 下一組開始的 millis（相對 planT0 的絕對排程）
static uint32_t planLateAt = 0;       // 這組內容最晚要跑完的 millis（功率機停錄 − PLAN_LATE_GUARD_MS）

/* 參數用 void*：Arduino 會把函式原型自動插到檔案最前面，那時 SeqStep 還沒宣告 */
static void seqStepRead(uint8_t i, void *s) {
  const SeqStep *p = (const SeqStep *)pgm_read_ptr(&SEQS[seqSel].steps);
  memcpy_P(s, &p[i], sizeof(SeqStep));
}
static uint8_t seqLen() { return pgm_read_byte(&SEQS[seqSel].n); }

/* ---- 0.11M 計畫：執行期讀 PROGMEM（公式與上面編譯期檢查相同） ---- */
static uint16_t seqTotalS(uint8_t idx0) {
  const SeqStep *p = (const SeqStep *)pgm_read_ptr(&SEQS[idx0].steps);
  uint8_t n = pgm_read_byte(&SEQS[idx0].n);
  uint16_t t = 0;
  for (uint8_t i = 0; i < n; i++) t += pgm_read_word(&p[i].holdS);
  return t;
}
static uint8_t planSegs() { return pgm_read_byte(&PLANS[planId - 1].n); }
static uint8_t planGroups() { return (uint8_t)(2 * planSegs() - 1); }
static bool    planIsRest(uint8_t g) { return g & 1; }
static uint8_t planSeqIdx(uint8_t g) {         // 第 g 組用哪個 SEQ（0 起算）
  if (planIsRest(g)) return PLAN_REST_SEQ - 1;
  const uint8_t *p = (const uint8_t *)pgm_read_ptr(&PLANS[planId - 1].segs);
  return (uint8_t)(pgm_read_byte(&p[g / 2]) - 1);
}
static uint32_t planDynoS(uint8_t g) {         // G_g：功率機這組的組長（秒）
  return (uint32_t)(seqTotalS(planSeqIdx(g)) + PLAN_MARGIN_S + 9) / 10 * 10;
}
static uint32_t planGroupStartS(uint8_t g) {   // T_g：第 g 組開始（秒，從 planT0 起算）
  uint32_t t = 0;
  for (uint8_t j = 0; j < g; j++) t += planDynoS(j) + PLAN_GAP_S;
  return t;
}
/* 第 g 組的兩個時刻：下一組開始（最後一組 = 0 不用）、內容最晚完成（LATE 門檻） */
static void planSetGroupTimes(uint8_t g) {
  uint32_t tg = planGroupStartS(g);
  planNextAt = (g + 1 < planGroups()) ? planT0 + (tg + planDynoS(g) + PLAN_GAP_S) * 1000UL : 0;
  planLateAt = planT0 + (tg + planDynoS(g)) * 1000UL - PLAN_LATE_GUARD_MS;
}
/* 內容（不是 HOLD）到了 LATE 門檻還沒跑完 */
static bool planLate(uint32_t now) {
  return planActive && !planHold && (int32_t)(now - planLateAt) >= 0;
}

static bool     tgtDirty = false;
static uint32_t tgtDirtyAt = 0;
static uint8_t  tgtRetry = 0;     // SET_CONTROL 沒收到 ACK 時已經補送幾次

/*
  §14 開機序列的查詢結果。這兩個指令「不回 ACK」，是直接回資料包
  （附錄 A-9 / A-10，CRC 已對過）：
     GET_VERSION(0x20)     → 回應 CMD 也是 0x20，DATA = major minor patch
     GET_SYSTEM_INFO(0x21) → 回應 CMD 是 0x81，DATA = vin_lo vin_hi major minor patch

  ⚠ VIN 的單位規格書與實機不符：
     附錄 A-10 的範例 0x0C8F = 3215 標註為 32.15V，隱含 0.01V/LSB；
     但實機在 24V 供電下回報 24030，那是 mV（24.030V）。3215 若為 mV 只有 3.2V，
     不可能是文件寫的 32.15V，所以兩者確實矛盾。這裡依「實機」以 mV 解讀。
     已列為待廠商確認事項第 12 條。
*/
static uint16_t vinMv    = 0;
static uint16_t lastErr  = 0;   // 用來偵測 error 旗標的上升緣
static uint8_t  fw[3]    = { 0, 0, 0 };
static bool     sysValid = false;

/* 查詢狀態機：0=待送VER 1=等VER 2=待送INFO 3=等INFO 4=完成或放棄 */
static uint8_t  sysStep = 0, sysRetry = 0;
static uint32_t sysAt = 0;
static bool     sysQuiet = false;   // 0.19M：這次 SYSTEM_INFO 是定時輪詢，結果只寫 E 行、不蓋掉畫面訊息

/* 這次 FAULT 期間是否已經試過 RESET_ERROR。
   試過還清不掉的話，下一次按 START 就直接送 arm 序列 ——
   用來測「下控在 FAULT 下到底接不接受 START」，也就是 PROTOCOL_NOTES 第 3 條。 */
static bool resetTried = false;

/* 畫面最後一行的事件訊息 */
static char msg[22] = "";

/* 事件同時往 D0/D1 吐一行，PC 端才有完整時序歷史 ——
   畫面只留得住最後一則，抓瞬時現象時不夠用。 */
static void emitEvent() {
#if TELEMETRY_MS
  Serial.print(F("E,")); Serial.print(millis());
  Serial.print(','); Serial.println(msg);
#endif
}

static void setMsgP(PGM_P s) { copyP(msg, sizeof(msg), s); emitEvent(); }

/* 有格式的版本。所有寫入 msg 的路徑都要走這兩個函式，事件才不會漏掉 */
static void setMsgF(PGM_P fmt, ...) {
  va_list ap;
  va_start(ap, fmt);
  vsnprintf_P(msg, sizeof(msg), fmt, ap);
  va_end(ap);
  emitEvent();
}

static const char M_ON[]      PROGMEM = "RESISTANCE ON";
static const char M_STOPPED[] PROGMEM = "STOPPED";
static const char M_ZERO[]    PROGMEM = "SAFE ZERO DONE";
static const char M_CLR[]     PROGMEM = "ERROR CLEARED";
static const char M_LOST[]    PROGMEM = "LINK LOST";
static const char M_UP[]      PROGMEM = "LINK UP";
static const char M_BUSY[]    PROGMEM = "BUSY, WAIT";
static const char M_RUNMODE[] PROGMEM = "STOP FIRST";
static const char M_ARMED[]   PROGMEM = "ALREADY RUNNING";
static const char M_SETFAIL[] PROGMEM = "SET FAILED, RETRY";

/*
  下控是否「確認」還在 RUNNING。
  對應 uart_session.js 的 _confirmedRunning()：只看自己記的狀態不夠，
  斷線後那個值已經過期。必須鏈路還活著、且最近一次 STATUS 真的回報 RUNNING。
*/
static bool confirmedRunning() {
  return linkAlive && sr.valid && (sr.flags & 0x02);
}

/* ==================== 送出 ==================== */
static uint8_t txbuf[16];   /* 最長的是 SET_CONTROL：2+1+1+3+2+1 = 10 bytes */

static void sendCmd(uint8_t cmd, const uint8_t *data, uint8_t n) {
  uint8_t i = 0, len = (uint8_t)(1 + n);
  txbuf[i++] = 0x55;
  txbuf[i++] = 0xAA;
  txbuf[i++] = len;          // LEN = CMD + DATA
  txbuf[i++] = cmd;
  for (uint8_t k = 0; k < n; k++) txbuf[i++] = data[k];
  uint16_t crc = crc16ccitt(&txbuf[2], (uint8_t)(1 + len));
  txbuf[i++] = (uint8_t)(crc & 0xFF);
  txbuf[i++] = (uint8_t)(crc >> 8);
  txbuf[i++] = 0x0D;
  ems.write(txbuf, i);
}

/* HEARTBEAT 不需 ACK（協定附錄 A-8），其餘 HMI→MCU 指令都等 ACK */
static void sendAwait(uint8_t cmd, const uint8_t *data, uint8_t n) {
  sendCmd(cmd, data, n);
  pendCmd = cmd;
  pendAt  = millis();
}

static void sendSetControl(uint16_t t) {
  pendVal = t;                    // lastSent 等 ACK OK 才更新（onAck）
  uint8_t d[3] = { mode, (uint8_t)(t & 0xFF), (uint8_t)(t >> 8) };
  sendAwait(CMD_SET_CONTROL, d, 3);
}

/* ==================== 序列 ==================== */
static void seqArm() {
  if (seq != SQ_NONE) { setMsgP(M_BUSY); return; }
  zeroPending = false;            // 使用者明確要 arm，取消尚未完成的保證歸零
  sendSetControl(target);
  seq = SQ_ARM_SET;
}

static void seqStop() {
  if (seq != SQ_NONE) { setMsgP(M_BUSY); return; }
  sendAwait(CMD_STOP, NULL, 0);
  seq = SQ_STOP;
  /* 心跳刻意不停 —— 停了 30 秒後下控會直接斷電 */
}

/* 0.9M：不再在忙碌時直接放棄，改成排進「保證歸零」，由主迴圈送到成功為止 */
static void seqSafeZero(PGM_P why = NULL) {
  if (why || !zeroPending) zeroWhy = why;                 // 歸零進行中再按長 #：保留原本的原因
  zeroPending = true; zeroTries = 0; zeroAt = millis() - ZERO_RETRY_MS;
}

/* 0.10M：保證歸零結束，原因訊息保留在前面（例如 "SEQ DONE +ZERO"） */
static void zeroFinish(PGM_P res) {
  zeroPending = false;
  if (zeroWhy) setMsgF(PSTR("%S %S"), zeroWhy, res);
  else         setMsgP(res);
  zeroWhy = NULL;
}

static void seqResetError() {
  if (seq != SQ_NONE) { setMsgP(M_BUSY); return; }
  sendAwait(CMD_RESET_ERROR, NULL, 0);
  seq = SQ_RESET;
}

static void cmdName(char *out, uint8_t cap, uint8_t cmd) {
  switch (cmd) {
    case CMD_START:       copyP(out, cap, CN_START);  break;
    case CMD_STOP:        copyP(out, cap, CN_STOP);   break;
    case CMD_RESET_ERROR: copyP(out, cap, CN_RESET);  break;
    case CMD_SET_CONTROL: copyP(out, cap, CN_SETCTL); break;
    default:              snprintf_P(out, cap, PSTR("0x%02X"), cmd); break;
  }
}

static void onAck(uint8_t cmd, uint8_t result) {
  if (cmd != pendCmd) {
    /*
      收到的不是正在等的那一個 ACK。最常見的成因是「逾時之後才姍姍來遲」——
      靜靜丟掉會讓畫面只留下 ACK TIMEOUT，看起來像下控完全沒反應，
      但那跟「下控有回、只是比 600ms 慢」是完全不同的問題。
      這一行連同時間戳一起進遙測，事後就能從 log 算出真實延遲。
    */
    char cn[8];
    cmdName(cn, sizeof(cn), cmd);
    setMsgF(PSTR("LATE ACK %s r%u"), cn, (unsigned)result);
    return;
  }
  pendCmd = 0;
  if (cmd == CMD_SET_CONTROL && result == 0) lastSent = pendVal;   // 0.9M：下控確認了才算送到

  /* 0.10M：保證歸零中 SET 0 回 NG 也照樣送 STOP；STOP 回 BAD_STATE 表示下控本來就沒在跑，歸零結束 */
  if (result != 0 && seq == SQ_ZERO_SET) { sendAwait(CMD_STOP, NULL, 0); seq = SQ_ZERO_STOP; return; }
  if (result == 5 && seq == SQ_ZERO_STOP) { seq = SQ_NONE; zeroFinish(PSTR("+STOP")); return; }

  if (result != 0) {
    char cn[8], rn[10];
    cmdName(cn, sizeof(cn), cmd);
    if (result < 6) copyP(rn, sizeof(rn), (PGM_P)pgm_read_ptr(&ACK_NAME[result]));
    else            snprintf_P(rn, sizeof(rn), PSTR("%u"), result);
    setMsgF(PSTR("NG %s %s"), cn, rn);
    seq = SQ_NONE;
    return;
  }

  switch (seq) {
    case SQ_ARM_SET:
      /* 只有在確認下控真的還在 RUNNING 時才略過 START（同 uart_session.js 的 arm()） */
      if (confirmedRunning()) { seq = SQ_NONE; setMsgP(M_ARMED); }
      else { sendAwait(CMD_START, NULL, 0); seq = SQ_ARM_START; }
      break;
    case SQ_ARM_START:  seq = SQ_NONE; setMsgP(M_ON);      break;
    case SQ_SET:        seq = SQ_NONE;                     break;
    /* 歸零計時從下控 ACK 開始算，不從送出算 */
    case SQ_DIP:        seq = SQ_NONE; dipT0 = millis();   break;
    case SQ_STOP:       seq = SQ_NONE; setMsgP(M_STOPPED); break;
    case SQ_ZERO_SET:   sendAwait(CMD_STOP, NULL, 0); seq = SQ_ZERO_STOP; break;
    case SQ_ZERO_STOP:  seq = SQ_NONE; zeroFinish(zeroWhy ? PSTR("+ZERO") : M_ZERO); break;
    /* 清錯誤時把 RPM 統計一起歸零，才知道「清完之後」又飄了多少 */
    case SQ_RESET:      seq = SQ_NONE; faulted = false; rpmStatsReset(); setMsgP(M_CLR); break;
    default:            seq = SQ_NONE;                     break;
  }
}

/* ==================== 接收 ==================== */
#define RX_MAX 24   /* STATUS_REPORT 的 LEN 是 0x0F，需要 1+15=16；24 已有餘裕 */
enum { S_SOF1, S_SOF2, S_LEN, S_PAYLOAD, S_CRC_L, S_CRC_H, S_EOF };

static struct {
  uint8_t  state, len, idx, buf[RX_MAX];
  uint16_t crcRx;
} rx;

static uint16_t crcErrCnt = 0;

/* ---- 0.16M 接收診斷 ----
   找「固定幾秒一次 LINK LOST」到底是哪一段沒收到：
     b    = 這段時間從 UART 讀到的 byte 數（下控 10 Hz × 21 B ≈ 210 B/s）
     fr   = 解出來的完整封包數；crc / len / eof = 三種被丟掉的封包
     pg   = 兩次 pumpEms() 之間最長隔多久（ms）；> 30 ms 硬體緩衝就可能滿
     lp   = 主迴圈單圈最長多久（ms）；full = 讀的時候緩衝已滿幾次（= 已經掉 byte）
   判讀：LOST 時 b ≈ 0 → 線上真的沒東西進來（接線／電位）；b 有但 fr 沒有 → 收到亂碼；
         pg / lp 大或 full > 0 → 我們的程式卡住沒去收（韌體問題）。 */
#if defined(__AVR_ATmega2560__)
#define EMS_RXBUF 64
#else
#define EMS_RXBUF 80
#endif
#define DIAG_MS 10000UL
static struct {
  uint16_t bytes, frames, crc, len, eof, full, pumpGap, loopMax;
} dg;
static uint16_t dgLastFr = 0, dgBadTot = 0;   // 0.19M：上一個 10 秒窗的封包數、開機以來丟掉的封包數（給待機畫面）
static bool     dgHave = false;
static uint16_t dgSinceFrame = 0;     // 上一個好封包之後又讀到幾個 byte
static uint32_t dgLastPump = 0;

static void onFrame(uint8_t cmd, const uint8_t *d, uint8_t n) {
  lastRxAt = millis();
  dg.frames++; dgSinceFrame = 0;
  if (!linkAlive) { linkAlive = true; sysStep = 0; sysRetry = 0; sysQuiet = false; setMsgP(M_UP); }

  if (cmd == CMD_STATUS_REPORT && n >= 13) {
    sr.rpm     = rd16(d + 0);
    sr.mA      = rd16(d + 2);
    sr.watt    = rd16(d + 4);
    sr.dutyX10 = rd16(d + 6);
    sr.tgt     = rd16(d + 8);
    sr.mode    = d[10];
    sr.flags   = d[11];
    /* 與 uart_session.js 一致：v0.2 的 error 是 uint16（DATA 14 bytes），
       保留 13 bytes 舊韌體的退路，免得整個 STATUS 顯示失效 */
    sr.err     = (n >= 14) ? rd16(d + 12) : d[12];
    sr.valid   = true;
    /* 直接從下控每次回報的旗標推導，不要自己記成黏著狀態 ——
       否則下控那邊錯誤排除了，畫面還會一直停在 FAULT。 */
    faulted    = (sr.err != 0);
    if (!faulted) resetTried = false;
    /* POWER_FAIL 剛亮起來時重問一次 SYSTEM_INFO —— VIN 不在 STATUS 裡，
       不重問拿到的就是開機當時的舊值，對判斷電源掉沒掉沒有用。 */
    if ((sr.err & 0x04) && !(lastErr & 0x04) && sysStep >= 4) { sysStep = 2; sysRetry = 0; }
    lastErr = sr.err;

    if (sr.rpm < rpmMin) rpmMin = sr.rpm;
    if (sr.rpm > rpmMax) rpmMax = sr.rpm;
    rpmSamples++;

    /* 存進波形緩衝。以 rpmMax 自動縮放，新的最大值出現時舊資料的比例會偏高，
       但那正好把「之前看起來很大的東西其實不算大」表現出來，不需要重算整段。 */
    traceBuf[traceIdx] = rpmMax ? (uint8_t)((uint32_t)sr.rpm * 15 / rpmMax) : 0;
    if (++traceIdx >= TRACE_W) { traceIdx = 0; traceFull = true; }
#if RPM_TRACE
    /* 每一筆 STATUS 都吐一行原始 RPM（10Hz），拿去存檔分析飄動的形狀 */
    Serial.print(F("R,")); Serial.print(millis());
    Serial.print(','); Serial.println(sr.rpm);
#endif
    return;
  }

  if (cmd == CMD_ACK && n >= 1) {
    onAck(d[0], (n > 1) ? d[1] : 0);
    return;
  }

  /* GET_VERSION 的回應沿用 0x20（附錄 A-9），不是另外一個 response 指令碼 */
  if (cmd == CMD_GET_VERSION && n >= 3) {
    fw[0] = d[0]; fw[1] = d[1]; fw[2] = d[2];
    if (sysStep == 1) { sysStep = 2; sysRetry = 0; }
    return;
  }

  /* GET_SYSTEM_INFO 的回應是 0x81（附錄 A-10）：VIN(0.01V) + 韌體版本 */
  if (cmd == CMD_SYSTEM_INFO && n >= 5) {
    vinMv = rd16(d + 0);
    fw[0] = d[2]; fw[1] = d[3]; fw[2] = d[4];
    sysValid = true;
    if (sysStep == 3) { sysStep = 4; sysRetry = 0; }
    /* 0.19M：定時輪詢的結果照樣吐 E 行（記錄頁要 VIN），但把畫面那一行訊息還原，
       否則 SEQ DONE 之類的訊息 5 秒內就被 VIN 蓋掉 */
    char keep[sizeof(msg)];
    bool quiet = sysQuiet; sysQuiet = false;
    if (quiet) memcpy(keep, msg, sizeof(msg));
    setMsgF(PSTR("VIN %u.%02uV FW%u.%u.%u"),
            (unsigned)(vinMv / 1000), (unsigned)((vinMv % 1000) / 10),
            (unsigned)fw[0], (unsigned)fw[1], (unsigned)fw[2]);
    if (quiet) memcpy(msg, keep, sizeof(msg));
    return;
  }

  if (cmd == CMD_ERROR_REPORT && n >= 1) {
    faulted = true;
    setMsgF(PSTR("ERR REPORT 0x%02X"), (unsigned)d[0]);
    return;
  }
}

static void feed(uint8_t b) {
  switch (rx.state) {
    case S_SOF1: if (b == 0x55) rx.state = S_SOF2; break;
    case S_SOF2:
      if (b == 0xAA)      rx.state = S_LEN;
      else if (b == 0x55) ;                       // 連續 0x55，繼續等 0xAA
      else                rx.state = S_SOF1;
      break;
    case S_LEN:
      if (b == 0 || b > RX_MAX - 1) { rx.state = S_SOF1; dg.len++; break; }
      rx.len = b; rx.buf[0] = b; rx.idx = 1; rx.state = S_PAYLOAD;
      break;
    case S_PAYLOAD:
      rx.buf[rx.idx++] = b;
      if (rx.idx >= (uint8_t)(1 + rx.len)) rx.state = S_CRC_L;
      break;
    case S_CRC_L: rx.crcRx = b; rx.state = S_CRC_H; break;
    case S_CRC_H: rx.crcRx |= (uint16_t)b << 8; rx.state = S_EOF; break;
    case S_EOF:
      if (b == 0x0D) {
        if (crc16ccitt(rx.buf, (uint8_t)(1 + rx.len)) == rx.crcRx)
          onFrame(rx.buf[1], &rx.buf[2], (uint8_t)(rx.len - 1));
        else { crcErrCnt++; dg.crc++; }
      } else dg.eof++;
      rx.state = S_SOF1;
      break;
  }
}

/* 必須被頻繁呼叫，包含 OLED 分頁重繪的迴圈裡面。
   下控每 100ms 丟 21 bytes，AltSoftSerial 的 RX 緩衝 80 bytes，
   只要別停下來超過 ~40ms 就不會掉。 */
static void pumpEms() {
  uint32_t t = millis();
  if (dgLastPump) { uint16_t g = (uint16_t)min(t - dgLastPump, 60000UL); if (g > dg.pumpGap) dg.pumpGap = g; }
  dgLastPump = t;
  if (ems.available() >= EMS_RXBUF - 1) dg.full++;
  while (ems.available()) {
    dg.bytes++; if (dgSinceFrame < 0xFFFF) dgSinceFrame++;   // 先加再 feed：收完整包時 onFrame 會歸零
    feed((uint8_t)ems.read());
  }
}

/* 直接寫成 E 行，不經過 msg（不佔 OLED 那一行）。記錄頁照一般事件存進 CSV */
static void diagEmit(PGM_P tag, uint32_t now) {
#if TELEMETRY_MS
  Serial.print(F("E,")); Serial.print(now); Serial.print(',');
  Serial.print((const __FlashStringHelper *)tag);
  if (lastRxAt) { Serial.print(F(" gap=")); Serial.print((int32_t)(now - lastRxAt)); }
  Serial.print(F(" since=")); Serial.print(dgSinceFrame);
  Serial.print(F(" b="));    Serial.print(dg.bytes);
  Serial.print(F(" fr="));   Serial.print(dg.frames);
  Serial.print(F(" crc="));  Serial.print(dg.crc);
  Serial.print(F(" len="));  Serial.print(dg.len);
  Serial.print(F(" eof="));  Serial.print(dg.eof);
  Serial.print(F(" pg="));   Serial.print(dg.pumpGap);
  Serial.print(F(" lp="));   Serial.print(dg.loopMax);
  Serial.print(F(" full=")); Serial.println(dg.full);
#endif
}

/* ==================== 按鍵 ==================== */
static struct {
  bool     down, longFired;
  uint32_t tEdge, tRepeat;
  uint8_t  repCount;
} bs[4];

static bool evEdge[4], evRepeat[4], evClick[4], evLong[4];

static void scanButtons() {
  uint32_t now = millis();
  for (uint8_t i = 0; i < 4; i++) {
    evEdge[i] = evRepeat[i] = evClick[i] = evLong[i] = false;
    bool down = (digitalRead(PIN_BTN[i]) == LOW);

    if (down != bs[i].down) {
      if (now - bs[i].tEdge < DEBOUNCE_MS) continue;
      bs[i].tEdge = now;
      bs[i].down  = down;
      if (down) {
        bs[i].longFired = false;
        bs[i].repCount  = 0;
        bs[i].tRepeat   = now + REPEAT_DELAY_MS;
        evEdge[i]       = true;
      } else if (!bs[i].longFired) {
        evClick[i] = true;                 // 短按放開
      }
      continue;
    }

    if (down) {
      if (!bs[i].longFired && (now - bs[i].tEdge) >= LONG_MS) {
        bs[i].longFired = true;
        evLong[i] = true;
      }
      /* 用有號差值比較，millis() 49 天後翻轉時才不會卡住不連發 */
      if ((int32_t)(now - bs[i].tRepeat) >= 0) {
        bs[i].tRepeat = now + REPEAT_RATE_MS;
        if (bs[i].repCount < 255) bs[i].repCount++;
        evRepeat[i]   = true;
      }
    }
  }
}

/* ==================== 目標值 ==================== */
/* mult 用來加速：按住超過一段時間後一次跳好幾格，
   否則 ERG 模式從 0 調到 3000 W 要按上一分鐘。 */
static void bumpTarget(int8_t dir, uint8_t mult) {
  uint16_t step = (uint16_t)(TGT_STEP[mode] * mult), max = TGT_MAX[mode];
  if (dir > 0) target = (uint16_t)((target + step > max) ? max : target + step);
  else         target = (uint16_t)((target < step) ? 0 : target - step);
  tgtDirty   = true;
  tgtDirtyAt = millis();
  tgtRetry   = 0;
}

/* KP / ERG 按住超過 15 次後一次跳 8 格。DUTY 不走這裡，改走 dutyPreset()。 */
static inline uint8_t accel(uint8_t i) {
  return (bs[i].repCount <= 15) ? 1 : 8;
}

/* DUTY 按住：每 DUTY_PRESET_EVERY 次連發跳到下一個檔位。
   「下一個」是嚴格大於（或小於）目前值的那一檔，所以從 29.9 往上會停 30.0，
   從 30.1 往下也停 30.0。 */
static void dutyPreset(uint8_t i, int8_t dir) {
  if ((bs[i].repCount - 1) % DUTY_PRESET_EVERY) return;
  uint16_t next = target;
  if (dir > 0) {
    for (uint8_t k = 0; k < DUTY_PRESET_N; k++) {
      uint16_t p = pgm_read_word(&DUTY_PRESET[k]);
      if (p > target) { next = p; break; }
    }
  } else {
    for (int8_t k = DUTY_PRESET_N - 1; k >= 0; k--) {
      uint16_t p = pgm_read_word(&DUTY_PRESET[k]);
      if (p < target) { next = p; break; }
    }
  }
  if (next == target) return;
  target     = next;
  tgtDirty   = true;
  tgtDirtyAt = millis();
  tgtRetry   = 0;
}

static void cycleMode() {
  if (confirmedRunning()) { setMsgP(M_RUNMODE); return; }   // 跑的時候不給換模式
  /* KP → ERG → DUTY → SEQ → KP。SEQ 只是畫面模式，協定上沿用 MODE_DUTY */
  if (mode == MODE_DUTY && !uiSeq) uiSeq = true;
  else {
    uiSeq = false;
    mode = (uint8_t)((mode + 1) % 3);
  }
  if (target > TGT_MAX[mode]) target = TGT_MAX[mode];
  msg[0] = 0;
}

/* ---- 序列：切到第 i 步 ---- */
static void seqApply(uint8_t i, uint32_t now) {
  SeqStep s; seqStepRead(i, &s);
  seqIdx = i; seqStepT0 = now;
  target = s.duty; tgtRetry = 0;
  if (s.dipMs && s.duty < lastSent) {                    // 先歸零，時間到由歸零邏輯送出 target
    dipLenMs = s.dipMs; dipPhase = 1; dipRetry = 0; tgtDirty = false;
  } else {
    tgtDirty = true; tgtDirtyAt = now - TGT_PUSH_MS;
  }
  setMsgF(PSTR("SQ%u %u/%u %u.%u%%"), (unsigned)(seqSel + 1), (unsigned)(i + 1),
          (unsigned)seqLen(), (unsigned)(s.duty / 10), (unsigned)(s.duty % 10));
}

static uint32_t seqLinkDownAt = 0;   // 0.10M：序列中鏈路斷掉的時刻，0 = 沒斷
static void seqAbort(PGM_P why) {
  if (!seqActive) return;
  seqActive = false;
  if (planActive) { uiSel = 0; seqSel = 0; }              // 0.11M：計畫結束後選單回 SEQ1，誤按 * 不會重跑計畫
  planActive = false; planHold = false;                    // 0.11M：任何中止 / 結束都結束計畫
  seqLinkDownAt = 0;                                       // 0.10M：斷線暫停的時刻不要帶到下一個序列
  tgtDirty = false; dipPhase = 0;                          // 0.9M：序列殘留的推送 / 歸零不要再送出
  setMsgP(why);
}

static const char M_SQDONE[]  PROGMEM = "SEQ DONE";
static const char M_SQABORT[] PROGMEM = "SEQ ABORTED";
static const char M_SQNORUN[] PROGMEM = "SEQ STOP: NOT RUN";
static const char M_SQLINK[]  PROGMEM = "SEQ ABORT: LINK";
static const char M_PLDONE[]  PROGMEM = "PLAN DONE";
static const char M_BOOT[]    PROGMEM = "BOOT FW " FW_VERSION;   // 0.11M：開機事件（E 行）
static const char M_BOOTZ[]   PROGMEM = "BOOT ZERO";
static const char M_PLLATE[]  PROGMEM = "PLAN ABORT: LATE";

/* 0.11M：第 g 組開始（下控已在 RUNNING；休息組 = REST5 同一個序列，阻力 0） */
static void planGroupStart(uint8_t g, uint32_t now) {
  planGrp = g; planHold = false;
  seqSel = planSeqIdx(g);
  planSetGroupTimes(g);
  seqApply(0, now);
  char nm[6]; copyP(nm, sizeof(nm), (PGM_P)pgm_read_ptr(&PLANS[planId - 1].name));
  setMsgF(PSTR("P%s G%u/%u %s"), nm, (unsigned)(g + 1), (unsigned)planGroups(),
          planIsRest(g) ? "REST" : "TEST");
}

static void seqStart() {
  seqActive = true; seqStarted = false; seqNotRun = 0;
  /* 0.10M：保證歸零進行中不准開新序列（由呼叫端擋，見 loop） */
  dipAuto = false; dipPhase = 0;                         // 手動的自動歸零會干擾序列，關掉
  SeqStep s; seqStepRead(0, &s);
  target = s.duty;
  if (confirmedRunning()) { seqStarted = true; if (planActive) planGroupStart(0, millis()); else seqApply(0, millis()); }
  else seqArm();                                          // 送 SET_CONTROL(第一步) → START
}

/* 0.11M：開始計畫 p（1 起算）。按下 * 的這一刻 = T0，操作員同時在功率機按第一下 F1 */
static void planStart(uint8_t p) {
  planId = p; planT0 = millis();
  planGrp = 0; planHold = false;
  seqSel = planSeqIdx(0);
  planSetGroupTimes(0);
  planActive = true;
  seqStart();                                              // 已在 RUNNING 就直接進第 1 組，否則 arm 後由 seqTick 進
}

static void seqTick(uint32_t now) {
  if (!seqActive) return;
  if (!linkAlive) {
    /* LINK LOST 一下就回來：不中止也不前進。（0.17M 前每幾秒一次的 LINK LOST 是誤判，已修；這裡留給真的短暫斷線）
       0.9M：連續斷超過 SEQ_LINK_ABORT_MS 就中止並排保證歸零，不再停在當下 duty。 */
    if (!seqLinkDownAt) seqLinkDownAt = now;              // 0.10M：從判定斷線那一刻起暫停這一步的計時
    if ((int32_t)(now - lastRxAt) > (int32_t)SEQ_LINK_ABORT_MS) {
      seqLinkDownAt = 0;
      seqAbort(M_SQLINK); target = 0; seqSafeZero(M_SQLINK);
    }
    return;
  }
  if (seqLinkDownAt) { seqStepT0 += now - seqLinkDownAt; seqLinkDownAt = 0; }   // 鏈路回來：補回暫停的時間
  if (!confirmedRunning()) {
    if (!seqNotRun) seqNotRun = now;
    if (now - seqNotRun > 3000 && seq == SQ_NONE) seqAbort(M_SQNORUN);
    return;
  }
  seqNotRun = 0;
  if (!seqStarted) { seqStarted = true; if (planActive) planGroupStart(0, now); else seqApply(0, now); return; }

  /* 推送途中剛好碰到 LINK LOST 時，推送邏輯會把 tgtDirty 清掉、值就沒送出去。
     序列跑的時候自己盯著：最後送出的值不是 target 就再推一次。 */
  /* 0.9M：lastSent 只在 ACK OK 才更新，下控回 NG 時這裡會一直成立 —— 補送間隔至少 1 秒，免得洗爆 UART */
  static uint32_t seqResendAt = 0;
  if (!dipPhase && !tgtDirty && lastSent != target && seq == SQ_NONE && !pendCmd && !zeroPending &&
      (now - seqResendAt) >= 1000) {
    seqResendAt = now;
    tgtDirty = true; tgtDirtyAt = now - TGT_PUSH_MS;
  }

  /* 0.11M：計畫中這組內容已跑完 → 阻力 0 等到下一組的絕對時刻 */
  bool lastGrp = planActive && (planGrp + 1 >= planGroups());
  if (planActive && planHold) {
    if (!lastGrp && (int32_t)(now - planNextAt) >= 0) planGroupStart((uint8_t)(planGrp + 1), now);
    return;
  }

  SeqStep s; seqStepRead(seqIdx, &s);
  /* 有號比較：seqStepT0 可能是在這一圈 now 之後才取的 millis()（例如 seqStart 裡），
     無號相減會變成超大值、立刻跳下一步 —— 10/12 D 輪 SQ3 第 1 步只停了 21 ms 就是這個 */
  if ((int32_t)(now - seqStepT0) >= (int32_t)((uint32_t)s.holdS * 1000UL)) {
    if (seqIdx + 1 >= seqLen()) {
      if (planActive && !lastGrp) {                         // 0.11M：計畫中、不是最後一組 → HOLD 阻力 0
        planHold = true;
        target = 0; tgtDirty = true; tgtDirtyAt = now - TGT_PUSH_MS; tgtRetry = 0;
        return;
      }
      /* 0.9M：SEQ DONE 後自動 SET_CONTROL(0) → STOP（保證歸零，送到 ACK 為止）；0.11M 計畫最後一組同一條路 */
      PGM_P why = planActive ? M_PLDONE : M_SQDONE;
      seqAbort(why); target = 0; seqSafeZero(why); return;
    }
    seqApply((uint8_t)(seqIdx + 1), now);
  }
  /* 0.11M：內容（含斷線暫停延長）拖到功率機這組停錄前 2 s 還沒跑完 → 中止並歸零（最後一組也檢查） */
  if (planLate(now)) {
    seqAbort(M_PLLATE); target = 0; seqSafeZero(M_PLLATE);
  }
}

/* ==================== 畫面 ==================== */
static void line(uint8_t row, const char *s) { oled.drawStr(0, (int8_t)(10 + row * 11), s); }

/*
  RPM 波形：最新的一筆畫在最右邊，縱軸相對於目前的 rpmMax。
  形狀本身就是診斷 —— 稀疏的高柱是偶發尖峰（雜訊耦合），
  整片densely 填滿代表訊號從頭到尾都不可信（輸入浮空）。
*/
static void drawTrace(uint8_t y0, uint8_t h) {
  const uint8_t x0 = 4;
  uint8_t n = traceFull ? TRACE_W : traceIdx;
  for (uint8_t k = 0; k < n; k++) {
    uint8_t i = (uint8_t)((traceIdx + TRACE_W - 1 - k) % TRACE_W);
    uint8_t v = (uint8_t)((uint16_t)traceBuf[i] * h / 15);
    if (v) oled.drawVLine((uint8_t)(x0 + TRACE_W - 1 - k), (uint8_t)(y0 + h - v), v);
  }
  oled.drawHLine(x0, (uint8_t)(y0 + h), TRACE_W);   // 基線
}

static void fmtTarget(char *out, uint8_t cap, uint16_t v) {
  if (mode == MODE_ERG) snprintf_P(out, cap, PSTR("%uW"), (unsigned)v);
  else if (mode == MODE_DUTY) snprintf_P(out, cap, PSTR("%u.%u%%"), (unsigned)(v / 10), (unsigned)(v % 10));
  else snprintf_P(out, cap, PSTR("%u.%u"), (unsigned)(v / 10), (unsigned)(v % 10));
}

static void stateBadge(char *out, uint8_t cap) {
  if (!linkAlive)          copyP(out, cap, PSTR("NOLINK"));
  else if (faulted)        copyP(out, cap, PSTR("FAULT"));
  else if (confirmedRunning()) copyP(out, cap, (mode == MODE_DUTY && dipAuto) ? PSTR("RUN+D") : PSTR("RUN"));
  else if (sr.valid && (sr.flags & 0x01)) copyP(out, cap, PSTR("READY"));
  else                     copyP(out, cap, PSTR("IDLE"));
}

/*
  先把五行文字全部排好（renderBegin）再一頁一頁畫（renderStep）。
  兩個理由：分頁模式下同一畫面會重畫 8 次，在迴圈裡 snprintf 等於算 8 遍；
  而且迴圈中間會呼叫 pumpEms()，全域狀態可能在兩個分頁之間被更新，
  直接讀全域會畫出上下半截不一致的畫面。
*/
/* 0.19M：重繪拆成「每圈主迴圈一頁」。排好的文字放在這裡，8 頁畫完之前不會變。 */
static struct {
  char    L[5][21];
  char    sb[8];
  int8_t  bx, msgY;
  bool    trace, active;
  uint8_t page;
} rd;

static void renderBegin() {
  char t[10], mn[6];

  copyP(mn, sizeof(mn), (PGM_P)pgm_read_ptr(&MODE_NAME[mode]));
  fmtTarget(t, sizeof(t), target);
  stateBadge(rd.sb, sizeof(rd.sb));

  /* 本機設定值與下控實際採用的目標值不同時標 * —— 看得出設定有沒有真的送進去 */
  bool unsent = sr.valid && (sr.tgt != target);
  if (uiSeq && !seqActive && uiSel >= SEQ_N) {           // 0.11M：選單上的計畫
    char nm[8]; uint8_t pi = (uint8_t)(uiSel - SEQ_N);
    copyP(nm, sizeof(nm), (PGM_P)pgm_read_ptr(&PLANS[pi].name));
    snprintf_P(rd.L[0], sizeof(rd.L[0]), PSTR("PLAN %-4s %uG"), nm,
               (unsigned)(2 * pgm_read_byte(&PLANS[pi].n) - 1));
  } else if (uiSeq && !seqActive) {
    char nm[8];
    copyP(nm, sizeof(nm), (PGM_P)pgm_read_ptr(&SEQS[seqSel].name));
    snprintf_P(rd.L[0], sizeof(rd.L[0]), PSTR("SEQ%u %-6s"), (unsigned)(seqSel + 1), nm);
  } else if (uiSeq && planActive) {
    snprintf_P(rd.L[0], sizeof(rd.L[0]), PSTR("G%u/%u %-6s%c"), (unsigned)(planGrp + 1), (unsigned)planGroups(),
               t, unsent ? '*' : ' ');                    // 不顯示 S%u，免得壓到右上徽章
  } else if (uiSeq) {
    snprintf_P(rd.L[0], sizeof(rd.L[0]), PSTR("S%u %-7s%c"), (unsigned)(seqSel + 1), t, unsent ? '*' : ' ');
  } else
  snprintf_P(rd.L[0], sizeof(rd.L[0]), PSTR("%-4s %-7s%c"), mn, t, unsent ? '*' : ' ');

  if (sr.valid) {
    snprintf_P(rd.L[1], sizeof(rd.L[1]), PSTR("RPM %4u PWR %4uW"), (unsigned)sr.rpm, (unsigned)sr.watt);
    /* RPM_FAIL 時 DTY / mA 必定是 0，那一行沒有資訊量。
       換成 RPM 的最小-最大與樣本數，把「會飄」變成可以拿去對帳的數字。 */
    if (sr.err & 0x02)
      snprintf_P(rd.L[2], sizeof(rd.L[2]), PSTR("RPM %u-%u n%lu"),
                 (unsigned)(rpmSamples ? rpmMin : 0), (unsigned)rpmMax,
                 (unsigned long)rpmSamples);
    else
      snprintf_P(rd.L[2], sizeof(rd.L[2]), PSTR("DTY %u.%u%% %umA"),
                 (unsigned)(sr.dutyX10 / 10), (unsigned)(sr.dutyX10 % 10), (unsigned)sr.mA);
    /* RPM_FAIL 時第 4 行讓位給波形圖，這裡放空字串讓文字迴圈跳過 */
    if (sr.err & 0x02)
      rd.L[3][0] = 0;
    /* POWER_FAIL 時把 VIN 換上來 —— 線圈電源電壓是判斷這個錯誤的第一手資料 */
    else if ((sr.err & 0x04) && sysValid)
      snprintf_P(rd.L[3], sizeof(rd.L[3]), PSTR("VIN %u.%02uV E%04X"),
                 (unsigned)(vinMv / 1000), (unsigned)((vinMv % 1000) / 10), (unsigned)sr.err);
    /* 序列執行中：第 4 行改顯示進度與這一步剩幾秒 */
    else if (planActive && planHold) {                  // 0.11M：等下一組
      int32_t left = (int32_t)(planNextAt - millis()) / 1000;
      snprintf_P(rd.L[3], sizeof(rd.L[3]), PSTR("HOLD NEXT G %lds"), (long)(left < 0 ? 0 : left));
    }
    else if (seqActive && seqStarted) {
      SeqStep s; seqStepRead(seqIdx, &s);
      uint32_t el = (millis() - seqStepT0) / 1000UL;
      uint16_t left = (el >= s.holdS) ? 0 : (uint16_t)(s.holdS - el);
      snprintf_P(rd.L[3], sizeof(rd.L[3]), PSTR("STEP %u/%u  %us"),
                 (unsigned)(seqIdx + 1), (unsigned)seqLen(), (unsigned)left);
    }
    /* 0.19M：待機且沒有錯誤時，第 4 行改顯示收包統計（上一個 10 秒收到幾包 / 開機以來丟掉幾包），
       不接電腦也看得出通訊正不正常。正常是 RX 98～104、BAD 0。 */
    else if (dgHave && !sr.err && !confirmedRunning())
      snprintf_P(rd.L[3], sizeof(rd.L[3]), PSTR("RX %u/10s BAD %u"), (unsigned)dgLastFr, (unsigned)dgBadTot);
    else
      snprintf_P(rd.L[3], sizeof(rd.L[3]), PSTR("TGT %-5u ERR %04X"),
                 (unsigned)sr.tgt, (unsigned)sr.err);
  } else {
    /* 還沒收到下控封包時（上機第一階段），把剩餘 RAM 秀出來當健康檢查 */
    strcpy_P(rd.L[1], PSTR("waiting for STATUS"));
    snprintf_P(rd.L[2], sizeof(rd.L[2]), PSTR("FW " FW_VERSION "  CRC ERR %u"), (unsigned)crcErrCnt);
    snprintf_P(rd.L[3], sizeof(rd.L[3]), PSTR("FREE RAM %u"), (unsigned)ramHeadroom());
  }

  strncpy(rd.L[4], msg, sizeof(rd.L[4]) - 1);
  rd.L[4][sizeof(rd.L[4]) - 1] = 0;

  rd.bx = (int8_t)(128 - 6 * (int8_t)strlen(rd.sb));
  /* 有波形時訊息行往下讓，沒有就維持原位 */
  rd.trace = sr.valid && (sr.err & 0x02);
  rd.msgY = rd.trace ? 63 : 54;

  rd.page = 0;
  rd.active = true;
  oled.firstPage();
}

/* 這一頁（8 列像素）有沒有碰到第 top～bot 列 */
static bool rowHit(uint8_t top, uint8_t bot) {
  uint8_t p0 = (uint8_t)(rd.page * 8);
  return bot >= p0 && top <= (uint8_t)(p0 + 7);
}
/* 6x12 字型：基線 y 的字佔 y−10 ～ y+1 列（字高 12、y 偏移 −2），這裡多留到 y+3 */
static bool textHit(int8_t y) { return rowHit((uint8_t)(y - 10), (uint8_t)(y + 3)); }

/* 畫一頁、送一頁。每圈主迴圈呼叫一次；一個畫面 8 頁，約 8 圈畫完。 */
static void renderStep() {
  if (!rd.active) return;
  oled.setFont(u8g2_font_6x12_tr);
  for (uint8_t r = 0; r < 4; r++) {
    int8_t y = (int8_t)(10 + r * 11);
    if (rd.L[r][0] && textHit(y)) { line(r, rd.L[r]); pumpEms(); }
  }
  if (textHit(10)) oled.drawStr(rd.bx, 10, rd.sb);
  if (rd.trace && rowHit(36, 52)) drawTrace(36, 16);
  if (rd.L[4][0] && textHit(rd.msgY)) { oled.drawStr(0, rd.msgY, ">"); oled.drawStr(8, rd.msgY, rd.L[4]); }
  pumpEms();                         // 送這一頁（I2C）之前先把串口收乾淨
  if (oled.nextPage()) rd.page++;
  else                 rd.active = false;
  pumpEms();
}

/* 一次畫完整個畫面（只有 setup() 用） */
static void render() {
  renderBegin();
  while (rd.active) renderStep();
}

/* ==================== ASCII 遙測 ==================== */
#if TELEMETRY_MS
static void telemetry() {
  /* Serial 這條線只有 ASCII，跟 EMS 的二進位協定完全分開 */
  Serial.print(F("S,"));
  Serial.print(millis());        Serial.print(',');
  Serial.print(sr.rpm);          Serial.print(',');
  Serial.print(sr.watt);         Serial.print(',');
  Serial.print(sr.mA);           Serial.print(',');
  Serial.print(sr.dutyX10);      Serial.print(',');
  Serial.print(sr.tgt);          Serial.print(',');
  Serial.print(target);          Serial.print(',');
  Serial.print(mode);            Serial.print(',');
  Serial.print(sr.flags);        Serial.print(',');
  Serial.print(sr.err);          Serial.print(',');
  Serial.print(linkAlive ? 1 : 0);  Serial.print(',');
  Serial.print(vinMv);
  /* 0.11M 追加（舊的 13 欄不動）：plan,grp,seg,rest,hold,seq,step,sel
     plan = 1 60A1 / 2 60A2 / 3 60B / 4 CMP1 / 5 CMP2 / 6 C90A / 7 C90B / 8 C120 / 0 沒有計畫（0.14M）；grp = 第幾組（1 起算）；seg = 第幾段量測（休息組 0）；
     rest = 休息組；hold = 內容跑完、阻力 0 等下一組；seq / step = 正在跑的 SEQ 與步（沒跑 = 0） */
  bool pa = planActive;
  Serial.print(','); Serial.print(pa ? planId : 0);
  Serial.print(','); Serial.print(pa ? planGrp + 1 : 0);
  Serial.print(','); Serial.print((pa && !planIsRest(planGrp)) ? planGrp / 2 + 1 : 0);
  Serial.print(','); Serial.print((pa && planIsRest(planGrp)) ? 1 : 0);
  Serial.print(','); Serial.print((pa && planHold) ? 1 : 0);
  Serial.print(','); Serial.print((seqActive && seqStarted) ? seqSel + 1 : 0);
  Serial.print(','); Serial.print((seqActive && seqStarted && !planHold) ? seqIdx + 1 : 0);
  /* sel = SEQ 畫面選單目前選中的計畫（1 起算，0 = 選的是單一 SEQ）：dyno_f1timer 開始前核對 --plan */
  Serial.print(','); Serial.print(uiSel >= SEQ_N ? uiSel - SEQ_N + 1 : 0);
  Serial.println();
}
#endif

/* ==================== setup / loop ==================== */
void setup() {
  paintFreeRam();                  // 要最早做，趁堆疊還很淺

  for (uint8_t i = 0; i < 4; i++) pinMode(PIN_BTN[i], INPUT_PULLUP);

  Serial.begin(TELEM_BAUD);
  ems.begin(EMS_BAUD);

  oled.begin();
  oled.setI2CAddress(OLED_ADDR << 1);
  oled.setBusClock(400000);        // 預設 100kHz 會讓每次重繪多阻塞 ~20ms

  rx.state = S_SOF1;

  /* 心跳綁「開機～關機」，不是綁 START～STOP。
     按 STOP 只是關阻力，此時若停掉心跳，30 秒後整台會斷電。 */
  sendCmd(CMD_HEARTBEAT, NULL, 0);
  lastHbAt = millis();

  /* 0.11M：開機一定先走保證歸零（SET 0 → STOP，鏈路一通就送、送到 ACK 或確認已停）。
     USB 重新連線（DTR）會讓 Mega 重開；下控沒逾時的話會停在重開前的 duty，這裡把它收掉。 */
  setMsgP(M_BOOT);
  seqSafeZero(M_BOOTZ);

  render();
}

static const char M_DG10[]  PROGMEM = "DIAG10";
static const char M_DGLOST[] PROGMEM = "DIAG LOST";

void loop() {
  /* 0.17M：先收封包、掃按鍵，再取 now。原本 now 先取，pumpEms() 裡 onFrame 記的
     lastRxAt = millis() 可能比 now 晚 1～5 ms，下面的無號相減 now - lastRxAt 就溢位成
     42 億 → 誤判 LINK LOST（下一包 0.1 s 後進來又 LINK UP）。11/11 UNO 實測 161 次 LINK LOST
     全部是這個原因，下控並沒有停送。 */
  pumpEms();
  scanButtons();
  uint32_t now = millis();

  /* 0.16M 接收診斷：單圈耗時 + 每 10 秒一行統計 */
  static uint32_t prevLoop = 0, lastDiag = 0;
  if (prevLoop) { uint16_t l = (uint16_t)min(now - prevLoop, 60000UL); if (l > dg.loopMax) dg.loopMax = l; }
  prevLoop = now;
  if (now - lastDiag >= DIAG_MS) {
    diagEmit(M_DG10, now);
    lastDiag = now;
    dgLastFr = dg.frames; dgHave = true;
    { uint16_t bad = (uint16_t)(dg.crc + dg.len + dg.eof); dgBadTot = (dgBadTot > 0xFFFF - bad) ? 0xFFFF : (uint16_t)(dgBadTot + bad); }
    memset(&dg, 0, sizeof(dg));
  }

  /* ---- 心跳 ---- */
  if (now - lastHbAt >= HEARTBEAT_MS) {
    lastHbAt = now;
    sendCmd(CMD_HEARTBEAT, NULL, 0);
  }

  /* ---- ACK 逾時 ---- */
  if (pendCmd && (int32_t)(now - pendAt) > (int32_t)ACK_TIMEOUT_MS) {   // 有號：pendAt 可能比這一圈的 now 晚
    char cn[8];
    cmdName(cn, sizeof(cn), pendCmd);
    setMsgF(PSTR("ACK TIMEOUT %s"), cn);
    /* 單純的目標值推送掉了就自己補送。原本這裡直接放掉，畫面上的設定值與下控
       實際採用的值會就此分家（只剩標題列的 * 提示），掃點時等於整筆作廢。
       arm/stop 那幾個序列不在此列 —— 它們有使用者按鍵當重試。 */
    if (pendCmd == CMD_SET_CONTROL && seq == SQ_SET) {
      if (tgtRetry < TGT_SET_RETRY) { tgtRetry++; tgtDirty = true; tgtDirtyAt = now; }
      else                            setMsgP(M_SETFAIL);   // 序列中由 seqTick 的 lastSent != target 檢查繼續補送
    }
    /* 0.9M：保證歸零的 STOP 掉了：zeroPending 仍在，主迴圈過 ZERO_RETRY_MS 重來。
       0.10M：SET 0 逾時就直接接著送 STOP（阻力至少先關掉），不等下一輪 */
    if (pendCmd == CMD_SET_CONTROL && seq == SQ_ZERO_SET) {
      sendAwait(CMD_STOP, NULL, 0); seq = SQ_ZERO_STOP;
      goto ackTimeoutDone;
    }
    /* 歸零那一包掉了：補送；補不上就放棄歸零，直接送回原值 */
    if (pendCmd == CMD_SET_CONTROL && seq == SQ_DIP) {
      if (dipRetry < TGT_SET_RETRY) { dipRetry++; dipPhase = 1; }
      else { dipPhase = 0; tgtDirty = true; tgtDirtyAt = now; setMsgP(M_SETFAIL); }
    }
    pendCmd = 0;
    seq     = SQ_NONE;
  }
ackTimeoutDone:

  /* ---- 鏈路看門狗 ---- */
  if (linkAlive && lastRxAt && (int32_t)(now - lastRxAt) > (int32_t)LINK_TIMEOUT_MS) {   // 有號，理由見 loop() 開頭
    linkAlive = false;
    setMsgP(M_LOST);
    diagEmit(M_DGLOST, now);     // 0.16M：斷線當下這 10 秒窗內收了什麼
  }

  /* ---- §14 開機查詢：HEARTBEAT → GET_VERSION → GET_SYSTEM_INFO ----
     這兩個指令不回 ACK 而是直接回資料包，所以不能走 sendAwait，
     自己管重試。鏈路一活過來就問，問三次還沒回就放棄，不影響主功能。 */
  /* 0.18M：每 VIN_POLL_MS 重問一次 SYSTEM_INFO。0.16M 以前是靠假的 LINK UP（每幾秒一次）順便重問，
     VIN 才會一直更新；0.17M 修掉假斷線後 VIN 只剩開機那一筆，align_dyno 的掉壓判定就沒資料了。 */
  static uint32_t lastVinPoll = 0;
  if (linkAlive && sysStep >= 4 && (now - lastVinPoll) >= VIN_POLL_MS) { lastVinPoll = now; sysStep = 2; sysRetry = 0; sysQuiet = true; }

  if (linkAlive && sysStep < 4 && seq == SQ_NONE && !pendCmd) {
    if (sysStep == 0)      { sendCmd(CMD_GET_VERSION,     NULL, 0); sysStep = 1; sysAt = now; }
    else if (sysStep == 2) { sendCmd(CMD_GET_SYSTEM_INFO, NULL, 0); sysStep = 3; sysAt = now; }
    else if (now - sysAt > 1000) {
      if (++sysRetry >= 3) sysStep = 4;   // 問不到就算了
      else                 sysStep--;     // 1→0 或 3→2，退回去重送
    }
  }

  /* ---- 按鍵 ---- */
  if (uiSeq) {
    /* SEQ 畫面：↑↓ 選序列；跑的時候不准動，避免誤觸改掉 duty */
    if (!seqActive) {
      /* 0.11M：SEQ1..SEQ_N 之後接著是計畫 60A1 / 60A2 / 60B / CMP1 / CMP2 / C90A / C90B / C120（0.14M） */
      if (evEdge[B_UP])   { uiSel = (uint8_t)((uiSel + 1) % (SEQ_N + PLAN_N)); msg[0] = 0; }
      if (evEdge[B_DOWN]) { uiSel = (uint8_t)((uiSel + SEQ_N + PLAN_N - 1) % (SEQ_N + PLAN_N)); msg[0] = 0; }
      if (uiSel < SEQ_N) seqSel = uiSel;
    }
  } else {
    if (evEdge[B_UP])     bumpTarget(+1, 1);
    if (evEdge[B_DOWN])   bumpTarget(-1, 1);
    if (mode == MODE_DUTY) {
      if (evRepeat[B_UP])   dutyPreset(B_UP, +1);
      if (evRepeat[B_DOWN]) dutyPreset(B_DOWN, -1);
    } else {
      if (evRepeat[B_UP])   bumpTarget(+1, accel(B_UP));
      if (evRepeat[B_DOWN]) bumpTarget(-1, accel(B_DOWN));
    }
  }

  bool dipMode = !uiSeq && (mode == MODE_DUTY) && confirmedRunning() && !faulted;
  if (dipMode && evLong[B_START]) {
    dipIdx = (uint8_t)((dipIdx + 1) % DIP_N);
    uint16_t ms = pgm_read_word(&DIP_MS[dipIdx]);
    setMsgF(PSTR("DIP LEN %u.%us"), ms / 1000, (ms % 1000) / 100);
  } else if (dipMode && evClick[B_START]) {
    dipAuto = !dipAuto;
    uint16_t ms = pgm_read_word(&DIP_MS[dipIdx]);
    if (dipAuto) setMsgF(PSTR("AUTO DIP ON %u.%us"), ms / 1000, (ms % 1000) / 100);
    else         setMsgF(PSTR("AUTO DIP OFF"));
  }
  else if (uiSeq && evClick[B_START] && !faulted) {
    if (zeroPending) setMsgP(M_BUSY);                    // 0.10M：保證歸零還沒完成，不准開新序列
    else if (!seqActive) {
      if (uiSel >= SEQ_N) planStart((uint8_t)(uiSel - SEQ_N + 1));   // 0.11M
      else { planId = 0; seqStart(); }
    }
  }
  else if (evLong[B_START]) cycleMode();
  else if (evClick[B_START]) {
    /* FAULT 時第一次按是清錯誤（反正多半 arm 不起來）；
       但如果清完還是 FAULT，再按一次就直接送 arm 序列 ——
       這是唯一能問出「下控在 FAULT 下接不接受 START」的方法，
       也就是 PROTOCOL_NOTES 待確認事項第 3 條。 */
    if (faulted && !resetTried) { resetTried = true; seqResetError(); }
    else                        seqArm();
  }

  if (evLong[B_STOP])       { bool a = seqActive; seqAbort(M_SQABORT); if (a) target = 0; seqSafeZero(a ? M_SQABORT : NULL); }
  else if (evClick[B_STOP]) {
    /* 0.10M：序列中短按 # 也走保證歸零（SET 0 → STOP），不只送 STOP */
    if (seqActive) { seqAbort(M_SQABORT); target = 0; seqSafeZero(M_SQABORT); }
    else seqStop();
  }

  seqTick(now);

  /* ---- 目標值推送（節流） ----
     DUTY 模式按鍵還按著就先不送：調整途中的值只顯示在 OLED，放開才送最後那個值。
     否則從 60 調到 30 的途中 50、40 都會真的送出去，量磁滯時會被這些中間值污染。 */
  /* 0.9M：序列跑著時按鍵不改 duty，所以按住也不能擋序列自己的推送 */
  bool dutyHeld = !seqActive && (mode == MODE_DUTY) && (bs[B_UP].down || bs[B_DOWN].down);

  /* ---- 保證歸零（0.9M）：SET_CONTROL(0) → STOP，直到兩個都 ACK OK ---- */
  /* 0.10M：下控 STATUS 確認已不在 RUNNING（至少試過一次後）就結束重試迴圈 */
  if (zeroPending && zeroTries && linkAlive && sr.valid && !(sr.flags & 0x02) &&
      seq == SQ_NONE && !pendCmd) {
    zeroFinish(PSTR("+IDLE"));
  }
  /* 0.10M：只有 RX 斷（收不到 STATUS）但 TX 可能還通：每秒盲送一次 STOP（不等 ACK） */
  if (zeroPending && !linkAlive && (now - blindStopAt) >= ZERO_RETRY_MS) {
    blindStopAt = now;
    sendCmd(CMD_STOP, NULL, 0);
  }
  if (zeroPending && linkAlive && seq == SQ_NONE && !pendCmd &&
      (now - zeroAt) >= ZERO_RETRY_MS) {
    zeroAt = now; dipPhase = 0; tgtDirty = false;
    if (zeroTries++) {
      if (zeroWhy) setMsgF(PSTR("%S R%u"), zeroWhy, (unsigned)zeroTries);
      else         setMsgF(PSTR("ZERO RETRY %u"), (unsigned)zeroTries);
    }
    sendSetControl(0);
    seq = SQ_ZERO_SET;
  }

  /* ---- 短暫歸零 ---- 歸零期間擋住一般推送，時間到才把 target 送回去 */
  /* 0.12M：只有「鏈路活著、下控確認不在 RUNNING」才取消歸零。原本 !confirmedRunning() 在 LINK LOST
     （當時約每 7 秒一次、每次 ~0.1 s，0.17M 查明是誤判）時也成立 —— 10/19 60B 的 DIP5 在歸零 0.9 s 時碰上 LINK LOST，
     歸零被取消、序列補推 30%，實際只歸零約 1 秒，那一段數據作廢。 */
  if (dipPhase && linkAlive && !confirmedRunning()) dipPhase = 0;      // 真的停了就不用回復
  if (dipPhase == 1 && seq == SQ_NONE && !pendCmd) {
    sendSetControl(0);                                    // ACK 後 lastSent 變 0，送回時就不會再觸發歸零
    seq = SQ_DIP; dipPhase = 2; dipT0 = now;              // ACK 回來時 dipT0 會再校正
  } else if (dipPhase == 2 && linkAlive && seq == SQ_NONE && !pendCmd &&   // 斷線中先不結束，等鏈路回來再送回
             (int32_t)(now - dipT0) >= (int32_t)dipLenMs) {
    /* 有號比較：dipT0 是在 ACK 處理時取的 millis()，可能比這一圈的 now 還晚 */
    dipPhase = 0;
    tgtDirty = true; tgtDirtyAt = now - TGT_PUSH_MS; tgtRetry = 0;
    setMsgF(PSTR("DIP END, TO %u.%u%%"), target / 10, target % 10);
  }

  if (tgtDirty && !dipPhase && !zeroPending) {
    if (!confirmedRunning()) {
      tgtDirty = false;             // 沒在跑就只改本地設定值，按 START 時才一起送出
    } else if (!dutyHeld && seq == SQ_NONE && !pendCmd && (int32_t)(now - tgtDirtyAt) >= (int32_t)TGT_PUSH_MS) {
      tgtDirty = false;
      if (mode == MODE_DUTY && dipAuto && target < lastSent) {
        dipPhase = 1; dipRetry = 0;                       // 往下調：先歸零，時間到再送 target
        dipLenMs = pgm_read_word(&DIP_MS[dipIdx]);
        setMsgF(PSTR("DIP 0 FOR %u.%us"), dipLenMs / 1000, (dipLenMs % 1000) / 100);
      } else {
        sendSetControl(target);
        seq = SQ_SET;
      }
    }
  }

  /* ---- 堆疊餘裕看門狗 ----
     沒剩多少就直接寫進事件行。RAM 被踩爛的症狀是隨機當機，
     那種東西在現場很難跟通訊問題分開，寧可讓它自己講出來。 */
  static uint32_t lastRamChk = 0;
  if (now - lastRamChk >= 1000) {
    lastRamChk = now;
    uint16_t hr = ramHeadroom();
    if (hr < 96) setMsgF(PSTR("LOW RAM %u"), (unsigned)hr);
  }

  /* ---- 畫面 ---- */
  static uint32_t lastDraw = 0;
  /* 0.19M：上一個畫面的 8 頁畫完才開始下一個畫面；每圈只畫一頁 */
  if (!rd.active && now - lastDraw >= OLED_REFRESH_MS) { lastDraw = now; renderBegin(); }
  renderStep();

#if TELEMETRY_MS
  static uint32_t lastTel = 0;
  if (now - lastTel >= TELEMETRY_MS) { lastTel = now; telemetry(); }
#endif
}
