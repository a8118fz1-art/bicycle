/*
  ems_head_unit.ino — EMS Bike 獨立測試用手把單元 (v0.4)

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
#include <AltSoftSerial.h>
#include <stdarg.h>

/* ==================== 設定 ==================== */
#define FW_VERSION         "0.6"  // 顯示在待機畫面上，回報問題時用來對版本
#define EMS_BAUD          19200   // 通訊協定 §2
#define TELEM_BAUD       115200   // D0/D1 遙測輸出速率
#define OLED_ADDR          0x3C

#define HEARTBEAT_MS       1000   // 協定 §12 標稱 100ms，廠商說 1 秒即可；對 3 秒逾時有 3 倍餘裕
#define ACK_TIMEOUT_MS      600   // 同 uart_session.js 的 ackTimeoutMs
#define LINK_TIMEOUT_MS    1000   // 下控 STATUS 週期 100ms，1 秒沒收到視為斷線
#define TGT_PUSH_MS         250   // 目標值連續調整時的送出節流
#define TGT_SET_RETRY         3   // SET_CONTROL 沒收到 ACK 時最多補送幾次
#define OLED_REFRESH_MS     150
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

AltSoftSerial ems;   // 固定 D8 = RX、D9 = TX
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
static uint16_t lastSent = 0;     // 最後一次送給下控的 SET_CONTROL 目標值

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
  lastSent = t;
  uint8_t d[3] = { mode, (uint8_t)(t & 0xFF), (uint8_t)(t >> 8) };
  sendAwait(CMD_SET_CONTROL, d, 3);
}

/* ==================== 序列 ==================== */
static void seqArm() {
  if (seq != SQ_NONE) { setMsgP(M_BUSY); return; }
  sendSetControl(target);
  seq = SQ_ARM_SET;
}

static void seqStop() {
  if (seq != SQ_NONE) { setMsgP(M_BUSY); return; }
  sendAwait(CMD_STOP, NULL, 0);
  seq = SQ_STOP;
  /* 心跳刻意不停 —— 停了 30 秒後下控會直接斷電 */
}

static void seqSafeZero() {
  if (seq != SQ_NONE) { setMsgP(M_BUSY); return; }
  sendSetControl(0);
  seq = SQ_ZERO_SET;
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
    case SQ_ZERO_STOP:  seq = SQ_NONE; setMsgP(M_ZERO);    break;
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

static void onFrame(uint8_t cmd, const uint8_t *d, uint8_t n) {
  lastRxAt = millis();
  if (!linkAlive) { linkAlive = true; sysStep = 0; sysRetry = 0; setMsgP(M_UP); }

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
    setMsgF(PSTR("VIN %u.%02uV FW%u.%u.%u"),
            (unsigned)(vinMv / 1000), (unsigned)((vinMv % 1000) / 10),
            (unsigned)fw[0], (unsigned)fw[1], (unsigned)fw[2]);
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
      if (b == 0 || b > RX_MAX - 1) { rx.state = S_SOF1; break; }
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
        else crcErrCnt++;
      }
      rx.state = S_SOF1;
      break;
  }
}

/* 必須被頻繁呼叫，包含 OLED 分頁重繪的迴圈裡面。
   下控每 100ms 丟 21 bytes，AltSoftSerial 的 RX 緩衝 80 bytes，
   只要別停下來超過 ~40ms 就不會掉。 */
static void pumpEms() {
  while (ems.available()) feed((uint8_t)ems.read());
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
  mode = (uint8_t)((mode + 1) % 3);
  if (target > TGT_MAX[mode]) target = TGT_MAX[mode];
  msg[0] = 0;
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
  先把五行文字全部排好再進分頁迴圈。
  兩個理由：分頁模式下同一畫面會重畫 8 次，在迴圈裡 snprintf 等於算 8 遍；
  而且迴圈中間會呼叫 pumpEms()，全域狀態可能在兩個分頁之間被更新，
  直接讀全域會畫出上下半截不一致的畫面。
*/
static void render() {
  char L[5][21];
  char t[10], mn[6], sb[8];

  copyP(mn, sizeof(mn), (PGM_P)pgm_read_ptr(&MODE_NAME[mode]));
  fmtTarget(t, sizeof(t), target);
  stateBadge(sb, sizeof(sb));

  /* 本機設定值與下控實際採用的目標值不同時標 * —— 看得出設定有沒有真的送進去 */
  bool unsent = sr.valid && (sr.tgt != target);
  snprintf_P(L[0], sizeof(L[0]), PSTR("%-4s %-7s%c"), mn, t, unsent ? '*' : ' ');

  if (sr.valid) {
    snprintf_P(L[1], sizeof(L[1]), PSTR("RPM %4u PWR %4uW"), (unsigned)sr.rpm, (unsigned)sr.watt);
    /* RPM_FAIL 時 DTY / mA 必定是 0，那一行沒有資訊量。
       換成 RPM 的最小-最大與樣本數，把「會飄」變成可以拿去對帳的數字。 */
    if (sr.err & 0x02)
      snprintf_P(L[2], sizeof(L[2]), PSTR("RPM %u-%u n%lu"),
                 (unsigned)(rpmSamples ? rpmMin : 0), (unsigned)rpmMax,
                 (unsigned long)rpmSamples);
    else
      snprintf_P(L[2], sizeof(L[2]), PSTR("DTY %u.%u%% %umA"),
                 (unsigned)(sr.dutyX10 / 10), (unsigned)(sr.dutyX10 % 10), (unsigned)sr.mA);
    /* RPM_FAIL 時第 4 行讓位給波形圖，這裡放空字串讓文字迴圈跳過 */
    if (sr.err & 0x02)
      L[3][0] = 0;
    /* POWER_FAIL 時把 VIN 換上來 —— 線圈電源電壓是判斷這個錯誤的第一手資料 */
    else if ((sr.err & 0x04) && sysValid)
      snprintf_P(L[3], sizeof(L[3]), PSTR("VIN %u.%02uV E%04X"),
                 (unsigned)(vinMv / 1000), (unsigned)((vinMv % 1000) / 10), (unsigned)sr.err);
    else
      snprintf_P(L[3], sizeof(L[3]), PSTR("TGT %-5u ERR %04X"),
                 (unsigned)sr.tgt, (unsigned)sr.err);
  } else {
    /* 還沒收到下控封包時（上機第一階段），把剩餘 RAM 秀出來當健康檢查 */
    strcpy_P(L[1], PSTR("waiting for STATUS"));
    snprintf_P(L[2], sizeof(L[2]), PSTR("FW " FW_VERSION "  CRC ERR %u"), (unsigned)crcErrCnt);
    snprintf_P(L[3], sizeof(L[3]), PSTR("FREE RAM %u"), (unsigned)ramHeadroom());
  }

  strncpy(L[4], msg, sizeof(L[4]) - 1);
  L[4][sizeof(L[4]) - 1] = 0;

  int8_t bx = (int8_t)(128 - 6 * (int8_t)strlen(sb));
  /* 有波形時訊息行往下讓，沒有就維持原位 */
  bool trace = sr.valid && (sr.err & 0x02);
  int8_t msgY = trace ? 63 : 54;

  oled.firstPage();
  do {
    pumpEms();                       // 重繪期間也要繼續收，否則會掉封包
    oled.setFont(u8g2_font_6x12_tr);
    for (uint8_t r = 0; r < 4; r++) if (L[r][0]) line(r, L[r]);
    oled.drawStr(bx, 10, sb);
    if (trace) drawTrace(36, 16);
    if (L[4][0]) { oled.drawStr(0, msgY, ">"); oled.drawStr(8, msgY, L[4]); }
  } while (oled.nextPage());
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

  render();
}

void loop() {
  uint32_t now = millis();

  pumpEms();
  scanButtons();

  /* ---- 心跳 ---- */
  if (now - lastHbAt >= HEARTBEAT_MS) {
    lastHbAt = now;
    sendCmd(CMD_HEARTBEAT, NULL, 0);
  }

  /* ---- ACK 逾時 ---- */
  if (pendCmd && (now - pendAt) > ACK_TIMEOUT_MS) {
    char cn[8];
    cmdName(cn, sizeof(cn), pendCmd);
    setMsgF(PSTR("ACK TIMEOUT %s"), cn);
    /* 單純的目標值推送掉了就自己補送。原本這裡直接放掉，畫面上的設定值與下控
       實際採用的值會就此分家（只剩標題列的 * 提示），掃點時等於整筆作廢。
       arm/stop 那幾個序列不在此列 —— 它們有使用者按鍵當重試。 */
    if (pendCmd == CMD_SET_CONTROL && seq == SQ_SET) {
      if (tgtRetry < TGT_SET_RETRY) { tgtRetry++; tgtDirty = true; tgtDirtyAt = now; }
      else                            setMsgP(M_SETFAIL);
    }
    /* 歸零那一包掉了：補送；補不上就放棄歸零，直接送回原值 */
    if (pendCmd == CMD_SET_CONTROL && seq == SQ_DIP) {
      if (dipRetry < TGT_SET_RETRY) { dipRetry++; dipPhase = 1; }
      else { dipPhase = 0; tgtDirty = true; tgtDirtyAt = now; setMsgP(M_SETFAIL); }
    }
    pendCmd = 0;
    seq     = SQ_NONE;
  }

  /* ---- 鏈路看門狗 ---- */
  if (linkAlive && lastRxAt && (now - lastRxAt) > LINK_TIMEOUT_MS) {
    linkAlive = false;
    setMsgP(M_LOST);
  }

  /* ---- §14 開機查詢：HEARTBEAT → GET_VERSION → GET_SYSTEM_INFO ----
     這兩個指令不回 ACK 而是直接回資料包，所以不能走 sendAwait，
     自己管重試。鏈路一活過來就問，問三次還沒回就放棄，不影響主功能。 */
  if (linkAlive && sysStep < 4 && seq == SQ_NONE && !pendCmd) {
    if (sysStep == 0)      { sendCmd(CMD_GET_VERSION,     NULL, 0); sysStep = 1; sysAt = now; }
    else if (sysStep == 2) { sendCmd(CMD_GET_SYSTEM_INFO, NULL, 0); sysStep = 3; sysAt = now; }
    else if (now - sysAt > 1000) {
      if (++sysRetry >= 3) sysStep = 4;   // 問不到就算了
      else                 sysStep--;     // 1→0 或 3→2，退回去重送
    }
  }

  /* ---- 按鍵 ---- */
  if (evEdge[B_UP])     bumpTarget(+1, 1);
  if (evEdge[B_DOWN])   bumpTarget(-1, 1);
  if (mode == MODE_DUTY) {
    if (evRepeat[B_UP])   dutyPreset(B_UP, +1);
    if (evRepeat[B_DOWN]) dutyPreset(B_DOWN, -1);
  } else {
    if (evRepeat[B_UP])   bumpTarget(+1, accel(B_UP));
    if (evRepeat[B_DOWN]) bumpTarget(-1, accel(B_DOWN));
  }

  bool dipMode = (mode == MODE_DUTY) && confirmedRunning() && !faulted;
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
  else if (evLong[B_START]) cycleMode();
  else if (evClick[B_START]) {
    /* FAULT 時第一次按是清錯誤（反正多半 arm 不起來）；
       但如果清完還是 FAULT，再按一次就直接送 arm 序列 ——
       這是唯一能問出「下控在 FAULT 下接不接受 START」的方法，
       也就是 PROTOCOL_NOTES 待確認事項第 3 條。 */
    if (faulted && !resetTried) { resetTried = true; seqResetError(); }
    else                        seqArm();
  }

  if (evLong[B_STOP])       seqSafeZero();
  else if (evClick[B_STOP]) seqStop();

  /* ---- 目標值推送（節流） ----
     DUTY 模式按鍵還按著就先不送：調整途中的值只顯示在 OLED，放開才送最後那個值。
     否則從 60 調到 30 的途中 50、40 都會真的送出去，量磁滯時會被這些中間值污染。 */
  bool dutyHeld = (mode == MODE_DUTY) && (bs[B_UP].down || bs[B_DOWN].down);

  /* ---- 短暫歸零 ---- 歸零期間擋住一般推送，時間到才把 target 送回去 */
  if (dipPhase && !confirmedRunning()) dipPhase = 0;      // 停了就不用回復
  if (dipPhase == 1 && seq == SQ_NONE && !pendCmd) {
    sendSetControl(0);                                    // lastSent 跟著變 0，送回時就不會再觸發歸零
    seq = SQ_DIP; dipPhase = 2; dipT0 = now;              // ACK 回來時 dipT0 會再校正
  } else if (dipPhase == 2 && seq == SQ_NONE && !pendCmd &&
             (int32_t)(now - dipT0) >= (int32_t)pgm_read_word(&DIP_MS[dipIdx])) {
    /* 有號比較：dipT0 是在 ACK 處理時取的 millis()，可能比這一圈的 now 還晚 */
    dipPhase = 0;
    tgtDirty = true; tgtDirtyAt = now - TGT_PUSH_MS; tgtRetry = 0;
    setMsgF(PSTR("DIP END, TO %u.%u%%"), target / 10, target % 10);
  }

  if (tgtDirty && !dipPhase) {
    if (!confirmedRunning()) {
      tgtDirty = false;             // 沒在跑就只改本地設定值，按 START 時才一起送出
    } else if (!dutyHeld && seq == SQ_NONE && !pendCmd && (now - tgtDirtyAt) >= TGT_PUSH_MS) {
      tgtDirty = false;
      if (mode == MODE_DUTY && dipAuto && target < lastSent) {
        dipPhase = 1; dipRetry = 0;                       // 往下調：先歸零，時間到再送 target
        uint16_t ms = pgm_read_word(&DIP_MS[dipIdx]);
        setMsgF(PSTR("DIP 0 FOR %u.%us"), ms / 1000, (ms % 1000) / 100);
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
  if (now - lastDraw >= OLED_REFRESH_MS) { lastDraw = now; render(); }

#if TELEMETRY_MS
  static uint32_t lastTel = 0;
  if (now - lastTel >= TELEMETRY_MS) { lastTel = now; telemetry(); }
#endif
}
