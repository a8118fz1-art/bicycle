#!/usr/bin/env python3
"""
建置「EMS Bike 下控扭力模型 第六版」xlsx（給下控廠商）

用法：
    python tools/reports/build_model_v6.py [輸出.xlsx]

資料：tools/reports/data/model_v6_plateaus.csv
      （tools/align_dyno.py --out 的平台表合併而成；新車台 2026-11-15～16 冷機四個踏頻，下控 FW11.11.0，VR1 未動）
      11-13 同一台的初版資料見 git 歷史（commit ce665a6）。
      第五版（前一台）的資料與程式保留在 model_v5_plateaus.csv / build_model_v5.py。
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
DATA = os.path.join(HERE, 'data', 'model_v6_plateaus.csv')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    f'~/Downloads/EMS Bike 下控扭力模型_第六版_{date.today():%Y%m%d}.xlsx')

RATIO = 15.0119      # 52/16 × 97/21
KP_NM = 9.8          # 1 kp = 9.8 N·m 淨扭力
CAL_NM, CAL_TOL = 50.6, 0.5   # 基準點：60 踏頻 duty 25 淨扭力（模型值；基準機 11/14～15 CAL25 三趟平均 50.53），容許約 ±1%
CHK_NM, CHK_TOL = 93.8, 1.8   # 檢查點：60 踏頻 duty 50 淨扭力（模型值；基準機三趟 0→50 平均 94.55），容許約 ±2%
V5 = dict(a=2.176389, b=0.00657222, x0=2.3552, c0=8.6539, t0=3.0030, t1=0.004849)   # 第五版（前一台）
DIP5 = ('+12%', '+8.4%', '+5.1%', '+3.3%', '+1.5%')   # 佔位，下面由第五版資料重算

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

P = lm(lambda p: net_model(p, duty, cad) / net - 1, (V5['a'], V5['b'], V5['x0'], V5['c0']))
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

# 第五版參照（廠商 FW11.11.0 內建的版本）
P5 = (V5['a'], V5['b'], V5['x0'], V5['c0'])
def v5_arr(d, c): return net_model(P5, d, c)
def v5_net(d, c): return float(net_model(P5, d, c))

# 歸零實驗只在前一台做過：由第五版資料重算（相對同一輪從 0 上到 30）
_r5 = [r for r in csv.DictReader(open(os.path.join(HERE, 'data', 'model_v5_plateaus.csv'), encoding='utf-8-sig'))
       if not r['excluded'] and r['ok'] == '✔']
_b30 = float(np.mean([float(r['net']) for r in _r5 if r['run'].endswith('60B') and r['kind'] == 'asc' and r['duty'] == '30']))
_dip = [float(r['net']) / _b30 - 1 for r in _r5 if r['run'].endswith('60B') and r['kind'] == 'desc' and r['peak'] == '60']
_nd = [float(r['net']) / _b30 - 1 for r in _r5 if r['kind'] == 'desc' and r['peak'] == '60' and r['duty'] == '30'
       and not r['run'].endswith('60B') and abs(float(r['rpm']) - 60) < 5]
DIP5 = tuple(f'{v * 100:+.1f}%' for v in ([float(np.mean(_nd))] if _nd else [float('nan')]) + _dip)

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
第六版　{date.today():%Y-%m-%d}。本版取代第五版（2026-11-04 / 11-13）。請以本版為準，第五版作廢。
公式、協定、kp 換算、速比都沒有變；只更換模型常數與空載（tare）常數，並改訂校正點。差異見 9_版本差異。
改版原因：2026-11-13 起改用新車台（同設計的另一台，下控 FW11.11.0 = 第五版參數），實測與第五版模型差 3～19%，
　　　　　且不是單一倍率，無法用 VR1 修正，因此以新車台重新量測並擬合（2026-11-15～16，四個踏頻都在冷機下量測）。
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
s.title('1　模型（第六版）')
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
　驗證範圍：踏頻 30～120、duty 10～100（90 踏頻驗證到 duty 80、120 踏頻驗證到 duty 50）。範圍外為外推。
　依據：新車台一台（2026-11-15～16，冷機）。台間差異尚未量測，見 9_版本差異 六。
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
　資料：新車台，2026-11-15～16，下控 FW11.11.0；VR1 自 11-13 後未再調整，鏈條也未再動。
　每個踏頻一趟，每趟開始前停機 2 小時以上（冷機），開始前拔插下控電源，全程 VIN ≥ 24.2 V。
　功率機 C271，定轉速。每個平台丟掉前段，取其後平均。踏頻 30 / 60 / 90 / 120（120 踏頻實際為 119）。
　只用「從 0 往上調」的平台（往下調有磁滯，另列 7_磁滯與歸零）。淨扭力 = 功率機扭力 − 同一輪 duty 0 讀數的平均。
　點數 {len(asc)}；RMS {math.sqrt(np.mean(resid ** 2)):.2f}%；最大 {np.max(np.abs(resid)):.2f}%。
　殘差 = 實測 / 模型 − 1。
　注意：90 踏頻只量到 duty 80、120 踏頻只量到 duty 50；60 踏頻 duty 70～100 的扭力波動較大（σ 0.4～0.8 N·m）。
　注意：本版資料只有一台。台與台之間的差異尚未量測（見 9_版本差異 六）。
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
ex = sorted({(r['run'], r['excluded']) for r in rows if r['excluded']}) or [('（無）', '')]
s.table(['執行', '原因'], ex)

# ==================== 6 校正程序 ====================
s = Sheet('6_校正程序', (110, 12, 12, 12, 12, 12))
s.title('6　校正程序（第六版：基準點改到 60 踏頻 duty 25，約 300 W）')
EX = 2.4   # 範例用的空載讀數
s.line(f'★ 基準點：60 踏頻、duty 25，功率機扭力讀數 = 當下空載（duty 0）讀數 + {CAL_NM:.1f} N·m，容許 ±{CAL_TOL:.1f} N·m', RED)
s.line(f'　 注意：{CAL_NM:.1f} 不是功率機螢幕上的讀數。例：空載 {EX} N·m → duty 25 要看到 {CAL_NM+EX:.1f} N·m（{CAL_NM-CAL_TOL+EX:.1f}～{CAL_NM+CAL_TOL+EX:.1f}）；空載 3.0 → {CAL_NM+3.0:.1f} N·m。', RED)
s.line(f'　 換成功率是「空載功率 + 約 {CAL_NM*2*math.pi:.0f} W」；空載 {EX} N·m 時螢幕約 {(CAL_NM+EX)*2*math.pi:.0f} W。')
s.line(f'★ 檢查點：60 踏頻、duty 50，功率機扭力讀數 = 當下空載讀數 + {CHK_NM:.1f} N·m，容許 ±{CHK_TOL:.1f} N·m（例：空載 {EX} → {CHK_NM+EX:.1f} N·m，{CHK_NM-CHK_TOL+EX:.1f}～{CHK_NM+CHK_TOL+EX:.1f}）', RED)
s.lines(f"""
　 基準點移到 duty 25 的原因：常用功率在 100～500 W，基準點放在中間（約 300 W），常用範圍的誤差最小。
　 duty 50 保留為檢查點，用來確認曲線形狀沒有跑掉；兩點都要合格。VR1 只依基準點調整。
　 上列兩個數值是第六版模型在 60 踏頻的值；基準機（新車台，VR1 未動）三趟實測都在容許範圍內，見下方。
""")
s.h('第 0 步：先確認空載')
s.lines(f"""
　60 踏頻、duty 0 的功率機扭力讀數應在 2.0～3.5 N·m（暫定）。超出範圍先檢查鏈條、皮帶張力，不要用 VR1 去補。
　（同一台車：鏈條太緊時空載到 5.3 N·m，放鬆後 1.7～2.6 N·m。）
""")
s.h('步驟')
s.lines(f"""
　1. 機器停機休息 30 分鐘以上（冷機）。不可在剛做完高負荷或反覆調整之後量。
　2. 功率機定轉速 60 rpm，duty 0 空轉 60 秒以上，記下扭力 = 空載讀數。
　3. duty 0 → 25（直接從 0 上去，不可從高往下降），停 30 秒，取後 15 秒平均扭力。
　4. 回到 duty 0 停 60 秒，記下空載讀數。
　5. 第 3～4 步共做 3 次。
　6. 淨扭力 = 每次 duty 25 扭力 − 前後空載讀數的平均；3 次取平均，判定是否在 {CAL_NM-CAL_TOL:.1f}～{CAL_NM+CAL_TOL:.1f} N·m。
　7. 再做一次 duty 0 → 50 停 30 秒（檢查點），淨扭力應在 {CHK_NM-CHK_TOL:.1f}～{CHK_NM+CHK_TOL:.1f} N·m。
　8. 基準點不合格時：回到 duty 0 再調 VR1，然後休息 10 分鐘，從第 2 步重做。
　　 基準點合格但檢查點不合格：不要再調 VR1，請回報（代表這台的曲線形狀與基準機不同）。
""")
s.h('為什麼用「扣掉空載的扭力」而不是總功率')
s.lines("""
　· VR1 調的是線圈電流，電流直接決定煞車扭力；功率是扭力 × 轉速，多受轉速誤差影響（差 1 rpm 就差 1.7%）。
　· 空載阻力會隨鏈條、皮帶狀態與溫度變動（同一台車 2.3～5.3 N·m），總功率跟著變，扣掉空載後不受影響。
　· 每做一次 0 → 25，讀數會比前一次高約 0.1～0.2%；反覆調整後量到的值會偏高，因此固定「冷機、3 次平均」。
""")
s.h('我方實測（基準機，VR1 未動，冷機）')
CALRUNS = [('2026-11-14 17:08', 2.39, (50.51, 50.74, 51.03), 95.13),
           ('2026-11-14 18:13', 1.74, (50.41, 50.56, 50.81), 94.55),
           ('2026-11-15 18:09', 2.39, (49.92, 50.25, 50.49), 93.97)]
s.table(['日期', '空載 N·m', 'duty 25 淨扭力（3 次）', '平均', '對基準', 'duty 50 淨扭力', '對檢查點'],
        [(t_, i_, ' / '.join(f'{v:.2f}' for v in v25), round(float(np.mean(v25)), 2), f'{float(np.mean(v25)) - CAL_NM:+.2f}',
          v50, f'{v50 - CHK_NM:+.2f}') for t_, i_, v25, v50 in CALRUNS])
s.r += 1
s.line(f'　模型在這兩點的值：duty 25 = {net_at(25, 60):.2f} N·m；duty 50 = {net_at(50, 60):.2f} N·m。'
       f'三趟都在容許範圍內（±{CAL_TOL:.1f} / ±{CHK_TOL:.1f}）。')
s.line('　注意：同一台車 11-13 量到的 duty 25 只有 48.4 N·m（低約 4%），11-14 起穩定在上表的值，推測為新車磨合。')
for col, w in zip('ABCDEFG', (110, 10, 24, 10, 10, 14, 10)): s.ws.column_dimensions[col].width = w
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
s.line(f'　第六版套用全部 {len(asc)} 個上升平台：功率誤差 RMS {math.sqrt(np.mean(err_p ** 2)):.1f}%，'
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
　「先前到過的最高 duty」與「目前 duty」。
　下表：新車台 2026-11-15～16，每 12～27 秒降 10%，實測淨扭力相對第六版模型偏高的百分比。
""")
g = defaultdict(list)
for r in use:
    if r['kind'] != 'desc': continue
    d = int(r['duty']); g[(round(float(r['rpm']) / 30) * 30, int(r['peak']), d)].append((float(r['net']) / net_at(d, float(r['rpm'])) - 1) * 100)
keys = sorted({k[:2] for k in g})
s.table(['踏頻（最高 duty）＼目前'] + list(range(10, 60, 10)),
        [[f'{c}（{p}）'] + [round(float(np.mean(g[(c, p, d)])), 1) if (c, p, d) in g else '' for d in range(10, 60, 10)] for c, p in keys])
s.ws.column_dimensions['A'].width = 24
s.r += 1
h30 = [float(np.mean(g[k])) for k in g if k[1] == 60 and k[2] == 30]
h10 = [float(np.mean(g[k])) for k in g if k[1] == 60 and k[2] == 10]
s.lines(f"""
　例：曾到 duty 60，降回 30 → 實際扭力比模型高約 {min(h30):.0f}～{max(h30):.0f}%；降到 10 → 高約 {np.mean(h10):.0f}%。
　新車台這次只量到最高 duty 60。更高的最高點（80、100）在前一台量過，偏高量更大（曾到 80 降回 50 約 +15%、降到 10 約 +41%），
　現象相同；新車台的完整磁滯表待補測。
""")
s.h('歸零可以消除大部分磁滯（前一台量測，60 → 0 短暫 → 30，60 踏頻，2026-10-29）')
s.table(['歸零時間', '降到 30 時偏高（相對同一輪從 0 上到 30）'],
        [(t_, v) for t_, v in zip(('不歸零', '0.5 s', '1 s', '2 s', '5 s'), DIP5)])
s.r += 1
s.lines("""
　歸零越久越接近；5 秒後只剩約 1～2%。
　線圈電流洩放慢：duty 設 0 後電流以時間常數約 0.7 秒衰減（前一台：1250 mA → 200 mA 約 1.9 秒）。
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
s.h('新車台（2026-11-13～16）')
s.lines(f"""
　· 熱機時扭力變低：60 踏頻跑到 duty 100（約 960 W）後只休息 8 分鐘就跑 30 踏頻，淨扭力比冷機同條件低 3～5%
　　（duty 10～50），高 duty 低 1～2%。90 踏頻跑到 duty 80（約 1380 W）後休息 7 分鐘、直接 0 → 60，比剛才低 3.9%。
　　回報電流沒有變，是煞車本身發熱。因此驗證與校正都必須在冷機下進行。
　· 冷機剛開始時，高踏頻的空載偏高：90 踏頻 2.9、120 踏頻 3.3 N·m，轉幾分鐘後降到 2.5～2.8。
　　30 / 60 踏頻空載約 2.0～2.2 N·m，變化不大。
　· 第六版 tare 取全部空載讀數：{T0:.4f} + {T1:.6f} × 踏頻，散布 σ {TARE_SD:.2f} N·m（60 踏頻時約 ±{TARE_SD*2*math.pi:.0f} W）。
　· 空載隨鏈條張力變動很大：同一台車鏈條太緊時 60 踏頻空載 5.3 N·m（33 W），放鬆後 1.7～2.6 N·m。
　　低功率（100 W 以下）的準確度主要由空載決定。
　· 新車磨合：同一台車 11-13 量到的淨扭力，低 duty 比 11-14 之後低 3～7%、高 duty 幾乎相同；11-14 之後三趟基準點一致（±0.5%）。
""")
s.h('前一台量測（現象應相同，數值供參考）')
s.lines("""
　· 同一平台停留時：往上調後每 10 秒約 +0.5%（磁性爬升），往下調後每 10 秒約 −0.2%。
　· 不同天、同條件重複量測的離散：σ 約 1%。
""")

# ==================== 9 版本差異 ====================
s = Sheet('9_版本差異', (110,))
s.title('9　版本差異（第六版相對第五版）')
s.h('一、改版原因：FW11.11.0（第五版參數）在新車台的實測')
s.lines("""
　下控回報功率（est_watt）對功率機實測，從 0 往上調，2026-11-13。超出 ±5% 的點不符合驗收標準。
""")
REP = {10: (2.8, -4.9, -5.5, -7.5), 20: (-0.5, -3.5, -4.6, -4.1), 30: (-1.0, -2.4, -4.1, -3.2), 40: (-0.1, -1.9, -3.9, -2.5),
       50: (1.6, -2.0, -4.2, -3.1), 60: (3.9, -1.4, -4.2, ''), 70: (6.5, 1.1, -4.6, ''), 80: (7.3, 3.5, -5.0, ''),
       90: (10.1, 3.3, '', ''), 100: (12.5, 3.1, '', '')}
s.table(['duty＼踏頻', 30, 60, 90, 120], [[d] + [f'{v:+.1f}%' if v != '' else '' for v in REP[d]] for d in REP])
s.r += 1
s.lines("""
　空載（duty 0）：下控回報 10 / 21 / 32 / 45 W（30 / 60 / 90 / 120 踏頻），功率機實測 5 / 16 / 18 / 27 W。
　誤差隨踏頻與 duty 變化，不是單一倍率，調 VR1 無法修正。
""")
s.h('二、不變的部分')
s.lines(f"""
　公式形式、反解方式、協定、1 kp = {KP_NM} N·m、速比 {RATIO} 都與第五版相同。程式結構不用改，只換下表的常數。
""")
s.h('三、要更換的常數')
s.table(['參數', '第五版', '第六版'], [
    ('a（u 一次項）', V5['a'], round(A_, 6)), ('b（u 二次項）', V5['b'], round(B_, 8)),
    ('duty 偏移 x0', V5['x0'], round(X0, 4)), ('轉速飽和 c0', V5['c0'], round(C0, 4)),
    ('轉速係數前係數', round((V5['c0'] + 60) / 60, 6), round(KS, 6)), ('tare 常數', V5['t0'], round(T0, 4)), ('tare 斜率', V5['t1'], round(T1, 6))])
s.ws.column_dimensions['B'].width = 14; s.ws.column_dimensions['C'].width = 14
s.r += 1
s.lines('　x0 同時出現在正向式、反解式與觸底判斷；轉速係數前係數 = (c0 + 60) / 60，請一併更新。')
s.lines('　同一 duty、同一踏頻的淨扭力，第六版相對第五版。同樣的 KP / ERG 目標，第六版在多數區域會給較低的 duty：')
s.table(['duty＼踏頻'] + [30, 60, 90, 120], [[d] + [f'{(net_at(d, c) / v5_net(d, c) - 1) * 100:+.1f}%' for c in (30, 60, 90, 120)]
                                           for d in (10, 30, 50, 70, 100)])
s.h('四、校正標準')
s.lines(f"""
　原：60 踏頻、duty 50，功率機扭力讀數 = 當下空載讀數 + 90.0 N·m（±1%）
　新：基準點 60 踏頻、duty 25，功率機扭力讀數 = 當下空載讀數 + {CAL_NM:.1f} N·m（±{CAL_TOL:.1f}）；
　　　檢查點 60 踏頻、duty 50，功率機扭力讀數 = 當下空載讀數 + {CHK_NM:.1f} N·m（±{CHK_TOL:.1f}）。見 6_校正程序。
　原本的「+90.0」不再適用於第六版參數。
""")
s.h('五、精度')
r5 = (net / v5_arr(duty, cad) - 1) * 100
s.lines(f"""
　第六版在新車台 {len(asc)} 個上升平台（踏頻 30～120）：淨扭力 RMS {math.sqrt(np.mean(resid ** 2)):.1f}%、最大 {np.max(np.abs(resid)):.1f}%。
　第五版套用同一批資料：RMS {math.sqrt(np.mean(r5 ** 2)):.1f}%、最大 {np.max(np.abs(r5)):.1f}%。
""")
s.h('六、限制（重要）')
s.lines("""
　· 第六版只依一台新車台的資料擬合（2026-11-15～16 冷機）。前一台（第五版的依據）與這一台是同一種設計，曲線卻差 3～19%。
　　其他台會接近哪一台目前不知道，需要再量至少一台才能確認第六版能否通用。
　· 90 踏頻 duty 90～100、120 踏頻 duty 60 以上沒有資料，為外推。
　· 往下調整（磁滯）的補償仍未實作，驗收只適用「從 0 往上調」的點。
""")

# ==================== 10 請貴司回覆 ====================
s = Sheet('10_請貴司回覆', (110,))
s.title('10　請貴司回覆')
s.lines("""
　1. FW11.11.0 相對 FW9.24.0，除了扭力模型參數之外還改了什麼？
　　 新車台這塊板（FW11.11.0）同一 duty 的回報電流比前一塊板（FW9.24.0）高約 20～38%
　　 （duty 30：837 對 607 mA；duty 50：1400 對 1142 mA），但實測扭力（60 踏頻）只差 −3～+13%。
　　 請說明電流量測或驅動方式是否有更動，或這是板與板之間的差異。
　2. 台間差異：同設計的兩台曲線差 3～19%。請評估把模型常數（a、b、x0、c0、tare 兩個）改成可用指令寫入、
　　 存在下控內的參數，不需重燒韌體；或至少提供每台可調的倍率與空載兩個參數。
　3. VR1 刻度太粗，很難調進 ±1%。可否改用多圈式可變電阻、串固定電阻縮小調整範圍，或改用程式內的倍率參數？
　4. 下控內部 VIN 異常：外部 24 V 穩定時，下控回報 VIN 會掉到 5～16 V，電流跳動、扭力少 15～30%；
　　 兩塊板都出現過，拔插下控電源即恢復。疑似在上控斷電重開、但 UART 線仍連接時觸發。
　　 請說明 VIN 量測位置，以及輸入保護（eFuse / MOSFET）是否可能鎖在異常狀態。
　5. 溫度：高負荷後同樣電流下扭力少 1.5～4%（見 8）。下控是否量測線圈或煞車溫度？能否補償？
　6. 磁滯：見 7。驅動是單端還是 H 橋？能否快速洩放（主動放電或反向脈衝）？傾向 A 或 B 哪種補償？
　7. VR1 實際調整的是什麼？duty 是電壓 PWM 還是電流閉迴路？
　8. ERG 觸底、ERG 超出、KP 低踏頻無法達成時，希望用哪個狀態旗標或錯誤碼標示？
　9. rpm 回報的取樣視窗長度？目前量化跳動 21～24 counts（60 踏頻約 2.3%）。
""")

wb.save(OUT)
print('輸出', OUT)
print(f'第六版 a={A_:.6f} b={B_:.8f} x0={X0:.4f} c0={C0:.4f} Ks={KS:.6f} tare={T0:.4f}+{T1:.6f}c σ{TARE_SD:.3f}')
print(f'RMS {math.sqrt(np.mean(resid**2)):.2f}% max {np.max(np.abs(resid)):.2f}%  duty50@60 net {net_at(50,60):.2f}  ERG例 duty {dd:.3f}')
