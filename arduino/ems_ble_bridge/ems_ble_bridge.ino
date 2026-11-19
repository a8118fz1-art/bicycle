/*
  ems_ble_bridge.ino — EMS Bike 無線 UART 測試棒 (v0.1)

  硬體：BLE-Nano 4.2（ATmega328P-AU QFP32 + BLE 4.2 模組，Type-C）
        0.96" SSD1306 128x64 OLED（硬體 I2C，位址 0x3C）
        4 顆按鍵（INPUT_PULLUP，按下 = LOW）

  資料流：
    PC / 手機 ──BLE──► 模組 ──D0/D1 @115200──► ATmega ──D8/D9 @19200──► EMS 下控
              ◄──────────────────────────────────────────────────────────

  ATmega 只做兩件事：
    1. 雙向原樣轉發位元組，完全不改內容
    2. 旁聽「下控 → 上控」方向，解出封包統計與 STATUS_REPORT 畫在 OLED 上

  協定與 uart.js / uart_session.js 完全一致：
    SOF 55 AA | LEN(= CMD+DATA 長度) | CMD | DATA... | CRC_L CRC_H | EOF 0D
    CRC = CRC-16/CCITT-FALSE（init 0xFFFF、poly 0x1021、不反射、不做最終 XOR）
          涵蓋範圍 = LEN + CMD + DATA，小端送出

  接線變更：4 號按鍵在舊案 master.ino 是接 D8，
     但 D8 是 AltSoftSerial 在 328P 上「固定」的 RX 腳，改不了，
     所以 4 號鍵必須改接 D7。（AltSoftSerial 另外會佔用 D10 的 PWM，本專案用不到。）

  注意：本檔案「不可」使用 Serial.print() 做任何除錯輸出。
     硬體 Serial 在這裡是純二進位封包通道，混入任何 ASCII 都會被
     上控的 parseUartFrame() 當成雜訊。要除錯請畫到 OLED 上。
*/

#include <Wire.h>
#include <U8g2lib.h>
#include <AltSoftSerial.h>

/* ==================== 設定 ==================== */
#define BLE_BAUD        115200   // 模組 UART 速率（沿用舊案 master.ino 的實測值）
#define EMS_BAUD         19200   // 通訊協定 §2：19200 8-N-1
#define OLED_ADDR         0x3C
#define OLED_REFRESH_MS     200  // 5Hz；下控 STATUS 是 10Hz，不需要畫那麼快
#define DEBOUNCE_MS          30

/*
  BLE 模組的 AT 設定。
  預設 0 = 開機不下任何 AT 指令，直接用模組出廠值（周邊 / peripheral，等別人來連）。

  舊案 master.ino 用的是這三行，但那是「主動去連另一顆模組」的用法：
      AT+ROLE=0      註解寫「設為主機」→ 這顆韌體的 ROLE 定義與 HM-10 相反，別照抄網路教學
      AT+BLEUSB=3    疑似控制 BLE / USB / MCU 之間的路由，值的意義待查
      AT+CON=<MAC>   連到指定 MAC 的從機
  測試棒要的是相反方向（讓 PC/手機來連我們），所以預設不動它。
  真的需要改設定時把下面改成 1，並填入正確指令。
*/
#define BLE_AT_SETUP 0

static const uint8_t PIN_BTN[4] = { 2, 4, 6, 7 };   // 見上方接線變更說明
enum { BTN_PREV = 0, BTN_CLEAR = 1, BTN_FREEZE = 2, BTN_NEXT = 3 };

AltSoftSerial ems;   // 固定 D8 = RX（接下控 TX）、D9 = TX（接下控 RX）
U8G2_SSD1306_128X64_NONAME_1_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);  // _1_ = 分頁模式，只吃 128B

/* ==================== 協定常數 ==================== */
/* 對照 uart_session.js 的 CMD 表 */
enum : uint8_t {
  CMD_START = 0x01, CMD_STOP = 0x02, CMD_RESET_ERROR = 0x03, CMD_SHUTDOWN = 0x06,
  CMD_SET_CONTROL = 0x10, CMD_GET_VERSION = 0x20, CMD_GET_SYSTEM_INFO = 0x21,
  CMD_HEARTBEAT = 0x40, CMD_STATUS_REPORT = 0x80, CMD_SYSTEM_INFO = 0x81,
  CMD_ACK = 0xF0, CMD_ERROR_REPORT = 0xF1
};

/* §8 ACK_RESULT */
static const char ACK_R0[] PROGMEM = "OK";
static const char ACK_R1[] PROGMEM = "CRC_ERR";
static const char ACK_R2[] PROGMEM = "PARAM_ERR";
static const char ACK_R3[] PROGMEM = "BUSY";
static const char ACK_R4[] PROGMEM = "UNKNOWN_CMD";
static const char ACK_R5[] PROGMEM = "INVALID_STATE";
static const char* const ACK_NAME[] PROGMEM = { ACK_R0, ACK_R1, ACK_R2, ACK_R3, ACK_R4, ACK_R5 };

/* §6 CONTROL_MODE */
static const char MODE_M0[] PROGMEM = "KP";
static const char MODE_M1[] PROGMEM = "ERG";
static const char MODE_M2[] PROGMEM = "DUTY";
static const char* const MODE_NAME[] PROGMEM = { MODE_M0, MODE_M1, MODE_M2 };

/* ==================== CRC-16/CCITT-FALSE ==================== */
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

/* ==================== 串流封包解析 ==================== */
/*
  用狀態機而不是滑動視窗（uart.js 的做法），因為 328P 的 2KB SRAM
  放不下舒服的環形緩衝。行為等價：LEN / CRC / EOF 任一不符就丟掉這一包，
  回到找 SOF 的狀態，不會卡死在半包上。
*/
#define RX_MAX 40   // LEN + payload；STATUS_REPORT 的 LEN 是 0x0F，這裡留兩倍餘裕

enum { S_SOF1, S_SOF2, S_LEN, S_PAYLOAD, S_CRC_L, S_CRC_H, S_EOF };

static struct {
  uint8_t  state;
  uint8_t  len;
  uint8_t  idx;
  uint8_t  buf[RX_MAX];   // buf[0]=LEN, buf[1]=CMD, buf[2..]=DATA（CRC 涵蓋範圍剛好是這一整段）
  uint16_t crcRx;
} rx;

/* ==================== 統計與最後狀態 ==================== */
static struct {
  uint32_t frames;        // CRC 正確的完整封包數
  uint32_t statusCnt;     // 其中 STATUS_REPORT 的數量
  uint16_t crcErr;
  uint16_t badFrm;        // EOF 不是 0x0D 或 LEN 超出範圍
  uint32_t txBytes;       // 上控 → 下控 轉發的位元組數
  uint32_t lastStatusMs;
  uint16_t gapMs;         // 兩次 STATUS 的間隔，協定標稱 100ms
} st;

static struct {
  uint16_t rpm, mA, watt, dutyX10, target, error;
  uint8_t  mode, status;
  bool     valid;
} sr;

static struct {
  uint8_t cmd, result;
  bool    valid;
} ack;

/* 最後一包「非 STATUS」的原始位元組。STATUS 以 10Hz 洗版，
   真正要看的是 ACK / ERROR_REPORT / SYSTEM_INFO 這些偶發封包。 */
static uint8_t lastRaw[RX_MAX];
static uint8_t lastRawLen = 0;

/* ==================== 封包處理 ==================== */
static void onFrame(uint8_t cmd, const uint8_t *d, uint8_t n) {
  st.frames++;

  if (cmd == CMD_STATUS_REPORT && n >= 13) {
    uint32_t now = millis();
    if (st.lastStatusMs) st.gapMs = (uint16_t)(now - st.lastStatusMs);
    st.lastStatusMs = now;
    st.statusCnt++;

    sr.rpm     = rd16(d + 0);
    sr.mA      = rd16(d + 2);
    sr.watt    = rd16(d + 4);
    sr.dutyX10 = rd16(d + 6);
    sr.target  = rd16(d + 8);
    sr.mode    = d[10];
    sr.status  = d[11];
    /* 與 uart_session.js 一致：error 在 v0.2 是 uint16（DATA 14 bytes），
       但保留 13 bytes 舊韌體的退路，免得整個 STATUS 顯示失效。 */
    sr.error   = (n >= 14) ? rd16(d + 12) : d[12];
    sr.valid   = true;
    return;
  }

  /* 非 STATUS 的封包：留一份原始位元組供 RAW 頁檢視 */
  lastRawLen = (uint8_t)min((int)(1 + rx.len), RX_MAX);
  memcpy(lastRaw, rx.buf, lastRawLen);

  if (cmd == CMD_ACK && n >= 1) {
    ack.cmd    = d[0];
    ack.result = (n > 1) ? d[1] : 0;
    ack.valid  = true;
  }
}

static void feed(uint8_t b) {
  switch (rx.state) {
    case S_SOF1:
      if (b == 0x55) rx.state = S_SOF2;
      break;

    case S_SOF2:
      if (b == 0xAA)      rx.state = S_LEN;
      else if (b == 0x55) ;                  // 連續 0x55，停在這裡繼續等 0xAA
      else                rx.state = S_SOF1;
      break;

    case S_LEN:
      if (b == 0 || b > RX_MAX - 1) { st.badFrm++; rx.state = S_SOF1; break; }
      rx.len = b; rx.buf[0] = b; rx.idx = 1; rx.state = S_PAYLOAD;
      break;

    case S_PAYLOAD:
      rx.buf[rx.idx++] = b;
      if (rx.idx >= (uint8_t)(1 + rx.len)) rx.state = S_CRC_L;
      break;

    case S_CRC_L:
      rx.crcRx = b; rx.state = S_CRC_H;
      break;

    case S_CRC_H:
      rx.crcRx |= (uint16_t)b << 8; rx.state = S_EOF;
      break;

    case S_EOF:
      if (b != 0x0D)                                        st.badFrm++;
      else if (crc16ccitt(rx.buf, 1 + rx.len) != rx.crcRx)  st.crcErr++;
      else                                                  onFrame(rx.buf[1], &rx.buf[2], rx.len - 1);
      rx.state = S_SOF1;
      break;
  }
}

/* ==================== 橋接 ==================== */
/*
  必須被頻繁呼叫，包括 OLED 分頁重繪的迴圈裡面。
  下控每 100ms 丟 21 bytes（SOF2+LEN1+CMD1+DATA14+CRC2+EOF1），
  AltSoftSerial 的 RX 緩衝有 80 bytes，只要別停下來超過 ~40ms 就不會掉。
*/
static void pump() {
  while (Serial.available()) { ems.write((uint8_t)Serial.read()); st.txBytes++; }
  while (ems.available())    { uint8_t b = (uint8_t)ems.read(); Serial.write(b); feed(b); }
}

/* ==================== 按鍵 ==================== */
static uint8_t  btnLast = 0x0F;      // bit0..3，1 = 放開
static uint32_t btnAt[4];
static uint8_t  btnEvent = 0;        // 本輪按下的邊緣，bit0..3

static void scanButtons() {
  uint32_t now = millis();
  for (uint8_t i = 0; i < 4; i++) {
    uint8_t cur = digitalRead(PIN_BTN[i]) ? 1 : 0;
    uint8_t old = (btnLast >> i) & 1;
    if (cur == old) continue;
    if (now - btnAt[i] < DEBOUNCE_MS) continue;
    btnAt[i] = now;
    btnLast = (uint8_t)((btnLast & ~(1 << i)) | (cur << i));
    if (cur == 0) btnEvent |= (1 << i);   // 放開 → 按下
  }
}

/* ==================== 畫面 ==================== */
#define PAGE_COUNT 4
static uint8_t page = 0;
static bool    frozen = false;

static void line(uint8_t row, const char *s) { oled.drawStr(0, (int8_t)(10 + row * 11), s); }

/* 把 0.1 為單位的整數印成 "x.y"，避免 AVR 上要另外連結浮點 printf */
static void fmtTenths(char *out, uint8_t cap, uint16_t v, const char *suffix) {
  snprintf(out, cap, "%u.%u%s", (unsigned)(v / 10), (unsigned)(v % 10), suffix);
}

/* 把 PROGMEM 字串表的一項複製到 RAM。
   不用 avr-libc 的 %S，因為 avr-gcc 的格式檢查把 %S 當成 wchar_t*，會噴 -Wformat 警告。 */
static void copyP(char *out, uint8_t cap, const char* const *table, uint8_t idx) {
  strncpy_P(out, (const char *)pgm_read_ptr(&table[idx]), cap - 1);
  out[cap - 1] = 0;
}

static void drawRide(char *b, uint8_t cap) {
  if (!sr.valid) { line(0, "NO STATUS YET"); return; }

  char t[10];

  snprintf(b, cap, "RPM %4u", (unsigned)sr.rpm);            line(0, b);
  snprintf(b, cap, "PWR %4u W", (unsigned)sr.watt);         line(1, b);

  /* target 的單位隨模式而變：KP 是 0.1 KP，ERG 是 W，DUTY 是 0.1% */
  if (sr.mode == 1) {
    snprintf(b, cap, "ERG %4u W", (unsigned)sr.target);
  } else {
    fmtTenths(t, sizeof(t), sr.target, "");
    char mn[6];
    copyP(mn, sizeof(mn), MODE_NAME, sr.mode < 3 ? sr.mode : 0);
    snprintf(b, cap, "%-4s %s", mn, t);
  }
  line(2, b);

  fmtTenths(t, sizeof(t), sr.dutyX10, "%");
  snprintf(b, cap, "DTY %-6s %umA", t, (unsigned)sr.mA);    line(3, b);

  /* §9 STATUS_FLAG / §10 ERROR_FLAG */
  snprintf(b, cap, "%s%s%s%s%s",
           (sr.status & 0x02) ? "RUN "  : "",
           (sr.status & 0x01) ? "RDY "  : "",
           (sr.status & 0x04) ? "TGT "  : "",
           (sr.status & 0x08) ? "ELIM " : "",
           sr.error ? "ERR!" : "");
  line(4, b);
}

static void drawLink(char *b, uint8_t cap) {
  uint32_t since = st.lastStatusMs ? (millis() - st.lastStatusMs) : 0;
  snprintf(b, cap, "FRAME %10lu", (unsigned long)st.frames);      line(0, b);
  snprintf(b, cap, "STAT  %10lu", (unsigned long)st.statusCnt);   line(1, b);
  snprintf(b, cap, "CRCERR %4u BAD %3u",
           (unsigned)st.crcErr, (unsigned)st.badFrm);             line(2, b);
  snprintf(b, cap, "GAP %4u ms", (unsigned)st.gapMs);             line(3, b);
  if (!st.lastStatusMs)   snprintf(b, cap, "LINK --   TX %lu", (unsigned long)st.txBytes);
  else if (since > 1000)  snprintf(b, cap, "LINK DOWN %lus", (unsigned long)(since / 1000));
  else                    snprintf(b, cap, "LINK UP   TX %lu", (unsigned long)st.txBytes);
  line(4, b);
}

static void drawAck(char *b, uint8_t cap) {
  if (!ack.valid) {
    line(0, "NO ACK YET");
  } else {
    snprintf(b, cap, "ACK CMD 0x%02X", ack.cmd);   line(0, b);
    if (ack.result < 6) {
      char rn[14];
      copyP(rn, sizeof(rn), ACK_NAME, ack.result);
      snprintf(b, cap, "RES %u %s", ack.result, rn);
    } else {
      snprintf(b, cap, "RES %u ?", ack.result);
    }
    line(1, b);
  }
  if (sr.valid) {
    snprintf(b, cap, "ERRFLAG 0x%04X", sr.error);  line(3, b);
    snprintf(b, cap, "%s%s%s%s",
             (sr.error & 0x01) ? "COMM "  : "",
             (sr.error & 0x02) ? "RPM "   : "",
             (sr.error & 0x04) ? "POWER " : "",
             (sr.error & 0x08) ? "COIL"   : "");
    line(4, b);
  }
}

static void drawRaw(char *b, uint8_t cap) {
  line(0, "LAST NON-STATUS");
  if (!lastRawLen) { line(1, "(none)"); return; }
  /* lastRaw[0] = LEN、[1] = CMD，前後的 55 AA / CRC / 0D 不重複顯示 */
  uint8_t row = 1, col = 0;
  b[0] = 0;
  for (uint8_t i = 0; i < lastRawLen && row < 5; i++) {
    snprintf(b + col, (uint8_t)(cap - col), "%02X ", lastRaw[i]);
    col += 3;
    if (col >= 18 || i == lastRawLen - 1) { line(row++, b); col = 0; b[0] = 0; }
  }
}

static void redraw() {
  char b[24];
  oled.firstPage();
  do {
    pump();                          // 分頁重繪期間也要繼續搬位元組，否則會掉封包
    oled.setFont(u8g2_font_6x12_tr);
    switch (page) {
      case 0: drawRide(b, sizeof(b)); break;
      case 1: drawLink(b, sizeof(b)); break;
      case 2: drawAck (b, sizeof(b)); break;
      default: drawRaw(b, sizeof(b)); break;
    }
    if (frozen) oled.drawStr(106, 10, "[F]");
  } while (oled.nextPage());
}

/* ==================== setup / loop ==================== */
void setup() {
  for (uint8_t i = 0; i < 4; i++) pinMode(PIN_BTN[i], INPUT_PULLUP);

  Serial.begin(BLE_BAUD);
  ems.begin(EMS_BAUD);

#if BLE_AT_SETUP
  /* 只有在這裡才可以對 Serial 送 ASCII —— 之後整條線都是二進位封包 */
  delay(200);
  Serial.println(F("AT+ROLE=1"));    // 這顆模組的 ROLE 定義與 HM-10 相反，值要對照模組的 AT 指令表
  Serial.flush();
  delay(300);
#endif

  oled.begin();
  oled.setI2CAddress(OLED_ADDR << 1);
  oled.setBusClock(400000);          // 預設 100kHz 會讓每次重繪多阻塞 ~20ms
  rx.state = S_SOF1;
  redraw();
}

void loop() {
  pump();                            // 第一優先：位元組不能等
  scanButtons();

  if (btnEvent) {
    if (btnEvent & (1 << BTN_NEXT))   page = (uint8_t)((page + 1) % PAGE_COUNT);
    if (btnEvent & (1 << BTN_PREV))   page = (uint8_t)((page + PAGE_COUNT - 1) % PAGE_COUNT);
    if (btnEvent & (1 << BTN_FREEZE)) frozen = !frozen;
    if (btnEvent & (1 << BTN_CLEAR)) {
      memset(&st, 0, sizeof(st));
      ack.valid = false;
      lastRawLen = 0;
    }
    btnEvent = 0;
  }

  static uint32_t lastDraw = 0;
  uint32_t now = millis();
  if (!frozen && (now - lastDraw) >= OLED_REFRESH_MS) { lastDraw = now; redraw(); }
}
