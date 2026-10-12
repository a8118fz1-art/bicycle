#!/usr/bin/env python3
"""功率機 .tst 與手把遙測 CSV 對齊、切段、取平均。

用法：
    python tools/align_dyno.py <功率機.tst> <head_unit_*.csv> [--out 結果.csv]

兩份紀錄必須在同一台電腦上錄（時鐘才一致）。功率機每列只有「自測試開始的秒數」，
絕對時間只有表頭一個；所以不信表頭，改用兩邊的轉速曲線做互相關，找出時間差。

切段規則（對應功率機約 10 秒的顯示延遲）：
  · 功率機轉速在同一整數值 ±1 rpm 內持續
  · 手把 duty 不變
  · 進入平台後先丟掉 SETTLE_S 秒
  · 剩下的扭力滾動標準差要小於 STABLE_STD，且有效長度至少 MIN_KEEP_S 秒
"""
import argparse, csv, math, statistics, sys
from datetime import datetime
sys.stdout.reconfigure(encoding="utf-8")

SETTLE_S   = 12.0     # 進入平台後丟掉的秒數（功率機顯示延遲約 10 秒）
MIN_KEEP_S = 8.0      # 平台有效長度下限，不足就標記重測
STABLE_STD = 0.35     # 扭力標準差上限 N·m
RATIO      = 15.0119  # 52/16 × 97/21，與 app.js 相同
MAX_RMS    = 3.0      # 對齊後轉速 RMS 超過這個值 = 兩個檔案不是同一次測試
HEADER_OFF = -1.5     # 轉速有變化的各輪對出來都在 -0.9～-2.5 秒；轉速不變時直接用這個值
MIN_OVERLAP = 120     # 對齊時至少要重疊的點數（0.5 秒一點 = 60 秒）；功率機常比記錄頁早開很久
VIN_MIN    = 23.0     # 平台內 VIN 低於這個值 = 電源掉壓，數據作廢

def model_net(duty, cad):
    """第四版模型的淨扭力（不含 tare）"""
    x = duty - 1.54
    if x <= 0: return 0.0
    return (2.232021 * x - 0.00656259 * x * x) * 1.14167 * cad / (8.50 + cad)

def read_tst(path):
    """回傳 (表頭時間, [段落])；每段是 [(t, 扭力, 轉速, 功率, 溫度), ...]"""
    txt = open(path, 'rb').read().decode('cp950', errors='replace')
    lines = txt.split('\r\n')
    head = lines[0].split('$')
    t0 = None
    try:
        d, tm = head[5].strip(), head[6].strip()            # '2026/9/20', '下午 11:09:50'
        ampm, hms = tm.split()
        h, m, s = map(int, hms.split(':'))
        if ampm == '下午' and h < 12: h += 12
        if ampm == '上午' and h == 12: h = 0
        y, mo, dd = map(int, d.split('/'))
        t0 = datetime(y, mo, dd, h, m, s)
    except Exception:
        pass
    segs, cur, last_t = [], [], -1.0
    for l in lines:
        p = l.strip().split('\t')
        if len(p) != 7:
            continue
        try:
            tq, rpm, pw, t, tc = (float(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4]))
        except ValueError:
            continue
        if t < last_t and cur:          # 時間倒退 = 重新開始錄
            segs.append(cur); cur = []
        cur.append((t, tq, rpm, pw, tc)); last_t = t
    if cur:
        segs.append(cur)
    return t0, segs

def read_head(path):
    S, E = [], []
    for r in csv.DictReader(open(path, encoding='utf-8-sig')):
        t = int(r['pc_epoch_ms']) / 1000.0
        if r['type'] == 'S':
            S.append((t, float(r['flywheel_rpm']), float(r['cadence']), float(r['duty_pct']),
                      float(r['current_ma']), float(r['pwr_w']), int(r['link']),
                      float(r['vin_v']) if r['vin_v'] else None))
        elif r['type'] in ('E', 'M'):
            E.append((t, r['type'], r['note']))
    return S, E

def interp(series, t):
    """series: [(t, v)] 已排序；線性內插，超出範圍回 None"""
    lo, hi = 0, len(series) - 1
    if t < series[lo][0] or t > series[hi][0]:
        return None
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if series[mid][0] <= t: lo = mid
        else: hi = mid
    (t1, v1), (t2, v2) = series[lo], series[hi]
    return v1 if t2 == t1 else v1 + (v2 - v1) * (t - t1) / (t2 - t1)

def align(seg, S, guess):
    """在 guess ± 180 秒內找出讓功率機轉速與手把踏頻最吻合的時間差（0.1 秒解析度）"""
    cad = [(s[0], s[2]) for s in S]
    pts = seg[::5]                                   # 0.5 秒取一點即可
    best = None
    for k in range(-1800, 1801):
        off = guess + k * 0.1
        err = n = 0
        for (t, tq, rpm, pw, tc) in pts:
            v = interp(cad, off + t)
            if v is None: continue
            err += (v - rpm) ** 2; n += 1
        if n < min(len(pts) * 0.5, MIN_OVERLAP): continue
        e = err / n
        if best is None or e < best[0]:
            best = (e, off, n)
    return best

def align_current(seg, S, guess):
    """轉速全程不變時（例如整輪都在 60 rpm）轉速曲線沒有特徵可對，
    改用手把電流與功率機扭力的相關係數找時間差。回傳格式同 align()，誤差欄填 0。"""
    cur = [(s[0], s[4]) for s in S]
    pts = seg[::5]
    best = None
    for k in range(-1800, 1801):
        off = guess + k * 0.1
        xs, ys = [], []
        for (t, tq, rpm, pw, tc) in pts:
            v = interp(cur, off + t)
            if v is None: continue
            xs.append(v); ys.append(tq)
        if len(xs) < min(len(pts) * 0.5, MIN_OVERLAP) or len(set(xs)) < 2: continue
        mx, my = statistics.mean(xs), statistics.mean(ys)
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
        r = sxy / math.sqrt(sxx * syy) if sxx and syy else 0
        if best is None or r > best[0]:
            best = (r, off, len(xs))
    return best

def plateaus(seg, S, off):
    """依功率機轉速與手把 duty 切出穩定段"""
    duty = [(s[0], s[3]) for s in S]
    out, cur = [], []
    def flush():
        if not cur: return
        t_start = cur[0][0]
        keep = [r for r in cur if r[0] - t_start >= SETTLE_S]
        out.append((cur, keep))
    for r in seg:
        t, tq, rpm, pw, tc = r
        d = interp(duty, off + t)
        if d is None: continue
        if cur and (abs(rpm - cur[0][2]) > 1.0 or abs(d - cur[0][5]) > 0.05):
            flush(); cur = []
        cur.append((t, tq, rpm, pw, tc, d))
    flush()
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tst'); ap.add_argument('head'); ap.add_argument('--out')
    a = ap.parse_args()
    t0, segs = read_tst(a.tst)
    S, E = read_head(a.head)
    print(f'功率機：{len(segs)} 段，表頭時間 {t0}')
    print(f'手把　：遙測 {len(S)} 筆，{datetime.fromtimestamp(S[0][0]):%H:%M:%S} → '
          f'{datetime.fromtimestamp(S[-1][0]):%H:%M:%S}')
    lost = [e for e in E if e[2] == 'LINK LOST']
    if lost:
        dur = S[-1][0] - S[0][0]
        print(f'　　　　LINK LOST {len(lost)} 次（平均每 {dur/len(lost):.1f} 秒一次）')
    results = []
    for i, seg in enumerate(segs, 1):
        if max(r[2] for r in seg) < 5:
            print(f'\n第 {i} 段：功率機沒有轉，略過'); continue
        guess = t0.timestamp() if t0 else S[0][0]
        moving = sorted(r[2] for r in seg if r[2] > 5)
        p10, p90 = moving[len(moving) // 10], moving[len(moving) * 9 // 10]
        if p90 - p10 < 8:                           # 轉速幾乎全程不變，改用電流對扭力
            best = align_current(seg, S, guess)
            if not best or best[0] < 0.8 or abs(best[1] - guess) > 179:
                print(f'\n第 {i} 段：電流與扭力對不起來，兩個檔案可能不是同一次測試，略過'); continue
            # 兩邊同一台電腦的時鐘，直接用表頭；電流對扭力的相關只用來確認檔案沒配錯
            # （它找到的是功率機扭力的反應延遲，不是時鐘差）
            off = guess + HEADER_OFF
            print(f'\n第 {i} 段：轉速全程不變，用表頭時間對齊（{HEADER_OFF:+.1f} 秒）；'
                  f'電流對扭力相關 {best[0]:.3f}，功率機扭力約落後 {HEADER_OFF - (best[1] - guess):.1f} 秒')
        else:
            best = align(seg, S, guess)
            if not best:
                print(f'\n第 {i} 段：對不上手把紀錄，略過'); continue
            rms, off, n = best
            if math.sqrt(rms) > MAX_RMS or abs(off - guess) > 179:
                print(f'\n第 {i} 段：轉速對不起來（RMS {math.sqrt(rms):.1f} rpm），兩個檔案可能不是同一次測試，略過')
                continue
            print(f'\n第 {i} 段：時間差 {off - guess:+.1f} 秒（相對表頭），轉速吻合 RMS {math.sqrt(rms):.2f} rpm')
        k = 0; rows = []
        for allr, keep in plateaus(seg, S, off):
            span = allr[-1][0] - allr[0][0]
            if span < SETTLE_S:          # 過渡段
                continue
            k += 1
            d = allr[0][5]
            if len(keep) < 2:
                continue
            tq = [r[1] for r in keep]; rp = [r[2] for r in keep]; pw = [r[3] for r in keep]
            sd = statistics.pstdev(tq)
            ks = keep[-1][0] - keep[0][0]
            ta, tb = off + keep[0][0], off + keep[-1][0]
            hs = [s for s in S if ta <= s[0] <= tb]
            hc = statistics.mean(s[2] for s in hs) if hs else float('nan')
            hm = statistics.mean(s[4] for s in hs) if hs else float('nan')
            hsd = statistics.pstdev(s[4] for s in hs) if len(hs) > 1 else float('nan')
            ok = '✔' if (sd <= STABLE_STD and ks >= MIN_KEEP_S) else '請重測'
            vins = [s[7] for s in S if ta - 5 <= s[0] <= tb and s[7]]   # VIN 只在 LINK UP 後更新，往前多看 5 秒
            if vins and min(vins) < VIN_MIN:
                ok = f'電源掉壓 {min(vins):.1f}V'
            rows.append(dict(seg=i, n=k, duty=d, rpm=round(statistics.mean(rp), 3),
                                torque=round(statistics.mean(tq), 4), power=round(statistics.mean(pw), 2),
                                torque_sd=round(sd, 4), keep_s=round(ks, 1),
                                head_cadence=round(hc, 3), head_ma=round(hm, 1), head_ma_sd=round(hsd, 1),
                                t_from=datetime.fromtimestamp(ta).strftime('%H:%M:%S'),
                                t_to=datetime.fromtimestamp(tb).strftime('%H:%M:%S'), ok=ok))
        # 同一輪的 duty 0 平台擬合 tare = a + b·轉速；只有一點就當常數
        tares = [(r['rpm'], r['torque']) for r in rows if r['duty'] == 0 and r['ok'] == '✔']
        if len(tares) >= 2 and max(t[0] for t in tares) - min(t[0] for t in tares) > 5:
            mx = statistics.mean(t[0] for t in tares); my = statistics.mean(t[1] for t in tares)
            b = sum((x - mx) * (y - my) for x, y in tares) / sum((x - mx) ** 2 for x, _ in tares)
            tare = lambda c: my + b * (c - mx)
        elif tares:
            tare = lambda c, v=statistics.mean(t[1] for t in tares): v
        else:
            tare = None
        print('  #  duty%  轉速    扭力     功率    扭力σ  有效秒  手把踏頻  電流mA ±σ    淨扭力  模型淨扭力   差    判定')
        for r in rows:
            net = mod = dif = None
            if tare and r['duty'] > 0:
                net = r['torque'] - tare(r['rpm'])
                mod = model_net(r['duty'], r['rpm'])
                dif = (net / mod - 1) * 100
            r.update(net=None if net is None else round(net, 3),
                     model_net=None if mod is None else round(mod, 3),
                     diff_pct=None if dif is None else round(dif, 2))
            tail = f'{net:7.3f}   {mod:7.3f}   {dif:+6.2f}%' if net is not None else ' ' * 30
            print(f' {r["n"]:2d}  {r["duty"]:5.1f}  {r["rpm"]:5.2f}  {r["torque"]:7.3f}  {r["power"]:7.1f}  '
                  f'{r["torque_sd"]:5.3f}  {r["keep_s"]:5.1f}   {r["head_cadence"]:6.2f}   {r["head_ma"]:5.0f} ±{r["head_ma_sd"]:<4.0f} {tail}  {r["ok"]}')
        if tare is None:
            print('  （這一輪沒有 duty 0 平台，無法扣 tare）')
        results += rows
    if a.out and results:
        with open(a.out, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader(); w.writerows(results)
        print(f'\n已輸出 {a.out}')

if __name__ == '__main__':
    main()
