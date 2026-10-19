#!/usr/bin/env python3
"""從 Mega .ino（0.11M 起）解析 SEQ / 計畫表，產生 plans.json 與 arduino/docs/DYNO_GROUP_TABLE.md。

唯一來源是 .ino（SQS_* 步表、SEQS、PLS_*、PLANS、PLAN_* 常數）；不要手改 plans.json。
用法: python gen_plans.py [--ino PATH] [--json plans.json] [--md 表.md]
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# repo 內的位置（tools/dyno_f1timer → arduino/）；在別處執行請用 --ino / --md 指定
DEFAULT_INO = os.path.normpath(os.path.join(HERE, "..", "..", "arduino", "ems_head_unit_mega", "ems_head_unit_mega.ino"))
DEFAULT_MD = os.path.normpath(os.path.join(HERE, "..", "..", "arduino", "docs", "DYNO_GROUP_TABLE.md"))


def _strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


def _define(src, name):
    m = re.search(rf"^#define\s+{name}\s+(\d+)\b", src, re.M)
    if not m:
        raise ValueError(f".ino 找不到 #define {name}")
    return int(m.group(1))


def parse_ino(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 .ino：{path}（請用 --ino 指定）")
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    fw = re.search(r'^#define\s+FW_VERSION\s+"([^"]+)"', raw, re.M).group(1)
    src = _strip_comments(raw)
    steps = {}
    for name, body in re.findall(r"static\s+constexpr\s+SeqStep\s+(SQS_\w+)\[\]\s*PROGMEM\s*=\s*\{(.*?)\};", src, re.S):
        steps[name] = [tuple(map(int, t)) for t in re.findall(r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}", body)]
        if len(steps[name]) != body.count("{"):          # 步表寫成運算式（如 {60*10,40,0}）時不要靜默略過
            raise ValueError(f"{name} 有 {body.count('{')} 步，只解析得出 {len(steps[name])} 步（步表只能寫整數）")
    names = dict(re.findall(r'static\s+const\s+char\s+(SN\d+)\[\]\s*PROGMEM\s*=\s*"([^"]*)"', src))
    seqs_body = re.search(r"SeqDef\s+SEQS\[\]\s*PROGMEM\s*=\s*\{(.*?)\};", src, re.S).group(1)
    seqs = [{"no": i + 1, "name": names[n], "steps": steps[a], "len_s": sum(h for _, h, _ in steps[a])}
            for i, (n, a) in enumerate(re.findall(r"SQ\(\s*(SN\d+)\s*,\s*(SQS_\w+)\s*\)", seqs_body))]
    pls = {n: [int(x) for x in re.findall(r"\d+", b)]
           for n, b in re.findall(r"static\s+constexpr\s+uint8_t\s+(PLS_\w+)\[\]\s*PROGMEM\s*=\s*\{(.*?)\};", src, re.S)}
    pnames = dict(re.findall(r'static\s+const\s+char\s+(PN\d+)\[\]\s*PROGMEM\s*=\s*"([^"]*)"', src))
    plans_body = re.search(r"PlanDef\s+PLANS\[\]\s*PROGMEM\s*=\s*\{(.*?)\};", src, re.S).group(1)
    plan_list = re.findall(r"\{\s*(PN\d+)\s*,\s*(PLS_\w+)\s*,\s*SQN\(\s*(PLS_\w+)\s*\)\s*\}", plans_body)
    k = {n: _define(src, n) for n in
         ("PLAN_REST_SEQ", "PLAN_MARGIN_S", "PLAN_GAP_S", "PLAN_LATE_GUARD_MS", "PLAN_MAX_GROUPS", "DYNO_GROUP_MAX_S")}
    plans = {}
    for idx, (pn, pl, pl2) in enumerate(plan_list, 1):
        if pl != pl2:
            raise ValueError(f"PLANS 項目 {pn} 的 SQN 指到別的陣列")
        plans[pnames[pn]] = build_plan(idx, pnames[pn], pls[pl], seqs, k)
    def line_of(pat):
        return raw[:re.search(pat, raw).start()].count("\n") + 1
    for s, (_, a) in zip(seqs, re.findall(r"SQ\(\s*(SN\d+)\s*,\s*(SQS_\w+)\s*\)", seqs_body)):
        s["array"], s["line"] = a, line_of(rf"SeqStep\s+{a}\[\]")
    return {"source": os.path.basename(path), "fw_version": fw, "constants": k,
            "plans_line": line_of(r"PlanDef\s+PLANS\[\]"), "const_line": line_of(r"#define\s+PLAN_REST_SEQ"),
            "seqs": [{"no": s["no"], "name": s["name"], "len_s": s["len_s"], "array": s["array"], "line": s["line"]}
                     for s in seqs],
            "plans": plans}


def dyno_s(mega_s, margin):
    return (mega_s + margin + 9) // 10 * 10          # 同 .ino 的 Cx::cxDynoS / planGroupStartS


# 功率機：只認 F1，每按一下 = 下一組；設定 N 組，按滿 N 下自己停。組長不影響換組，只要不早於 F1 自己結束 → 每組都設 600 s。
# 功率機第 1 組 = 穩定組（F2 開始）；第一下 F1（操作員）結束穩定組、開始功率機第 2 組 ＝ Mega G1（3 s 內按 *）。
# 之後 dyno_f1timer 在每個 Mega 組「結束前 3 s」送 1 下 F1；最後一組在 Mega PLAN DONE 時送最後 1 下（第 N 下）。
DYNO_GROUP_S = 600  # 功率機每組設定長度（含穩定組）
STABILIZE_S = DYNO_GROUP_S
DYNO_EXTRA = 1      # Mega 組號 + 1 = 功率機組號
F1_LEAD_S = 3       # 在 Mega 組結束（= 下一組開始）前幾秒送 F1


def build_plan(plan_id, name, segs, seqs, k):
    groups, t = [], 0
    for i, sq in enumerate(segs):
        if not 2 <= sq <= len(seqs):
            raise ValueError(f"計畫 {name} 的段 SEQ{sq} 不合法")
        items = [("test", sq)] + ([("rest", k["PLAN_REST_SEQ"])] if i + 1 < len(segs) else [])
        for kind, no in items:
            m = seqs[no - 1]["len_s"]
            slot = dyno_s(m, k["PLAN_MARGIN_S"])        # 韌體內部：組長 = 內容 + 30 進位到 10（之後 HOLD 等下一組）
            groups.append({"group": len(groups) + 1, "dyno_group": len(groups) + 1 + DYNO_EXTRA, "kind": kind,
                           "seg": i + 1 if kind == "test" else 0,
                           "seq": no, "seq_name": seqs[no - 1]["name"], "mega_s": m, "fw_slot_s": slot,
                           "start_s": t})
            t += slot + k["PLAN_GAP_S"]
    for i, g in enumerate(groups):
        last = i + 1 == len(groups)
        # Mega 組長 = 這組開始 → 下一組開始（planNextAt，絕對排程：內容 + HOLD）；最後一組 = 內容跑完（PLAN DONE）
        g["len_s"] = g["mega_s"] if last else groups[i + 1]["start_s"] - g["start_s"]
        g["f1_at_s"] = None if last else g["len_s"] - F1_LEAD_S   # 這組開始後幾秒送 F1（最後一組：PLAN DONE 時送）
    check_plan(name, groups, k)
    return {"id": plan_id, "segs": segs, "groups": groups, "dyno_groups": len(groups) + DYNO_EXTRA,
            "dyno_group_s": DYNO_GROUP_S, "f1_lead_s": F1_LEAD_S,
            "stabilize": {"dyno_group": 1, "dyno_s": STABILIZE_S, "start_key": "F2"},
            "f1_operator": 1, "f1_program": len(groups), "f1_total": len(groups) + 1,
            "end_s": groups[-1]["start_s"] + groups[-1]["mega_s"]}


def check_plan(name, groups, k):
    n = len(groups) + DYNO_EXTRA
    if not 1 <= n <= k["PLAN_MAX_GROUPS"]:
        raise ValueError(f"計畫 {name} 功率機共 {n} 組（含穩定組），超過 {k['PLAN_MAX_GROUPS']}")
    for g in groups:   # 功率機組長 600 s 不能比 Mega 這組先結束：內容與整組（含 HOLD）都要 < 600
        if not 0 < g["mega_s"] < DYNO_GROUP_S or not 0 < g["len_s"] < DYNO_GROUP_S:
            raise ValueError(f"計畫 {name} Mega G{g['group']} 內容 {g['mega_s']} s／整組 {g['len_s']} s 不 < {DYNO_GROUP_S}")
        if g["f1_at_s"] is not None and g["f1_at_s"] <= g["mega_s"]:
            raise ValueError(f"計畫 {name} Mega G{g['group']} F1 會落在內容還沒跑完時")


def fmt_t(s):
    return f"{s // 60}:{s % 60:02d}"


def make_md(d):
    k = d["constants"]
    mx_c = max((g["mega_s"], n, g["group"]) for n, p in d["plans"].items() for g in p["groups"])
    mx_l = max((g["len_s"], n, g["group"]) for n, p in d["plans"].items() for g in p["groups"])
    nlist = "、".join(f"{n} N={p['dyno_groups']}" for n, p in d["plans"].items())
    klist = "；".join(f"{n} = 操作員 1 + 程式 {p['f1_program']} = {p['f1_total']}" for n, p in d["plans"].items())
    out = [f"# 功率機設定頁「組」對照表（Mega FW {d['fw_version']} 串接計畫）", "",
           f"> 由 `dyno_f1timer/gen_plans.py` 解析 `{d['source']}` 自動產生，**不要手改**；改 .ino 後重跑 `python gen_plans.py`。", "",
           "## 功率機設定",
           f"- 功率機**只認 F1**：每按一下 = 下一組；設定 N 組，按滿 N 下自己停。組長不影響換組。",
           f"- **N = F1 的下數，F2 不算**（{nlist}）。**第一次正式跑時確認功率機在最後一下 F1 後真的自己停。**",
           f"- **每一組（含第 1 組穩定組）組長都設 {DYNO_GROUP_S} s**，只要求不會在 F1 之前自己結束。",
           f"  - Mega 每組內容最長 {mx_c[0]} s（{mx_c[1]} G{mx_c[2]}）、整組（含 HOLD）最長 {mx_l[0]} s（{mx_l[1]} G{mx_l[2]}），都 < {DYNO_GROUP_S} s（gen_plans.py 與測試檢查）。",
           f"  - 穩定組：F2 開始，**必須在 {DYNO_GROUP_S} s 內按第一下 F1**（否則穩定組自己結束）。",
           f"- 組數：功率機 N = 穩定組 + Mega 組數，**功率機最多只能設 {k['PLAN_MAX_GROUPS']} 組**（2026-10-19 確認），所以一個計畫最多 5 段。", "",
           "## F1 怎麼按（共 N 下）",
           "- F2 → 第 1 組（穩定組）。轉速穩定後**操作員按第 1 下 F1**（→ 功率機第 2 組），3 s 內 Mega 按 \\* → Mega G1。",
           f"- 之後 dyno_f1timer 只跟著 Mega：在 **Mega 每一組結束前 {F1_LEAD_S} s** 送 1 下 F1（休息組也一樣）→ 功率機和 Mega 一起換組。",
           "  - 「組結束」= 下一組開始（韌體 `planNextAt`，從 \\* 起的絕對排程）= 內容 + HOLD（內容跑完後阻力 0 等）。內容結束和組結束不同；以組結束為準，所以 F1 落在 HOLD 期間、不會切掉內容。",
           "  - 剩餘時間 = 這組長度 − 已過時間；已過時間 = 現在 − 狀態檔的 `grp_since_pc_ms`（記錄頁收到 Mega 換組的時刻，誤差 ≤ 0.5 s）。每組重新對齊，沒有獨立 PC 倒數表。",
           "- **最後一組沒有下一組**：Mega 內容跑完就 `PLAN DONE`（不 HOLD），程式看到 PLAN DONE 時送**最後 1 下（第 N 下）**，功率機按滿 N 下自己停。",
           f"- 按鍵數：{klist}。", "",
           "## 狀態檔停更（> 3 s 沒更新）：不停止",
           "- 停更期間不送、不停止，終端一行顯示；恢復後看 Mega 目前組號，缺幾下就補幾下，每下間隔 1.5 s，每下送前重讀狀態檔＋確認前景，已送數不會超過 Mega 實際走到的地方。", "",
           "## 韌體的 30 s 餘裕 / HOLD / LATE（PM 待決）",
           f"- 0.11M 每組 = 內容 + {k['PLAN_MARGIN_S']} s 進位到 10 s + {k['PLAN_GAP_S']} s，多出的時間 HOLD（阻力 0），LATE 門檻 {k['PLAN_LATE_GUARD_MS'] // 1000} s。這是當初假設「功率機組長固定、F1 照 PC 時刻送」留的餘裕。",
           "- 現在功率機只認 F1、F1 跟著 Mega 組結束送，**這段餘裕對功率機已不需要**，只讓每組多 30～40 s 阻力 0 的空錄。建議之後韌體版本拿掉（組 = 內容；或只留幾秒 HOLD），LATE 檢查也可一併簡化。本次不改韌體。", "",
           "## 各計畫", ""]
    for name, p in d["plans"].items():
        out += [f"### {name}（功率機 {p['dyno_groups']} 組 = 穩定組 + Mega {len(p['groups'])} 組；F1 共 {p['f1_total']} 下 = 操作員 1 + 程式 {p['f1_program']}；\\* 起約 {fmt_t(p['end_s'])}；段 = SEQ {', '.join(map(str, p['segs']))}）", "",
                "| 功率機組 | Mega 組 | 內容 | 內容 s | Mega 整組 s（含 HOLD） | 結束這組的 F1 | 開始時刻（\\* 起 mm:ss） |",
                "|---|---|---|---|---|---|---|",
                "| 1 | — | **穩定組**（F2 開始，Mega 不動） | — | — | 操作員第 1 下（穩定後，600 s 內） | — |"]
        for i, g in enumerate(p["groups"]):
            what = (f"段 {g['seg']}：SEQ{g['seq']} {g['seq_name']}" if g["kind"] == "test" else
                    f"休息（SEQ{g['seq']} {g['seq_name']}，阻力 0）")
            f1 = (f"程式第 {i + 1} 下：組開始後 {g['f1_at_s']} s（結束前 {F1_LEAD_S} s）" if g["f1_at_s"] is not None
                  else f"程式第 {i + 1} 下（最後）：PLAN DONE 時")
            out.append(f"| {g['dyno_group']} | G{g['group']} | {what} | {g['mega_s']} | {g['len_s']} | {f1} | {fmt_t(g['start_s'])} |")
        out.append("")
    out += ["## 來源（.ino 行號）", "", "| SEQ | 名稱 | 長度 s | 步表 |", "|---|---|---|---|"]
    used = sorted({g["seq"] for p in d["plans"].values() for g in p["groups"]})
    for s in d["seqs"]:
        if s["no"] in used:
            out.append(f"| {s['no']} | {s['name']} | {s['len_s']} | `{s['array']}` 第 {s['line']} 行 |")
    out += ["", f"計畫表 `PLANS` 第 {d['plans_line']} 行；常數 `PLAN_*` 第 {d['const_line']} 行起。", ""]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ino", default=DEFAULT_INO)
    ap.add_argument("--json", default=os.path.join(HERE, "plans.json"))
    ap.add_argument("--md", default=DEFAULT_MD)
    a = ap.parse_args(argv)
    d = parse_ino(a.ino)
    with open(a.json, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    with open(a.md, "w", encoding="utf-8") as f:
        f.write(make_md(d))
    for n, p in d["plans"].items():
        print(n, "Mega", len(p["groups"]), "組 / 功率機", p["dyno_groups"], "組 / F1", p["f1_total"], "下", [g["len_s"] for g in p["groups"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
