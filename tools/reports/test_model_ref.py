#!/usr/bin/env python3
"""
ems_model_ref.c（簡化版）的逐行 Python 對應與測試。
    python tools/reports/test_model_ref.py
檢查：第六版數值、ERG / KP 往返、倍率校正收斂、磁滯公式對實測、旗標、參數範圍、封包範例。
"""
import math, struct, sys
sys.stdout.reconfigure(encoding='utf-8')

RATIO, KP_NM = 15.0119, 9.8
DEFAULT = [2.374758, 0.00899796, 1.6251, 12.4604, 1.5790, 0.010934, 1.000, 0.353, 2.0]
PMIN = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.80, 0.0, 0.5]
PMAX = [4.0, 0.03, 10.0, 50.0, 6.0, 0.05, 1.20, 1.0, 30.0]
N_PARAM = len(DEFAULT)
STATUS_ERG_LIMIT = 0x08
# 新車台 2026-11-15～16 降 duty 實測：(最高 duty, 目前 duty, 偏高 %)；30 / 90 / 120 踏頻
HYST_MEAS = [(60, 10, 23.8), (60, 20, 16.8), (60, 30, 11.9), (60, 40, 7.2), (60, 50, 2.7),
             (60, 10, 24.1), (60, 20, 13.0), (60, 30, 7.1), (60, 40, 3.0), (60, 50, -0.5),
             (40, 10, 21.9), (40, 20, 8.4), (40, 30, 0.8)]

class Ref:
    def __init__(self):
        self.p = list(DEFAULT); self.peak = 0.0; self.zt = 0.0
    def param_set(self, i, v):
        if i >= N_PARAM or not (PMIN[i] <= v <= PMAX[i]): return 2
        self.p[i] = v; return 0
    def sf(self, c): c0 = self.p[3]; return (c0 + 60) / 60 * c / (c0 + c)
    def tare(self, c): return self.p[4] + self.p[5] * c
    def net(self, d, c):
        u = d - self.p[2]
        return 0.0 if u <= 0 else (self.p[0] * u - self.p[1] * u * u) * self.sf(c) * self.p[6]
    def duty_from_net(self, need, c, st):
        a, b, x0 = self.p[0], self.p[1], self.p[2]
        if need <= 0: return 0.0
        X = need / (self.sf(c) * self.p[6]); disc = a * a - 4 * b * X
        if disc < 0: st[0] |= STATUS_ERG_LIMIT; return 100.0
        d = (a - math.sqrt(disc)) / (2 * b) + x0
        if d > 100: st[0] |= STATUS_ERG_LIMIT; return 100.0
        return d
    def track(self, d, dt):
        if d <= 0:
            self.zt += dt
            if self.zt >= self.p[8]: self.peak = 0.0
        else:
            self.zt = 0.0; self.peak = max(self.peak, d)
    def excess(self, d):
        if d <= 0 or d >= self.peak: return 0.0
        x = (self.peak - d) / self.peak
        return self.p[7] * x * x
    def duty_for_net(self, need, c, st):
        d = self.duty_from_net(need, c, st); h = self.excess(d)
        if h > 0: d = self.duty_from_net(need / (1 + h), c, st)
        return d
    def erg(self, w_t, rpm, st):
        c = rpm / RATIO
        if c < 1: return 0
        w = 2 * math.pi * c / 60
        return int(self.duty_for_net(w_t / w - self.tare(c), c, st) * 10 + 0.5)
    def kp(self, k10, rpm, st):
        c = rpm / RATIO
        if c < 1: return 0
        return int(self.duty_for_net(k10 * 0.1 * KP_NM, c, st) * 10 + 0.5)
    def est_watt(self, dx10, rpm):
        c = rpm / RATIO; d = dx10 * 0.1
        n = self.net(d, c) * (1 + self.excess(d))
        return int((n + self.tare(c)) * 2 * math.pi * c / 60 + 0.5)

fails = 0
def check(name, ok, info=''):
    global fails
    print(('  ✔ ' if ok else '  ✘ ') + name + (f'　{info}' if info else ''))
    fails += 0 if ok else 1

R60 = round(60 * RATIO)
m = Ref()
print('第六版數值')
check('60 踏頻 duty 25 淨扭力 50.59', abs(m.net(25, 60) - 50.59) < 0.01, f'{m.net(25, 60):.3f}')
check('60 踏頻 duty 50 淨扭力 93.82', abs(m.net(50, 60) - 93.82) < 0.01, f'{m.net(50, 60):.3f}')
check('60 踏頻 duty 25 總功率 331.9 W', abs((m.net(25, 60) + m.tare(60)) * 2 * math.pi - 331.9) < 0.1)
check('轉速係數 30 / 120 = 0.853 / 1.094', abs(m.sf(30) - 0.8533) < 1e-3 and abs(m.sf(120) - 1.0941) < 1e-3)

print('ERG / KP 往返（無磁滯）')
worst = 0
for c in (30, 60, 90, 120):
    rpm = round(c * RATIO)
    for w in (100, 200, 300, 500, 800):
        st = [0]; d = m.erg(w, rpm, st)
        if st[0]: continue
        worst = max(worst, abs(m.est_watt(d, rpm) - w) - 0.005 * w)
check('ERG 目標 → duty → est_watt：誤差 ≤ 0.5% + 2 W（duty 解析度 0.1%、瓦數取整數）', worst <= 2.0, f'超出 0.5% 的部分最多 {worst:.2f} W')
st = [0]; d = m.kp(52, R60, st)
check('KP 5.2 @60 → duty 約 25.2', abs(d - 252) <= 1, f'MODE_DUTY {d}')

print('倍率校正收斂')
TRUE_K = 1.03                                     # 假設這台實際比模型強 3%
real = lambda r, d, c: r.net(d, c) / r.p[6] * TRUE_K
st = [0]; d = m.kp(52, R60, st) / 10
meas = real(m, d, 60); check('未校正：KP 5.2 實際 52.5 N·m', abs(meas - 52.5) < 0.1, f'{meas:.2f}')
g = m.p[6] * meas / 50.96; check('新倍率 = 1.030', abs(g - 1.03) < 0.002, f'{g:.4f}')
m.param_set(6, g); st = [0]; d = m.kp(52, R60, st) / 10; meas2 = real(m, d, 60)
check('校正後：KP 5.2 實際 50.96 ±0.5%（duty 解析度 0.1% ≈ ±0.24 N·m）', abs(meas2 / 50.96 - 1) < 0.005, f'{meas2:.3f}')
check('校正後：est_watt 與實際一致 ±0.5%', abs(m.est_watt(round(d * 10), R60) / ((meas2 + m.tare(60)) * 2 * math.pi) - 1) < 0.005)
m.param_set(6, 1.0)

print('磁滯補償')
m = Ref()
res = []
for pk, cur, h in HYST_MEAS:
    m.peak = pk; res.append(m.excess(cur) * 100 - h)
rms = math.sqrt(sum(r * r for r in res) / len(res))
check('公式對 13 個實測點：RMS ≤ 2%、最大 ≤ 3.5%', rms <= 2 and max(map(abs, res)) <= 3.5, f'RMS {rms:.2f}%、最大 {max(map(abs, res)):.2f}%')
m = Ref(); m.track(60, 0.1)
check('最高 60、目前 30 → 8.8%', abs(m.excess(30) - 0.353 * 0.25) < 1e-9, f'{m.excess(30) * 100:.2f}%')
check('目前 ≥ 最高 → 0', m.excess(60) == 0 and m.excess(70) == 0)
st = [0]; dn = m.kp(52, R60, st); d0 = Ref().kp(52, R60, [0])
check('往下調時 duty 變低', dn < d0, f'{d0} → {dn}')
m.track(0, 1.0); check('duty 0 維持 1 秒：記錄保留', m.peak == 60)
m.track(0, 1.0); check('duty 0 累計 2 秒：記錄清除', m.peak == 0)
m.param_set(7, 0.0); m.track(60, 0.1); check('k = 0 → 不補償', m.excess(30) == 0)

print('旗標')
st = [0]; m = Ref(); m.erg(10, R60, st); check('ERG 10 W @60 → duty 0、不設旗標', st[0] == 0)
st = [0]; m.kp(140, round(30 * RATIO), st); check('KP 14.0 @30 → STATUS_ERG_LIMIT 0x08', st[0] == STATUS_ERG_LIMIT)

print('參數範圍')
check('倍率 1.25 → ACK_PARAM_ERROR(2)', m.param_set(6, 1.25) == 2)
check('編號 9 → ACK_PARAM_ERROR(2)', m.param_set(9, 1.0) == 2)
check('NaN → ACK_PARAM_ERROR(2)', m.param_set(6, float('nan')) == 2)
check('倍率 1.05 → ACK_OK(0)', m.param_set(6, 1.05) == 0)

print('封包範例')
import proto_examples as pe
check('廠商協定附錄 A 13 個範例全部重現', all(ok for _, ok in pe.verify_vendor()))
check('預設參數與參考程式一致', pe.DEFAULT == DEFAULT)

print('\n全部通過' if fails == 0 else f'\n{fails} 項失敗'); sys.exit(1 if fails else 0)
