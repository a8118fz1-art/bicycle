#!/usr/bin/env python3
"""
建置「EMS Bike 下控 韌體修改規格（參數指令、微調、磁滯補償）」xlsx（給下控廠商）

用法：
    python tools/reports/build_param_proposal.py [輸出.xlsx]

數值來源：
    參數預設值 = 第六版（build_model_v6.py）
    參考程式   = ems_model_ref.c（avr-gcc -Wall -Wextra 編譯通過；test_model_ref.py 逐行對應並測試）
    封包範例   = proto_examples.py（已用廠商協定附錄 A 的 13 個範例驗證格式與 CRC）
與 build_tft_cal_spec.py（給 TFT 上控廠商）的指令與數值一致。
"""
import math, os, sys
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proto_examples as pe

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    f'~/Downloads/EMS Bike 下控 韌體修改規格_{date.today():%Y%m%d}.xlsx')

assert all(ok for _, ok in pe.verify_vendor()), '封包格式與廠商附錄不一致'

V5 = [2.176389, 0.00657222, 2.3552, 8.6539, 3.0030, 0.004849]
P = pe.DEFAULT
RATIO, KP_NM = 15.0119, 9.8
def sf(c): return (P[3] + 60) / 60 * c / (P[3] + c)
def net(d, c): u = d - P[2]; return max(0.0, (P[0] * u - P[1] * u * u) * sf(c) * P[6])
def tare(c): return P[4] + P[5] * c + P[7]
def duty_from(need, c):
    X = need / (sf(c) * P[6]); return (P[0] - math.sqrt(P[0] ** 2 - 4 * P[1] * X)) / (2 * P[1]) + P[2]

F = '微軟正黑體'
TITLE = Font(name=F, size=14, bold=True, color='123C6B')
H2 = Font(name=F, size=12, bold=True, color='123C6B')
BODY = Font(name=F, size=11)
BOLD = Font(name=F, size=11, bold=True)
RED = Font(name=F, size=11, bold=True, color='C0392B')
MONO = Font(name='Consolas', size=10)
HEAD_FILL = PatternFill('solid', fgColor='E8EEF6')
NEW_FILL = PatternFill('solid', fgColor='FFF8E1')
thin = Side(style='thin', color='9FB3CC')
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(horizontal='left', vertical='top', wrap_text=True)
wb = Workbook(); wb.remove(wb.active)

class Sheet:
    def __init__(self, name, widths=(120,)):
        self.ws = wb.create_sheet(name); self.r = 1
        for i, w in enumerate(widths): self.ws.column_dimensions[chr(65 + i)].width = w
    def line(self, text='', font=BODY):
        self.ws.cell(self.r, 1, text).font = font; self.r += 1
    def title(self, t): self.line(t, TITLE)
    def h(self, t): self.r += 1; self.line(t, H2)
    def lines(self, txt, font=BODY):
        for t in txt.strip('\n').split('\n'): self.line(t, font)
    def table(self, head, data, fill_rows=()):
        for j, v in enumerate(head):
            c = self.ws.cell(self.r, 1 + j, v); c.font = BOLD; c.fill = HEAD_FILL; c.border = BOX
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        self.r += 1
        for i, row in enumerate(data):
            for j, v in enumerate(row):
                c = self.ws.cell(self.r, 1 + j, v); c.font = MONO if isinstance(v, str) and v.startswith('55 AA') else BODY
                c.border = BOX; c.alignment = WRAP
                if i in fill_rows: c.fill = NEW_FILL
            self.r += 1

# ==================== 0 總覽 ====================
s = Sheet('0_總覽')
s.title('EMS Bike 下控　韌體修改規格（參數指令、微調、磁滯補償）')
s.lines(f"""
{date.today():%Y-%m-%d}。本文件是我方提出的修改方案，請貴司評估後回覆（7_請貴司回覆），雙方確認後定案。
與「下控扭力模型 第六版」一起提供：第六版說明模型怎麼來的，本文件說明韌體要怎麼改。
""")
s.line('★ 公式與 FW11.11.0 相同（貴司依我方第五版參數實作的那條），只是把常數改成可寫入的參數並換成第六版數值。', RED)
s.h('我們要做的事（一次改好，之後不需要再重燒韌體）')
s.table(['#', '修改', '為什麼', '詳見'], [
    ('1', '模型常數改成參數：存在 flash，可用指令讀寫', '之後模型更新只要寫入新數值，不用改程式', '1、2、3'),
    ('2', '新增「扭力倍率」參數：VR1 粗調、倍率細調', 'VR1 刻度太粗，調不進 ±1%。VR1 只需粗調到 ±5%，剩下由 TFT 上控量測後自動算出倍率寫入', '1、6'),
    ('3', '磁滯補償：往下調整 duty 時依補償表修正', '從高 duty 往下調，實際扭力比模型高 7～24%', '4'),
    ('4', '新增 7 個指令（0x30～0x36）與 3 個回應（0x82～0x84）', '讀寫上面的參數', '3'),
    ('5', 'STATUS_REPORT 的 status 新增 2 個 bit', '讓上控知道「觸底」與「補償中」', '3'),
])
for col, w in zip('ABCD', (5, 52, 52, 10)): s.ws.column_dimensions[col].width = w
s.h('不變的部分')
s.lines("""
　· 封包格式、CRC、既有指令（0x01～0x81、0xF0、0xF1）的格式與行為完全不變，包括 GET_VERSION。
　· STATUS_REPORT 的欄位與長度不變；只用到 status 欄位裡目前沒用的 bit。
　· 舊的 TFT 上控不送新指令，就跟現在完全一樣。
""")
s.h('本文件各頁')
s.lines("""
　1_公式與參數　：下控用的計算公式，10 個參數各自的意義，代入數字的例子
　2_參數表　　　：編號、第五版值、第六版預設、允許範圍
　3_新增指令　　：指令格式、ACK、狀態 bit、逐 byte 封包範例
　4_磁滯補償　　：機制、補償表、查表例子
　5_參考程式　　：完整 C 程式（計算部分），可直接參考實作
　6_出廠校正流程：TFT 上控如何使用這些指令（給貴司了解使用時機）
　7_請貴司回覆
""")

# ==================== 1 公式與參數 ====================
s = Sheet('1_公式與參數')
s.title('1　公式與參數')
s.h('下控從 duty 算出扭力與功率（est_watt）')
s.lines(f"""
　踏頻　　　= 飛輪RPM / {RATIO}　　　　　　　　　　　　　　　★ 公式用踏頻，不是飛輪 RPM
　u　　　　 = duty − x0　　　　　　　　　　　　　　　　　　 （u ≤ 0 時淨扭力 = 0）
　淨扭力60　= a × u − b × u²　　　　　　　　　　　　　　　 60 踏頻時的煞車扭力（N·m）
　轉速係數　= (c0 + 60) / 60 × 踏頻 / (c0 + 踏頻)　　　　　　60 踏頻時 = 1
　淨扭力　　= 淨扭力60 × 轉速係數 × 扭力倍率　　　　　　　　 線圈產生的煞車扭力
　空載　　　= tare常數 + tare斜率 × 踏頻 + 空載補正　　　　 duty 0 時的機械阻力
　總扭力　　= 淨扭力 + 空載
　est_watt　= 總扭力 × 2π × 踏頻 / 60
""", MONO)
s.h('反過來：要多少扭力 → duty（ERG、KP 共用）')
s.lines("""
　ERG：需要的淨扭力 = 目標W / (2π × 踏頻 / 60) − 空載　　　（ERG 是騎士總功率，要扣空載）
　KP ：需要的淨扭力 = kp × 9.8　　　　　　　　　　　　　　　（KP 本身就是煞車扭力，不扣空載）
　X　 = 需要的淨扭力 / (轉速係數 × 扭力倍率)
　duty = (a − √(a² − 4 × b × X)) / (2 × b) + x0
　　· 需要的淨扭力 ≤ 0：duty 0，設「觸底」bit
　　· a² − 4bX < 0 或 duty > 100：duty 100，設 STATUS_ERG_LIMIT（KP 也一樣用這個 bit）
""", MONO)
s.h('10 個參數的意義')
s.table(['編號', '名稱', '意義（白話）', '例子'], [
    (0, 'a　煞車強度', 'duty 每增加 1%，煞車扭力大約增加 a N·m（60 踏頻）', 'a = 2.37：duty 從 20 到 21 約多 2 N·m'),
    (1, 'b　飽和彎曲', 'duty 越高，扭力增加越慢（電磁鐵磁飽和）；b 描述變慢的程度', 'duty 25 時 b 項約 −4.9 N·m；duty 100 時約 −50 N·m'),
    (2, 'x0　起始 duty', 'duty 低於 x0 時線圈幾乎沒有扭力；也用於觸底判斷', 'x0 = 1.6：duty 1.5 → 扭力 0'),
    (3, 'c0　轉速影響', '同一 duty 下，踏頻越高扭力越大，但越來越平緩', f'同一 duty：30 踏頻是 60 踏頻的 {sf(30):.2f} 倍，120 踏頻是 {sf(120):.2f} 倍'),
    (4, 'tare 常數', '空載阻力的基本值（軸承、皮帶）', f'60 踏頻空載 = {P[4]} + {P[5]} × 60 = {tare(60):.2f} N·m'),
    (5, 'tare 斜率', '空載阻力隨踏頻增加的量（風阻等）', '同上'),
    (6, '扭力倍率', '每台出廠校正的細調（VR1 先粗調到 ±5%）。淨扭力 × 倍率；只改計算，不改線圈實際輸出', '某台煞車比模型強 3% → TFT 寫入 1.030'),
    (7, '空載補正', '預留給機械阻力特別大或小的車，直接加在空載上；目前不使用', '保持 0'),
    (8, '磁滯歸零時間', 'duty 0 維持超過這個秒數，清除「最高 duty」記錄（見 4_磁滯補償）', '2 秒'),
    (9, '磁滯補償開關', '1 = 啟用，0 = 關閉；出問題時可直接關掉', '1'),
])
for col, w in zip('ABCD', (6, 18, 60, 52)): s.ws.column_dimensions[col].width = w
s.h('完整代入一次（60 踏頻 = 飛輪 901 RPM，倍率 1，無磁滯）')
d25 = net(25, 60); w25 = (d25 + tare(60)) * 2 * math.pi
need = 300 / (2 * math.pi) - tare(60); dE = duty_from(need, 60)
s.lines(f"""
　① duty 25 → est_watt
　　u = 25 − {P[2]} = {25 - P[2]:.4f}
　　淨扭力 = {P[0]} × {25 - P[2]:.4f} − {P[1]} × {25 - P[2]:.4f}² = {d25:.2f} N·m　　（功率機實測 50.2～50.8 ✔）
　　空載 = {P[4]} + {P[5]} × 60 = {tare(60):.4f} N·m
　　est_watt = ({d25:.2f} + {tare(60):.2f}) × 2π × 60 / 60 = {w25:.1f} W

　② ERG 300 W → duty
　　需要的淨扭力 = 300 / 6.2832 − {tare(60):.4f} = {need:.3f} N·m
　　duty = ({P[0]} − √({P[0]}² − 4 × {P[1]} × {need:.3f})) / (2 × {P[1]}) + {P[2]} = {dE:.2f}　→ MODE_DUTY {round(dE * 10)}

　③ KP 5.2 → duty
　　需要的淨扭力 = 5.2 × 9.8 = 50.96 N·m　→ duty = {duty_from(50.96, 60):.2f}　→ MODE_DUTY {round(duty_from(50.96, 60) * 10)}
""", MONO)

# ==================== 2 參數表 ====================
s = Sheet('2_參數表', (6, 16, 46, 13, 13, 13))
s.title('2　參數表')
s.lines("""
　參數 0～5 就是目前韌體裡寫死的常數（第五版），只是改成可寫入的變數，預設值換成第六版。6～9 是新增（黃底）。
　數值格式：float32（IEEE 754，little-endian）。寫入超出範圍 → ACK_PARAM_ERROR，不寫入。
""")
NAMES = ['a', 'b', 'x0', 'c0', 'tare 常數', 'tare 斜率', '扭力倍率', '空載補正 N·m', '磁滯歸零時間 s', '磁滯補償開關']
NOTE = ['煞車強度', '飽和彎曲', '起始 duty；也用於觸底判斷', '轉速影響；轉速係數前係數 (c0+60)/60 由此計算，不另外存',
        '空載基本值', '空載隨踏頻增加', '每台出廠校正的細調（VR1 粗調後）', '預留，目前 0', 'duty 0 維持超過此秒數清除最高 duty', '0 關 / 1 開']
RNG = ['1.0～4.0', '0～0.03', '0～10', '1～50', '0～6', '0～0.05', '0.80～1.20', '−3～+3', '0.5～30', '0 或 1']
s.table(['編號', '名稱', '說明', '目前韌體（第五版）', '第六版預設', '允許範圍'],
        [(i, NAMES[i], NOTE[i], V5[i] if i < 6 else '（新增）', P[i], RNG[i]) for i in range(10)], fill_rows=range(6, 10))
s.r += 1
s.lines("""
　· 寫入後立即生效（RAM）；送 SAVE_PARAMS 才寫進 flash，下次開機保留。
　· 開機讀 flash：資料損壞（建議存檔時附 CRC 檢查）就使用第六版預設值。
　· 寫入只允許在 STOP 狀態（避免騎乘中阻力突變）。
""")

# ==================== 3 新增指令 ====================
s = Sheet('3_新增指令', (22, 26, 52, 12, 75))
s.title('3　新增指令（格式與原協定相同：55 AA LEN CMD DATA CRC_L CRC_H 0D）')
s.lines("""
　指令碼不與原協定衝突（原協定只用 0x01、02、03、06、10、20、21、40、80、81、F0、F1）。
　回應沿用原協定的分法：下控 → 上控的回應用 0x8x；只需確認成功與否的用原本的 ACK（F0 + 被回應的 CMD + 結果）。
""")
s.h('一、指令一覽')
s.table(['指令（上控 → 下控）', 'DATA', '下控回應', '限制'], [
    ('0x30 SET_PARAM', '編號(1) + 數值 float32(4)', 'ACK：OK / PARAM_ERROR / INVALID_STATE', '只在 STOP'),
    ('0x31 GET_PARAM', '編號(1)', '0x82 PARAM_VALUE：編號(1) + 數值(4)；編號錯回 ACK PARAM_ERROR', '隨時'),
    ('0x32 SAVE_PARAMS', '無', '寫完 flash 後回 ACK OK', '只在 STOP'),
    ('0x33 LOAD_DEFAULTS', '無', 'ACK OK（恢復第六版預設到 RAM，不自動存檔）', '只在 STOP'),
    ('0x34 SET_HYST_ROW', '行號(1) + 9 × int16(18)', 'ACK：OK / PARAM_ERROR / INVALID_STATE', '只在 STOP'),
    ('0x35 GET_HYST_ROW', '行號(1)', '0x83 HYST_ROW：行號(1) + 9 × int16(18)', '隨時'),
    ('0x36 GET_PARAM_CRC', '無', '0x84 PARAM_CRC：CRC16(2，低位元組在前)', '隨時'),
])
s.lines("""
　· 舊韌體收到新指令會回 ACK_UNKNOWN_CMD（原協定已有），上控據此判斷下控是否支援。
　· 參數 CRC：參數 0～9（float32 LE，依編號）接著磁滯表 5 行 × 9 格（int16 LE，逐行），共 130 byte，
　　用與封包相同的 CRC16/CCITT-FALSE 計算。上控用它確認下控內的參數是不是預期的版本。
""")
s.h('二、STATUS_REPORT 的 status 欄位')
s.table(['bit', '名稱', '意義', '狀態'], [
    ('0x01', 'STATUS_READY', '（原有）', '不變'),
    ('0x02', 'STATUS_RUNNING', '（原有）', '不變'),
    ('0x04', 'STATUS_TARGET_REACHED', '（原有）', '不變'),
    ('0x08', 'STATUS_ERG_LIMIT', 'duty 100 仍達不到目標', '原有；請 KP 模式也使用'),
    ('0x10', 'STATUS_BOTTOM', '目標低於空載阻力，已輸出 duty 0', '新增'),
    ('0x20', 'STATUS_HYST_COMP', '目前輸出有套用磁滯補償', '新增'),
], fill_rows=(4, 5))
s.lines('　如 0x10、0x20 貴司已有其他用途，請指定其他未用的 bit。')
s.h('三、逐 byte 封包範例（CRC 已實際計算）')
s.lines("""
　LEN = CMD + DATA 的 byte 數；CRC16/CCITT-FALSE（init 0xFFFF、poly 0x1021）涵蓋 LEN + CMD + DATA，低位元組在前；數值 little-endian。
""")
s.table(['範例', '方向', 'CMD', 'LEN', '完整封包（hex）'], pe.rows())
s.h('四、格式核對：用同一個程式重算原協定附錄 A 的範例，全部一致')
s.table(['原協定範例', '一致'], [(n, '✔' if ok else '✘') for n, ok in pe.verify_vendor()])

# ==================== 4 磁滯補償 ====================
s = Sheet('4_磁滯補償', (24,) + (9,) * 9)
s.title('4　磁滯補償')
s.h('現象')
s.lines("""
　從高 duty 往下調時，同一個 duty 的實際扭力比往上調時高。偏高多少取決於「之前到過的最高 duty」與「目前 duty」。
　例：曾到 duty 60，降回 30 → 實際扭力高約 9.5%；降到 10 → 高約 24%。duty 歸零一段時間後恢復正常。
""")
s.h('作法（3 個步驟）')
s.lines("""
　1. 記錄最高 duty：每次輸出 duty 後，若 duty > 最高 duty 就更新；duty 0 維持超過參數 8（預設 2 秒）就清為 0。
　2. 查偏高量 h：目前 duty < 最高 duty 時，用下表查出 h（兩個方向線性內插）；其他情況 h = 0。
　3. 修正：
　　· 換算 duty：先照常反解出 duty，查 h，再用「需要的淨扭力 ÷ (1 + h)」重新反解一次（只需一次）。
　　· est_watt：淨扭力 × (1 + h)。
　　· 套用時 status 設 0x20。參數 9 = 0 時整個關閉。
""")
s.h('補償表（單位 0.1%；240 = 24.0%）')
s.table(['最高 duty＼目前 duty'] + [str(d) for d in range(10, 100, 10)],
        [[f'{20 * (i + 1)}（第 {i} 行）'] + r for i, r in enumerate(pe.HYST)])
s.lines("""
　來源：新車台 2026-11-15～16 實測（最高 60 = 30、90 踏頻平均；最高 40 = 120 踏頻）。
　最高 20、80、100 三行先填 0（= 不補償），我方補測後用 0x34 寫入，不需改韌體。
""")
s.h('查表例子')
s.lines("""
　· 最高 60、目前 30：第 2 行、duty 30 那格 = 95 → h = 9.5%
　· 最高 60、目前 25：duty 20（149）與 30（95）中間 → 122 → h = 12.2%
　· 最高 50、目前 30：第 1 行（8）與第 2 行（95）中間 → 51.5 → h = 5.15%
　· 目前 ≥ 最高：h = 0
""", MONO)

# ==================== 5 參考程式 ====================
s = Sheet('5_參考程式', (130,))
s.title('5　參考程式（計算部分，C）')
s.lines("""
　· 不含 UART 收發與 flash 驅動，請接到貴司現有的架構。
　· 已用 avr-gcc（-std=c99 -Wall -Wextra）編譯，無警告；並用逐行對應的測試程式驗證：
　　第六版數值、ERG / KP 往返、倍率校正一次收斂、磁滯查表與清除、旗標、參數範圍檢查，全部通過。
　· 數值精度：MODE_DUTY 解析度 0.1%，在 60 踏頻約等於 ±0.24 N·m（±0.5%），屬正常。
""")
s.r += 1
for ln in open(os.path.join(HERE, 'ems_model_ref.c'), encoding='utf-8').read().split('\n'):
    s.line(ln, MONO)

# ==================== 6 出廠校正流程 ====================
s = Sheet('6_出廠校正流程', (14, 36, 30, 40))
s.title('6　出廠校正流程（由 TFT 上控執行；供貴司了解指令使用時機）')
s.lines("""
　VR1 是硬體 PWM 調整，決定線圈實際能出多少力，所以仍需粗調；倍率只修正計算，不會讓線圈變強。
　分工：VR1 粗調到 ±5%（確保 duty 100 的能力足夠、倍率落在 0.95～1.05），倍率細調到 ±1%。
　冷機、功率機定轉速 60 rpm；操作員把功率機扭力讀數（N·m）輸入 TFT，TFT 自動計算並寫入。
""")
s.table(['步驟', 'TFT 上控送出', '操作員', '判定'], [
    ('0 前置', 'GET_VERSION、GET_PARAM_CRC、GET_PARAM 6（舊倍率）', '確認冷機', '踏頻 60 ±1、VIN ≥ 23 V'),
    ('0A VR1 粗調（新機 / 換板時）', 'STOP → SET_PARAM 6 = 1.000（不存檔）→ START → KP 5.2 持續', '轉 VR1，看功率機', '淨扭力 48.4～53.5 N·m（50.96 ±5%）；調完 KP 0 休息 10 分鐘'),
    ('1 空載', 'SET_CONTROL KP 0', '輸入空載讀數', '2.0～3.5 N·m；超出提示檢查鏈條，可繼續'),
    ('2 量測 ×3', 'KP 5.2（30 秒）→ KP 0（60 秒）', '輸入讀數', '3 次差 ≤ 0.5 N·m'),
    ('3 寫入', 'STOP → SET_PARAM 6 → GET_PARAM 6 比對 → SAVE_PARAMS → START', '確認', '新倍率 = 舊倍率 × 平均淨扭力 ÷ 50.96'),
    ('4 驗證', 'KP 5.2、KP 9.6、ERG 300 W', '輸入讀數', '±1% / ±2% / ±5%'),
])
s.lines("""
　例：某台 KP 5.2 實測淨扭力 52.5 N·m，舊倍率 1.000 → 新倍率 = 1.000 × 52.5 / 50.96 = 1.030。
　寫入後同樣 KP 5.2，下控會輸出較低的 duty，實際扭力回到 50.96 N·m；est_watt 也同時變準。
""")

# ==================== 7 請貴司回覆 ====================
s = Sheet('7_請貴司回覆')
s.title('7　請貴司回覆')
s.lines("""
　1. VR1（硬體 PWM 調整）：
　　 a. VR1 每轉一圈，PWM 約變化多少 %？
　　 b. 調 VR1 是讓整條扭力曲線按比例變化，還是起始點（x0）也會移動？（若會移動，只靠倍率修不準）
　　 c. 量產建議用多圈式 VR，或固定電阻 + 小範圍 VR，讓粗調容易落在 ±5%？
　2. 參數存 flash 是否可行？可寫入次數？
　3. 指令碼 0x30～0x36、回應 0x82～0x84、status bit 0x10 / 0x20 是否可用？如需調整請告知。
　4. 磁滯補償的實作方式是否有疑問？驅動是單端還是 H 橋？能否快速洩放線圈電流？
　5. 下控是否量測線圈或煞車溫度？
　6. 預估完成時間？
""")

wb.save(OUT)
print('輸出', OUT)
