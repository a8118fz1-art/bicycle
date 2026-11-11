#!/usr/bin/env python3
"""dyno_f1timer 模擬測試：不碰 Windows、不送真的按鍵，假造 Mega 狀態檔與功率機視窗，
把 plans.json 每個計畫完整跑一遍，檢查 F1 的下數與時機。

    python test_f1timer_sim.py

檢查項目（每個計畫）：
  1. 程式送的 F1 下數 = Mega 組數（功率機總下數 = 這個 + 操作員第 1 下）
  2. 第 k 下落在 Mega 第 k 組結束前 F1_LEAD_S 秒左右（最後一下在 PLAN DONE）
  3. 不會在內容還沒跑完時送（F1 一定落在 HOLD 期間）
  4. 狀態檔停更 20 s 跨過換組時，恢復後補送、總下數不變、不多送
"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dyno_f1timer as F                                   # noqa: E402

STAR_DELAY = 1.0       # 操作員按第一下 F1 後幾秒按 *（容許 −1～+6）
T0 = 1_000_000.0       # 假時鐘起點（monotonic 與 wall 共用）


class Sim:
    """假 Mega + 假功率機。時間只在 sleep() 時前進。"""

    def __init__(self, plan, plan_id, stale=None, keys=(), fg_off=(), freeze=None, garble=()):
        self.t = T0
        self.plan, self.plan_id = plan, plan_id
        self.groups = plan["groups"]
        self.started = None            # Mega G1 開始（wall）
        self.sent = []                 # 程式送 F1 的時刻
        self.stale = stale             # (開始, 結束)：這段期間狀態檔不更新
        self.last_st = None
        self.keys = list(keys)         # v3：[(開始, 結束, vk)] 操作員按鍵（絕對時間）
        self.fg_off = list(fg_off)     # v3：[(開始, 結束)] 前景被別的視窗搶走
        self.freeze = freeze           # v3：(開始, 結束) 狀態檔照常更新、但 Mega 組號卡住 → 之後跳組
        self.garble = list(garble)     # v3.1：[(開始, 結束, {欄位: 值})] 黏行造成的錯位欄位（狀態檔照常新鮮）
        self.dyno = []                 # 功率機實際換組的時刻（程式送的 + 操作員在功率機上按的）
        self._down = set()

    # 時鐘
    def clock(self): return self.t
    def wall(self): return self.t
    def sleep(self, dt): self.t += max(dt, 0.001)

    # Mega 狀態
    def _mega(self):
        if self.started is None or self.t < self.started:
            return {"plan": 0, "grp": 0, "hold": 0}, None, False
        rel = self.t - self.started
        last = self.groups[-1]
        if rel >= last["start_s"] + last["mega_s"]:
            return {"plan": 0, "grp": 0, "hold": 0}, None, True
        g = max((x for x in self.groups if x["start_s"] <= rel), key=lambda x: x["start_s"])
        hold = int(rel - g["start_s"] >= g["mega_s"])
        return {"plan": self.plan_id, "grp": g["group"], "hold": hold}, self.started + g["start_s"], False

    def status(self):
        if self.stale and self.stale[0] <= self.t < self.stale[1] and self.last_st is not None:
            return self.last_st        # 停更：一直回同一份（pc_epoch_ms 不動）
        if self.freeze and self.freeze[0] <= self.t < self.freeze[1] and self.last_st is not None:
            st = dict(self.last_st); st["pc_epoch_ms"] = self.t * 1000      # 新鮮，但組號不動
            return st
        m, since, done = self._mega()
        events = [{"nano_ms": 0, "pc_ms": (self.started + self.groups[-1]["start_s"] + self.groups[-1]["mega_s"]) * 1000,
                   "msg": "PLAN DONE"}] if done else []
        st = {"schema": 1, "pc_epoch_ms": self.t * 1000, "fw": "", "boots": 0, "millis_backwards": 0,
              "grp_since_pc_ms": (since or self.t) * 1000, "events": events,
              "s": {"nano_ms": int((self.t - T0) * 1000), "link": 1, "ncols": 21, "plan": m["plan"],
                    "grp": m["grp"], "hold": m["hold"], "sel": self.plan_id}}
        self.last_st = st
        for a, b, bad in self.garble:
            if a <= self.t < b:
                st = dict(st)
                top = {k[1:]: v for k, v in bad.items() if k.startswith("^")}      # "^欄位" = 狀態檔頂層欄位
                st.update(top)
                st["s"] = {**st["s"], **{k: v for k, v in bad.items() if not k.startswith("^")}}
        return st

    # 假功率機視窗（WinOps 介面）
    def find(self): return [1]
    def privilege_mismatch(self, h): return None
    def activate(self, h): pass
    def foreground(self): return 0 if any(a <= self.t < b for a, b in self.fg_off) else 1
    def keys_down(self):
        down = {vk for a, b, vk in self.keys if a <= self.t < b}
        for vk in down - self._down:                   # 按下的瞬間：F1 按在功率機上 → 功率機換組
            if vk == F.VK_F1 and self.foreground() == 1:
                self.dyno.append(self.t)
        self._down = down
        return down
    def send_f1(self): self.sent.append(self.t); self.dyno.append(self.t)


def run_plan(name, plan, stale=None, **kw):
    sim = Sim(plan, plan["id"], stale, **kw)
    logs = []
    cfg = {"status_file": "", "status_stale_s": 3.0, "activate_lead_s": 8.0}
    r = F.Runner(cfg, name, plan["id"], "", plan["groups"], sim, logs.append,
                 status=sim.status, clock=sim.clock, wall=sim.wall, sleep=sim.sleep, out=lambda *a, **k: None)
    r.preflight()
    t0 = sim.t                                    # 操作員第一下 F1
    sim.started = t0 + STAR_DELAY                 # * 在 F1 後 1 s → Mega G1
    r.run(t0, t0)
    return sim, logs


def check(name, plan, sim, tol, stale=None):
    g = plan["groups"]
    errs = []
    if len(sim.sent) != len(g):
        errs.append(f"送了 {len(sim.sent)} 下，應為 {len(g)}")
    for k, (grp, t) in enumerate(zip(g, sim.sent), 1):
        start = sim.started + grp["start_s"]
        if grp["f1_at_s"] is None:                                  # 最後一下：PLAN DONE
            expect = start + grp["mega_s"]
        else:
            expect = start + grp["f1_at_s"]
            if t < start + grp["mega_s"]:
                errs.append(f"第 {k} 下在內容還沒跑完時送出")
        in_stale = stale and stale[0] <= expect <= stale[1] + tol
        if abs(t - expect) > tol and not in_stale:
            errs.append(f"第 {k} 下時刻差 {t - expect:+.2f} s")
        if in_stale and not (expect - tol <= t <= stale[1] + tol + F.CATCHUP_GAP_S * len(g)):
            errs.append(f"第 {k} 下（停更期間）補送時刻 {t - expect:+.2f} s 不合理")
    return errs


def v3_cases(plans):
    """v3「照紀錄跑、不自己中斷」：各種干擾下都不停、功率機總換組數 = Mega 組數；連按 3 下 Esc 才停。"""
    bad = 0
    for name in ("60B", "C120"):
        p = plans[name]; g = p["groups"]
        base = T0 + STAR_DELAY
        end1 = base + g[0]["start_s"] + g[0]["f1_at_s"]          # 程式原本送第 1 下的時刻
        end2 = base + g[1]["start_s"] + g[1]["f1_at_s"]
        cases = {
            "按到別的鍵和 1 下 Esc": dict(keys=[(base + 30, base + 30.2, 0x41), (base + 60, base + 60.1, F.VK_ESC)]),
            "操作員提早手動按 F1": dict(keys=[(end2 - 5, end2 - 4.9, F.VK_F1)]),
            "送 F1 時視窗被搶走 5 秒": dict(fg_off=[(end1 - 1, end1 + 4)]),
            "組號卡住 20 秒後跳組": dict(freeze=(end1 - 10, end1 + 10)),
            # v3.1：10/29 60B 實機誤停（plan=300）；黏行也可能錯成合理範圍內的別的值
            "黏行 plan=300 grp=600": dict(garble=[(base + 94, base + 94.6, {"plan": 300, "grp": 600})]),
            "黏行 plan 錯成別的計畫 3 秒": dict(garble=[(end1 - 30, end1 - 27, {"plan": 1, "grp": 2})]),
            "黏行 grp 往前跳 0.5 秒": dict(garble=[(end1 - 30, end1 - 29.5, {"grp": len(g)})]),
            "黏行 欄數不足": dict(garble=[(end2 + 20, end2 + 20.5, {"ncols": 17, "plan": 60, "grp": 0})]),
            "黏行 millis 倒退": dict(garble=[(end2 + 40, end2 + 40.5, {"nano_ms": 5, "^millis_backwards": 1})]),
            "黏行 假 LATE 事件": dict(garble=[(end2 + 60, end2 + 60.5,
                                          {"^events": [{"nano_ms": 0, "pc_ms": (end2 + 60) * 1000, "msg": "XX LATE 9"}]})]),
        }
        for cname, kw in cases.items():
            errs = []
            sim = None
            try:
                sim, _ = run_plan(name, p, **kw)
            except F.Halt as e:
                errs.append(f"中斷了：{e}")
            if sim:
                if len(sim.dyno) != len(g):
                    errs.append(f"功率機換組 {len(sim.dyno)} 次，應為 {len(g)}")
                for k, (grp, t) in enumerate(zip(g, sim.dyno), 1):
                    if grp["f1_at_s"] is not None and t > base + grp["start_s"] + grp["len_s"] + 10:
                        errs.append(f"第 {k} 下晚了 {t - (base + grp['start_s'] + grp['len_s']):.1f} s")
            print(("✓" if not errs else "✗"), f"[v3] {name}：{cname}", *(["\n    " + e for e in errs] if errs else []))
            bad += bool(errs)
        try:                                           # 連按 3 下 Esc 要能停
            run_plan(name, p, keys=[(base + 30 + i, base + 30.1 + i, F.VK_ESC) for i in range(3)])
            print("✗", f"[v3] {name}：連按 3 下 Esc 沒有停"); bad += 1
        except F.Halt as e:
            print("✓", f"[v3] {name}：連按 3 下 Esc → 停止（{e}）")
    return bad


def main():
    with open(os.path.join(HERE, "plans.json"), encoding="utf-8") as f:
        d = json.load(f)
    bad = 0
    for name, plan in d["plans"].items():
        if F.PLAN_IDS.get(name) != plan["id"]:
            print(f"✗ {name}: PLAN_IDS={F.PLAN_IDS.get(name)} 與 plans.json id={plan['id']} 不符"); bad += 1; continue
        sim, _ = run_plan(name, plan)
        errs = check(name, plan, sim, tol=0.6)
        # 停更 20 s，剛好跨過第 1 組結束的 F1 時刻
        g1 = plan["groups"][0]
        s0 = T0 + STAR_DELAY + g1["f1_at_s"] - 10 if g1["f1_at_s"] is not None else None
        if s0:
            sim2, logs2 = run_plan(name, plan, stale=(s0, s0 + 20))
            errs2 = check(name, plan, sim2, tol=0.6, stale=(s0, s0 + 20))
            if not any("補送" in l for l in logs2):
                errs2.append("停更後沒有補送紀錄")
            errs += [f"[停更] {e}" for e in errs2]
        print(("✓" if not errs else "✗"), name, f"Mega {len(plan['groups'])} 組，程式送 {len(sim.sent)} 下",
              *(["\n    " + e for e in errs] if errs else []))
        bad += bool(errs)
    bad += v3_cases(d["plans"])
    print("\n全部通過" if not bad else f"\n{bad} 項失敗")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
