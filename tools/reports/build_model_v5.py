#!/usr/bin/env python3
"""
建置「EMS Bike 下控扭力模型 第五版」xlsx（給下控廠商）

用法：
    python tools/reports/build_model_v5.py [輸出.xlsx]

資料：tools/reports/data/model_v5_plateaus.csv
      （tools/align_dyno.py --out 的平台表合併而成；新板、10/27 校正後同一顆 VR1）
擬合：只用「從 0 往上調」的平台（kind = asc），排除 excluded 欄有原因的執行。
"""
import csv, math, os, sys
from collections import defaultdict
from datetime import date
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data', 'model_v5_plateaus.csv')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    f'~/Downloads/EMS Bike 下控扭力模型_第五版_{date.today():%Y%m%d}.xlsx')

RATIO = 15.0119      # 52/16 × 97/21
KP_NM = 9.8          # 1 kp = 9.8 N·m 淨扭力
CAL_NM = 90.0        # 校正標準：60 踏頻 duty 50 淨扭力
V3 = dict(a=2.232021, b=0.00656259, x0=1.54, c0=8.50, t0=2.33715, t1=0.0066425, kp=9.364661, ratio=15.1)

# ==================== 擬合 ====================
rows = list(csv.DictReader(open(DATA, encoding='utf-8-sig')))
use = [r for r in rows if not r['excluded'] and r['ok'] == '✔']
asc = [r for r in use if r['kind'] == 'asc']
duty = np.array([float(r['duty']) for r in asc])
cad = np.array([float(r['rpm']) for r in asc])
net = np.array([float(r['net']) for r in asc])

def net_model(p, d, c):
    a, b, x0, c0 = p
    u = np.clip(np.asarray(d, float) - x0, 0, None)
    return (a * u - b * u * u) * (c / (c0 + c)) * ((c0 + 60) / 60)

def lm(f, x0, iters=300):
    """Levenberg-Marquardt（不依賴 scipy）"""
    x = np.array(x0, float); lam = 1e-3; r = f(x); cost = r @ r
    for _ in range(iters):
        J = np.empty((len(r), len(x)))
        for j in range(len(x)):
            h = 1e-6 * max(abs(x[j]), 1e-3); xp = x.copy(); xp[j] += h
            J[:, j] = (f(xp) - r) / h
        A = J.T @ J; g = J.T @ r
        while True:
            step = np.linalg.solve(A + lam * np.diag(np.diag(A)), -g)
            xn = x + step; rn = f(xn); cn = rn @ rn
            if cn < cost: x, r, cost, lam = xn, rn, cn, lam / 3; break
            lam *= 4
            if lam > 1e10: break
        if np.max(np.abs(step)) < 1e-11 or lam > 1e10: break
    return x

P = lm(lambda p: net_model(p, duty, cad) / net - 1, (V3['a'], V3['b'], V3['x0'], V3['c0']))
A_, B_, X0, C0 = P
KS = (C0 + 60) / 60
resid = (net / net_model(P, duty, cad) - 1) * 100

idle = [r for r in use if r['kind'] == 'idle' and float(r['rpm']) > 25]
tc = np.array([float(r['rpm']) for r in idle]); tq = np.array([float(r['torque']) for r in idle])
T1, T0 = np.polyfit(tc, tq, 1)
TARE_SD = float(np.std(tq - (T0 + T1 * tc)))

def speed(c): return KS * c / (C0 + c)
def net_at(d, c): return float(net_model(P, d, c))
def tare(c): return T0 + T1 * c
def power(d, c): return (net_at(d, c) + tare(c)) * 2 * math.pi * c / 60

def duty_for_net(need, c):
    """反解：淨扭力 → duty；回傳 (duty, 狀態)"""
    if need <= 0: return 0.0, '觸底'
    X = need / speed(c)
    disc = A_ * A_ - 4 * B_ * X
    if disc < 0: return 100.0, '超出'
    d = (A_ - math.sqrt(disc)) / (2 * B_) + X0
    if d < X0: return 0.0, '觸底'
    if d > 100: return 100.0, '超出'
    return d, ''

# v3 參照（廠商手上的版本）
def v3_net(d, c):
    u = max(d - V3['x0'], 0)
    return (V3['a'] * u - V3['b'] * u * u) * 1.14167 * c / (V3['c0'] + c)

# ==================== 版面工具 ====================
F = '微軟正黑體'
TITLE = Font(name=F, size=14, bold=True, color='123C6B')
H2 = Font(name=F, size=12, bold=True, color='123C6B')
BODY = Font(name=F, size=11)
BOLD = Font(name=F, size=11, bold=True)
RED = Font(name=F, size=11, bold=True, color='C0392B')
MONO = Font(name='Consolas', size=10.5)
HEAD_FILL = PatternFill('solid', fgColor='E8EEF6')
WARN_FILL = PatternFill('solid', fgColor='FFF8E1')
thin = Side(style='thin', color='9FB3CC')
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)

wb = Workbook(); wb.remove(wb.active)

class Sheet:
    def __init__(self, name, widths=(110,)):
        self.ws = wb.create_sheet(name); self.r = 1
        for i, w in enumerate(widths):
            self.ws.column_dimensions[chr(65 + i)].width = w
    def line(self, text='', font=BODY, fill=None):
        c = self.ws.cell(self.r, 1, text); c.font = font
        if fill: c.fill = fill
        self.r += 1
    def title(self, t): self.line(t, TITLE)
    def h(self, t): self.r += 1 if self.r > 2 else 0; self.line(t, H2)
    def lines(self, txt, font=BODY, fill=None):
        for t in txt.strip('\n').split('\n'): self.line(t, font, fill)
    def table(self, head, data, col=1, fmt=None):
        for j, v in enumerate(head):
            c = self.ws.cell(self.r, col + j, v); c.font = BOLD; c.fill = HEAD_FILL; c.border = BOX
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        self.r += 1
        for row in data:
            for j, v in enumerate(row):
                c = self.ws.cell(self.r, col + j, v); c.font = BODY; c.border = BOX
                c.alignment = Alignment(horizontal='center')
                if fmt and j < len(fmt) and fmt[j] and isinstance(v, (int, float)): c.number_format = fmt[j]
            self.r += 1

CADS = [30, 40, 50, 60, 70, 80, 90, 100, 110, 120]
GRID_W = (12,) + (11,) * 11 + (24,)

# ==================== 0 名詞與單位 ====================
s = Sheet('0_名詞與單位')
s.title('0　名詞與單位　——　請先確認這一頁')
s.lines(f"""
第五版　{date.today():%Y-%m-%d}。本版取代第三版（2026-10-02）。第四版為內部版本，未發行；其修改一併併入本版。
相對第三版的全部差異見 9_版本差異。請以本版為準，第三版作廢。
2026-11-13 修訂：只改寫校正標準的說法（「空載讀數 + 90 N·m」），參數、數值、程序都沒有變。
""")
s.line('★ 最容易出錯的一點：本文件所有式子用的是「踏頻」，不是貴司回報的「飛輪 RPM」', RED)
s.lines(f"""
　　踏頻(rpm) = 飛輪 RPM / {RATIO}
　　STATUS_REPORT 的 rpm 欄位是飛輪轉速，必須先除以 {RATIO} 才能代入本文件的式子。
　　速比由齒數決定：曲柄端 52T/16T、皮帶端 97T/21T，52/16 × 97/21 = 1261/84 = 15.011905。
""")
s.table(['踏頻', '飛輪 RPM'], [(c, round(c * RATIO)) for c in CADS])
s.h('其他名詞')
s.table(['名詞', '單位', '說明'], [
    ('duty', '0～100', '協定 MODE_DUTY 的值 ÷ 10。MODE_DUTY 500 = duty 50.0'),
    ('淨扭力', 'N·m', 'EMS 線圈產生的煞車扭力，不含機械阻力'),
    ('tare', 'N·m', 'EMS 關閉（duty 0）時的機械阻力：軸承＋皮帶＋風阻'),
    ('總扭力', 'N·m', '淨扭力 + tare。功率機量到的、騎士實際感受到的'),
    ('kp', 'kilopond', f'1 kp = {KP_NM:.4f} N·m 的「淨扭力」（不含 tare）'),
    ('ERG 目標 W', 'W', '騎士輸出的「總功率」（含 tare）'),
    ('est_watt', 'W', '貴司回報的功率 = 總扭力 × 2π × 踏頻 / 60'),
])
s.ws.column_dimensions['B'].width = 12; s.ws.column_dimensions['C'].width = 70
s.r += 1
s.line('★ 第二個容易出錯的點：KP 不含 tare，ERG 含 tare', RED)
s.lines("""
　　KP　：目標是煞車扭力本身 → 直接用 kp × 9.8 當「淨扭力」，不要加 tare
　　ERG：目標是騎士輸出的功率 → 先換成總扭力，再扣掉 tare 才得到「淨扭力」
""")

# ==================== 1 模型 ====================
s = Sheet('1_模型')
s.title('1　模型（第五版）')
s.h('正向：duty → 功率')
s.lines(f"""
　踏頻　　　　　 = 飛輪RPM / {RATIO}
　u　　　　　　　= duty − {X0:.4f}　　（u ≤ 0 時淨扭力為 0）
　淨扭力@60踏頻 = {A_:.6f} × u − {B_:.8f} × u²
　轉速係數　　　 = {KS:.6f} × 踏頻 / ({C0:.4f} + 踏頻)　　（60 踏頻時 = 1.000）
　淨扭力　　　　 = 淨扭力@60踏頻 × 轉速係數
　tare　　　　　 = {T0:.4f} + {T1:.6f} × 踏頻
　總扭力　　　　 = 淨扭力 + tare
　功率(W)　　　　= 總扭力 × 2π × 踏頻 / 60　　（= est_watt）
""", MONO)
s.h('反向：要的淨扭力 → duty（閉式，KP 與 ERG 共用）')
s.lines(f"""
　X　　= 目標淨扭力 / 轉速係數
　disc = {A_:.6f}² − 4 × {B_:.8f} × X
　duty = ( {A_:.6f} − √disc ) / ( 2 × {B_:.8f} ) + {X0:.4f}

　disc < 0　　　　 → 目標超出機器能力，夾到 duty 100 並回報
　duty < {X0:.4f}　 → 目標低於導通門檻，夾到 duty 0 並回報已觸底
　duty > 100　　　 → 夾到 duty 100 並回報
""", MONO)
s.h('轉速係數與 duty 100 能力（供快速核對）')
s.table(['踏頻', '飛輪RPM', '轉速係數', 'duty 100 淨扭力 N·m', 'duty 100 = kp', 'duty 0 功率 W', 'duty 100 功率 W'],
        [(c, round(c * RATIO), round(speed(c), 4), round(net_at(100, c), 1), round(net_at(100, c) / KP_NM, 2),
          round(power(0, c), 1), round(power(100, c))) for c in CADS])
s.r += 1
s.lines(f"""
　驗證範圍：踏頻 30～120、duty 10～100（120 踏頻驗證到 duty 50）。範圍外為外推。
　適用條件：從較低 duty 往上調整（或從 0 開始）。往下調整有磁滯，見 7_磁滯與歸零。
""")
for col, w in zip('ABCDEFG', (110, 10, 10, 18, 14, 14, 15)): s.ws.column_dimensions[col].width = w

# ==================== 2 ERG 實作說明 ====================
s = Sheet('2_ERG實作說明')
FR, TW = 1208, 250
c = FR / RATIO; w = 2 * math.pi * c / 60; tot = TW / w; ta = tare(c); nn = tot - ta
sf = speed(c); X = nn / sf; disc = A_ * A_ - 4 * B_ * X; dd = (A_ - math.sqrt(disc)) / (2 * B_) + X0
s.title('2　ERG 模式　逐步計算範例')
s.line(f'　以「飛輪 RPM = {FR}、ERG 目標 {TW} W」為例，每一步都列出數字。')
s.lines(f"""
　①　把飛輪 RPM 換成踏頻　　　踏頻 = {FR} / {RATIO} = {c:.4f}
　②　算角速度 ω　　　　　　　 ω = 2π × {c:.4f} / 60 = {w:.5f} rad/s
　③　目標功率換成總扭力　　　 總扭力 = {TW} / {w:.5f} = {tot:.4f} N·m
　④　算這個踏頻的 tare　　　　tare = {T0:.4f} + {T1:.6f} × {c:.4f} = {ta:.4f} N·m
　⑤　扣掉 tare 得到淨扭力　　 淨扭力 = {tot:.4f} − {ta:.4f} = {nn:.4f} N·m
　⑥　算轉速係數　　　　　　　 轉速係數 = {KS:.6f} × {c:.4f} / ({C0:.4f} + {c:.4f}) = {sf:.5f}
　⑦　除掉轉速影響　　　　　　 X = {nn:.4f} / {sf:.5f} = {X:.4f}
　⑧　代入反解式　　　　　　　 disc = {A_:.6f}² − 4 × {B_:.8f} × {X:.4f} = {disc:.5f}
　　　　　　　　　　　　　　　 duty = ({A_:.6f} − {math.sqrt(disc):.5f}) / (2 × {B_:.8f}) + {X0:.4f} = {dd:.4f}
　⑨　轉成協定值　　　　　　　 MODE_DUTY = round({dd:.4f} × 10) = {round(dd * 10)}
""", MONO)
s.h('驗算（把 duty 代回正向式，應該回到目標功率）')
s.line(f'　功率 = ({net_at(dd, c):.4f} + {ta:.4f}) × {w:.5f} = {power(dd, c):.2f} W　　✔', MONO)
s.h('虛擬碼')
s.lines(f"""
uint16_t net_to_duty(float need_net, float cad)          /* 回傳 MODE_DUTY（0.1%） */
{{
    if (need_net <= 0.0f) {{ set_bottomed_flag(); return 0; }}
    float sf   = {KS:.6f}f * cad / ({C0:.4f}f + cad);
    float X    = need_net / sf;
    float disc = {A_:.6f}f * {A_:.6f}f - 4.0f * {B_:.8f}f * X;
    if (disc < 0.0f) {{ set_over_flag(); return 1000; }}
    float duty = ({A_:.6f}f - sqrtf(disc)) / (2.0f * {B_:.8f}f) + {X0:.4f}f;
    if (duty < {X0:.4f}f) {{ set_bottomed_flag(); return 0; }}
    if (duty > 100.0f)  {{ set_over_flag(); duty = 100.0f; }}
    return (uint16_t)(duty * 10.0f + 0.5f);
}}

uint16_t erg_to_duty(uint16_t target_w, uint16_t flywheel_rpm)
{{
    float cad = flywheel_rpm / {RATIO}f;
    if (cad < 1.0f) return 0;                                 /* 還沒轉起來 */
    float w    = 2.0f * 3.14159265f * cad / 60.0f;
    float tare = {T0:.4f}f + {T1:.6f}f * cad;
    return net_to_duty((float)target_w / w - tare, cad);      /* ERG：扣 tare */
}}

uint16_t kp_to_duty(uint16_t mode_kp, uint16_t flywheel_rpm)  /* MODE_KP：0.1 kp */
{{
    float cad = flywheel_rpm / {RATIO}f;
    if (cad < 1.0f) return 0;
    return net_to_duty(mode_kp * 0.1f * {KP_NM:.1f}f, cad);   /* KP：不扣 tare */
}}

uint16_t est_watt(uint16_t mode_duty, uint16_t flywheel_rpm)
{{
    float cad = flywheel_rpm / {RATIO}f;
    float u   = mode_duty * 0.1f - {X0:.4f}f;
    float n60 = (u > 0.0f) ? ({A_:.6f}f * u - {B_:.8f}f * u * u) : 0.0f;
    float tot = n60 * {KS:.6f}f * cad / ({C0:.4f}f + cad) + {T0:.4f}f + {T1:.6f}f * cad;
    return (uint16_t)(tot * 2.0f * 3.14159265f * cad / 60.0f + 0.5f);
}}
""", MONO)

# ==================== 3 ERG 對照表 ====================
s = Sheet('3_ERG對照表', GRID_W)
s.title('3　ERG 對照表（供核對實作結果）')
s.lines("""
　表內數值是 MODE_DUTY（0～1000，0.1% 為單位）。例如 137 代表 duty 13.7%。
　「目標 W」是騎士輸出的總功率（含機械阻力）。觸底 = 低於純機械阻力；超出 = 高於 duty 100 的能力。
""")
grid = []
for tw in (30, 40, 50, 60, 80, 100, 125, 150, 175, 200, 250, 300, 400, 500, 600, 800, 1000, 1200):
    row = [tw]
    for c in CADS:
        d, st = duty_for_net(tw / (2 * math.pi * c / 60) - tare(c), c)
        row.append(st or round(d * 10))
    grid.append(row)
s.table(['目標 W'] + [f'踏頻 {c}' for c in CADS], grid)
s.r += 1
s.table(['飛輪RPM'] + [round(c * RATIO) for c in CADS], [])

# ==================== 4 KP 對照表 ====================
s = Sheet('4_KP對照表', GRID_W)
s.title('4　KP 對照表（供核對實作結果）')
s.line(f'　1 kp = {KP_NM} N·m 的淨扭力（不含 tare）。表內數值是 MODE_DUTY（0～1000）。')
grid = []
for k10 in range(5, 145, 5):
    row = [k10, k10 / 10, round(k10 / 10 * KP_NM, 1)]
    for c in CADS:
        d, st = duty_for_net(k10 / 10 * KP_NM, c)
        row.append(st or round(d * 10))
    grid.append(row)
s.table(['MODE_KP', 'kp', '淨扭力 N·m'] + [f'踏頻 {c}' for c in CADS], grid)
s.r += 1
lim = [c for c in range(20, 61) if duty_for_net(14 * KP_NM, c)[1] == '']
s.lines(f"""
　duty 100 在 60 踏頻可達 {net_at(100, 60) / KP_NM:.2f} kp。
　14.0 kp 的最低可行踏頻約 {lim[0] if lim else '>60'}；低於此踏頻請夾到 duty 100 並以狀態旗標回報（與 ERG 觸底共用同一機制）。
""")

# ==================== 5 驗證資料 ====================
s = Sheet('5_驗證資料', (14, 10, 9, 12, 12, 12, 10, 12))
s.title('5　擬合資料與殘差')
s.lines(f"""
　資料：新板，2026-10-27 校正後 VR1 未再調整；功率機 C271，定轉速。每個平台丟掉前 12 秒，取其後平均。
　只用「從 0 往上調」的平台（往下調有磁滯，另列 7_磁滯與歸零）。淨扭力 = 功率機扭力 − 同一輪 duty 0 的 tare。
　點數 {len(asc)}；RMS {math.sqrt(np.mean(resid ** 2)):.2f}%；最大 {np.max(np.abs(resid)):.2f}%。
　殘差 = 實測 / 模型 − 1。同一條件不同天重複量測的離散約 σ 1%，模型無法比這更準。
""")
s.h('各轉速 × duty 平均殘差（%）')
mat = []
for cc in (30, 60, 90, 120):
    row = [cc]
    for d in range(10, 101, 10):
        m = [resid[i] for i in range(len(asc)) if duty[i] == d and abs(cad[i] - cc) < 5]
        row.append(round(float(np.mean(m)), 1) if m else '')
    mat.append(row)
s.table(['踏頻＼duty'] + list(range(10, 101, 10)), mat)
s.h('全部擬合點')
s.table(['日期', '執行', '踏頻', 'duty %', '淨扭力 實測', '模型', '殘差 %', '電流 mA'],
        [(r['date'], r['run'][5:], round(float(r['rpm']), 1), int(r['duty']), round(float(r['net']), 2),
          round(net_at(float(r['duty']), float(r['rpm'])), 2), round(float(resid[i]), 2), round(float(r['current_ma'])))
         for i, r in enumerate(asc)])
s.h('排除的資料')
ex = sorted({(r['run'], r['excluded']) for r in rows if r['excluded']})
s.table(['執行', '原因'], ex)

# ==================== 6 校正程序 ====================
s = Sheet('6_校正程序', (110, 12, 12, 12, 12, 12))
s.title('6　校正程序（取代原「duty 100 = 1000 W」）')
s.line(f'★ 新標準：60 踏頻、duty 50，功率機扭力讀數 = 當下空載（duty 0）讀數 + {CAL_NM:.1f} N·m，容許 ±{CAL_NM*0.01:.1f} N·m', RED)
s.line(f'　 注意：{CAL_NM:.0f} 不是功率機螢幕上的讀數。例：空載 3.3 N·m → duty 50 要看到 {CAL_NM+3.3:.1f} N·m（{CAL_NM*0.99+3.3:.1f}～{CAL_NM*1.01+3.3:.1f}）；空載 4.0 → {CAL_NM+4.0:.1f} N·m。', RED)
s.line(f'　 也就是淨扭力（扣掉空載後）= {CAL_NM:.1f} N·m ±1%（{CAL_NM*0.99:.1f}～{CAL_NM*1.01:.1f} N·m），換成功率是「空載功率 + 約 565 W」。')
s.h('步驟')
s.lines(f"""
　1. 機器停機休息 30 分鐘以上（冷機）。不可在剛做完高負荷或反覆調整之後量。
　2. 功率機定轉速 60 rpm，duty 0 空轉 60 秒以上，記下扭力 = tare。
　3. duty 0 → 50（直接從 0 上去，不可從高往下降），停 30 秒，取後 15 秒平均扭力。
　4. 回到 duty 0 停 60 秒，記下 tare。
　5. 第 3～4 步共做 3 次。
　6. 淨扭力 = 每次 duty 50 扭力 − 前後 duty 0（空載）扭力的平均；3 次取平均，判定是否在 {CAL_NM*0.99:.1f}～{CAL_NM*1.01:.1f} N·m。
　7. 不合格時：回到 duty 0 再調 VR1，然後休息 10 分鐘，從第 2 步重做。
""")
s.h('為什麼用「淨扭力」而不是總功率')
s.lines("""
　· VR1 調的是線圈電流，電流直接決定煞車扭力；功率是扭力 × 轉速，多受轉速誤差影響（差 1 rpm 就差 1.7%）。
　· 功率機的空轉阻力每天不同（下表 2.2～3.8 N·m，相當 14～24 W），總功率因此變動 ±1%，淨扭力不受影響。
　· 每做一次 0→50，讀數會比前一次高約 0.5%；反覆調整後量到的值會偏高 2% 以上（2026-10-27 即是如此）。
　　因此固定「冷機、3 次平均」。
""")
s.h('我方實測（同一塊板，VR1 未動）')
cal = [('2026-10-29', 'CMP1 duty 50（單次）', 3.8, 90.07), ('2026-11-03', 'CAL50 第一輪', 3.0, 90.05),
       ('2026-11-03', 'CAL50 第二輪', 3.1, 89.51), ('2026-11-04', 'CAL50', 2.2, 89.89)]
s.table(['日期', '項目', 'tare N·m', '淨扭力 N·m', '對 90.0'],
        [(d_, it, t_, n_, f'{(n_ / CAL_NM - 1) * 100:+.1f}%') for d_, it, t_, n_ in cal])
s.r += 1
s.line(f'　模型在此點的值：{net_at(50, 60):.2f} N·m（{(net_at(50, 60) / CAL_NM - 1) * 100:+.1f}%，在模型精度內）。')
for col, w in zip('ABCDE', (14, 26, 12, 12, 10)): s.ws.column_dimensions[col].width = w
s.h('驗收標準（出貨檢驗、實驗室驗證）：看瓦數')
s.lines("""
　est_watt（機器顯示）對功率機實測的總功率：誤差 ±5%；實測 100 W 以下改用 ±5 W（取兩者較寬者）。
　條件：從 duty 0 往上調到測試點（或歸零後再上），停 30 秒後取後 15 秒平均；冷機；踏頻 30～120。
　往下調整的點要等磁滯補償（7_磁滯與歸零）實作後才適用本標準。
""")
pw_meas = np.array([float(r['power']) for r in asc])
pw_mod = np.array([power(float(r['duty']), float(r['rpm'])) for r in asc])
err_w = pw_mod - pw_meas; err_p = err_w / pw_meas * 100
ok = [(abs(err_p[i]) <= 5) or (pw_meas[i] < 100 and abs(err_w[i]) <= 5) for i in range(len(asc))]
s.line(f'　第五版套用全部 {len(asc)} 個上升平台：功率誤差 RMS {math.sqrt(np.mean(err_p ** 2)):.1f}%，'
       f'合格 {sum(ok)} / {len(asc)}。', BOLD)
bad = [i for i in range(len(asc)) if not ok[i]]
if bad:
    s.table(['不合格點', '踏頻', 'duty', '實測 W', '顯示 W', '誤差'],
            [(asc[i]['run'][5:], round(cad[i]), int(duty[i]), round(pw_meas[i], 1), round(pw_mod[i], 1),
              f'{err_p[i]:+.1f}%（{err_w[i]:+.1f} W）') for i in bad])


# ==================== 7 磁滯與歸零 ====================
s = Sheet('7_磁滯與歸零', (16,) + (9,) * 10)
s.title('7　磁滯：往下調整時扭力偏高')
s.lines("""
　模型適用於「從較低 duty 往上調」。從高 duty 往下調時，實際扭力會比模型高，偏高量主要取決於
　「先前到過的最高 duty」與「目前 duty」，與踏頻幾乎無關（30 / 60 / 90 / 120 踏頻差異在 3 個百分點內）。
　下表：每 25～30 秒降 10%，實測淨扭力相對第五版模型偏高的百分比（各踏頻、各場次平均）。
""")
g = defaultdict(list)
for r in use:
    if r['kind'] != 'desc' or (r['run'].endswith('60B') and r['peak'] == '60'): continue   # 60B 的 60→30 是歸零實驗，另列
    d = int(r['duty']); g[(int(r['peak']), d)].append((float(r['net']) / net_at(d, float(r['rpm'])) - 1) * 100)
peaks = sorted({k[0] for k in g})
s.table(['最高 duty＼目前'] + list(range(10, 100, 10)),
        [[p] + [round(float(np.mean(g[(p, d)])), 1) if (p, d) in g else '' for d in range(10, 100, 10)] for p in peaks])
s.r += 1
s.lines("""
　例：曾到 duty 80，降回 50 → 實際扭力比模型高約 15%；降到 10 → 高約 41%。
""")
s.h('歸零可以消除大部分磁滯（60 → 0 短暫 → 30，60 踏頻，2026-10-29）')
dips = [r for r in use if r['run'].endswith('60B') and r['kind'] == 'desc' and r['peak'] == '60']
base30 = float(np.mean([float(r['net']) for r in use if r['run'].endswith('60B') and r['kind'] == 'asc' and r['duty'] == '30']))
dip_pct = [(float(r['net']) / base30 - 1) * 100 for r in dips]
s.table(['歸零時間', '降到 30 時偏高（相對同一輪從 0 上到 30）'],
        [(t_, f'{v:+.1f}%') for t_, v in zip(('0.5 s', '1 s', '2 s', '5 s'), dip_pct)])
s.r += 1
s.lines(f"""
　直接 60 → 30（不歸零）偏高約 {np.mean(g[(60, 30)]):.0f}%。歸零越久越接近；5 秒後只剩約 {dip_pct[-1]:.0f}%。
　線圈電流洩放慢：duty 設 0 後電流以時間常數約 0.7 秒衰減（1250 mA → 200 mA 約 1.9 秒）。
""")
s.h('建議做法（請貴司評估）')
s.lines("""
　A. 往下調整前先短暫歸零：duty → 0 維持 1～2 秒，再設新的 duty。
　　 簡單；但騎士會感到一下阻力消失。若驅動改為快速洩放（H 橋反向或主動放電），歸零可縮短到感覺不到。
　B. 查表補償：記錄「上次歸零後的最高 duty」，往下調時依上表把目標淨扭力除以 (1 + 偏高%)，再反解 duty。
　　 不影響騎乘感受；但需要韌體記錄最高點，且溫度與停留時間會造成數個百分點的殘差。
　兩者可並用。請回覆貴司傾向的方式，我方再提供對應的驗收程序。
""")

# ==================== 8 溫度與重現性 ====================
s = Sheet('8_溫度與重現性')
s.title('8　溫度、重現性與量測注意事項')
s.lines("""
　· 熱機：連續高負荷（90 踏頻、最高 duty 80，約 1300 W）之後，同樣約 1145 mA 的電流，60 踏頻 duty 50 淨扭力
　　88.5 N·m，冷機為 89.5～90.1 N·m，少約 1.5%。電流沒有變，是煞車本身發熱造成，不是 VR1 或電路漂移。
　· 120 踏頻（最高約 1200 W）之後接著量 30 踏頻，與隔天冷機重量相比少約 1%。
　· 同一平台停留時：往上調後每 10 秒約 +0.5%（磁性爬升），往下調後每 10 秒約 −0.2%。
　· 不同天、同條件重複量測的離散：σ 約 1%。
　· tare（空轉阻力）每天不同：2.2～3.8 N·m，與機器溫度、皮帶狀態有關。
""")
s.lines(f"""
　· 第五版 tare 取全部資料平均：{T0:.4f} + {T1:.6f} × 踏頻，散布 σ {TARE_SD:.2f} N·m（60 踏頻時約 ±{TARE_SD*2*math.pi:.0f} W）。
""")

# ==================== 9 版本差異 ====================
s = Sheet('9_版本差異', (110,))
s.title('9　版本差異（第五版相對第三版）')
s.lines(f"""
　貴司手上的是第三版（2026-10-02）。第四版為我方內部版本，未發行；以下列出第三版 → 第五版的全部差異。
""")
s.h('一、kp 換算常數')
s.lines(f"""
　第三版　1 kp = {V3['kp']} N·m　→　第五版　1 kp = {KP_NM} N·m（客戶指定，2026-10-05）。同一 kp 煞車扭力大 4.65%。
""")
s.h('二、飛輪速比')
s.lines(f"""
　第三版　踏頻 = 飛輪RPM / {V3['ratio']}　→　第五版　踏頻 = 飛輪RPM / {RATIO}（52/16 × 97/21，齒數算出的精確值）
""")
s.h('三、duty 曲線、轉速項、tare（以新板資料重新擬合）')
s.table(['參數', '第三版', '第五版'], [
    ('a（u 一次項）', V3['a'], round(A_, 6)), ('b（u 二次項）', V3['b'], round(B_, 8)),
    ('duty 偏移 x0', V3['x0'], round(X0, 4)), ('轉速飽和 c0', V3['c0'], round(C0, 4)),
    ('轉速係數前係數', 1.14167, round(KS, 6)), ('tare 常數', V3['t0'], round(T0, 4)), ('tare 斜率', V3['t1'], round(T1, 6))])
s.ws.column_dimensions['B'].width = 14; s.ws.column_dimensions['C'].width = 14
s.r += 1
s.lines('　同一 duty、同一踏頻的淨扭力，第五版相對第三版（新板、新校正點）。同樣的 KP / ERG 目標，第五版會給較高的 duty：')
s.table(['duty＼踏頻'] + [30, 60, 90, 120], [[d] + [f'{(net_at(d, c) / v3_net(d, c) - 1) * 100:+.1f}%' for c in (30, 60, 90, 120)]
                                           for d in (10, 30, 50, 70, 100)])
s.h('四、校正標準')
s.lines(f"""
　原：60 踏頻、duty 100 = 1000 W　→　新：60 踏頻、duty 50，功率機扭力讀數 = 當下空載讀數 + {CAL_NM:.1f} N·m（±1%），冷機 3 次平均（見 6_校正程序）。
""")
s.h('五、精度')
s.lines(f"""
　第五版在 {len(asc)} 個上升平台（踏頻 30～120）RMS {math.sqrt(np.mean(resid ** 2)):.1f}%、最大 {np.max(np.abs(resid)):.1f}%。
　第三版 / 第四版套用同一批資料：RMS 約 6%、最大約 18%（主要是新板與 VR1 校正點不同）。
　貴司目前 FW9.24.0 內建的仍是更早的第二版參數：60 踏頻偏低約 3%，120 踏頻偏低約 15%。請更新為第五版。
""")
s.h('六、新增')
s.lines("""
　· 6_校正程序：新校正標準與步驟
　· 7_磁滯與歸零：往下調整的偏高量表、歸零實驗、兩種補償建議
　· 8_溫度與重現性
""")

# ==================== 10 請貴司回覆 ====================
s = Sheet('10_請貴司回覆', (110,))
s.title('10　請貴司回覆')
s.lines("""
　1. 下控內部 VIN 異常：外部 24 V 穩定時，下控回報 VIN 會掉到 5～16 V，電流跳動、扭力少 15～30%；
　　 新舊兩塊板都出現過，拔插下控電源即恢復。疑似在上控斷電重開、但 UART 線仍連接時觸發。
　　 請說明 VIN 量測位置，以及輸入保護（eFuse / MOSFET）是否可能鎖在異常狀態。
　2. STATUS_REPORT 週期性中斷：約每 7 秒有一次約 1.1 秒收不到 STATUS_REPORT（每輪測試數百次；待機、騎乘、
　　 只送 HEARTBEAT 時都會；兩種上控硬體都量到，非上控接收問題）。約 0.1 秒後恢復，未觸發 3 秒逾時。
　　 影響：上控 COMM LOST 門檻因此只能設 2 秒，WINGATE 每秒統計也要處理沒有資料的秒。
　　 請確認韌體是否會週期性暫停送 STATUS（ADC、EEPROM 或其他工作），並修正為穩定 100 ms。
　3. 溫度：同樣電流下熱機扭力少約 1.5%（見 8）。下控是否量測線圈或煞車溫度？能否補償？
　4. 磁滯：見 7。驅動是單端還是 H 橋？能否快速洩放（主動放電或反向脈衝）？傾向 A 或 B 哪種補償？
　5. VR1 實際調整的是什麼？duty 是電壓 PWM 還是電流閉迴路？
　6. ERG 觸底、ERG 超出、KP 低踏頻無法達成時，希望用哪個狀態旗標或錯誤碼標示？
　7. rpm 回報的取樣視窗長度？目前量化跳動 21～24 counts（60 踏頻約 2.3%）。
　8. 兩塊板的電流讀值相差約 5%，實際扭力相同；若以電流讀值做保護門檻，請考慮板間差異。
""")

wb.save(OUT)
print('輸出', OUT)
print(f'第五版 a={A_:.6f} b={B_:.8f} x0={X0:.4f} c0={C0:.4f} Ks={KS:.6f} tare={T0:.4f}+{T1:.6f}c σ{TARE_SD:.3f}')
print(f'RMS {math.sqrt(np.mean(resid**2)):.2f}% max {np.max(np.abs(resid)):.2f}%  duty50@60 net {net_at(50,60):.2f}  ERG例 duty {dd:.3f}')
