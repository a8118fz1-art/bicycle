#!/usr/bin/env python3
"""dyno_f1timer（配 Mega FW 0.14M 串接計畫 + 記錄頁 mega_status.json）

流程：記錄頁連上 Mega 並寫 mega_status.json → 本程式檢查（視窗、權限、狀態檔、Mega 選的計畫）→ ARMED →
功率機只認 F1（每下 = 下一組，按滿 N 下自己停，組長不影響換組）。F2 = 第 1 組（穩定組）→ 穩定後操作員在
「功率機視窗」按第一下 F1 = t0（功率機第 2 組），3 秒內在 Mega 按 * → 之後只看狀態檔的 Mega 組號與換組時刻：
在 Mega 每一組結束（= 下一組開始）前 3 s 送 1 下 F1，最後一組在 PLAN DONE 時送最後 1 下（第 N 下）。
v3（10/22）：照紀錄跑、不自己中斷 —— 按鍵、手動 F1、前景被搶、視窗暫失、跳組都照 Mega 對帳續跑；
只有 Mega 自己結束計畫或操作員連按 3 下 Esc 才停。只送 F1，絕不送到功率機以外的視窗。

  python dyno_f1timer.py --plan 60A1           正式
  python dyno_f1timer.py --plan 60B --dry-run  演練：按 Enter 當 t0，照 PC 時間表倒數，不送鍵、不切視窗
  python dyno_f1timer.py --plan 60A1 --check   只檢查（視窗、權限、切前景、狀態檔），不送任何鍵
時程來自 plans.json（gen_plans.py 由 .ino 產生），不要手改。
"""
import sys
if sys.version_info < (3, 11):
    sys.exit("需要 Python 3.11 以上（測試機用 py -3.13）。目前版本：" + sys.version.split()[0])
import argparse, ctypes, datetime, json, os, re, time, tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
VK_F1 = 0x70
MOUSE_VKS = {0x01, 0x02, 0x04, 0x05, 0x06}   # 滑鼠鍵不算「按鍵」
INJECT_GUARD_S = 0.6     # 自己送 F1 前後這段時間看到的 F1 視為自己送的
POLL_S = 0.02            # 鍵盤輪詢
STATUS_POLL_S = 0.25     # 狀態檔輪詢
GRP1_TIMEOUT_S = 8.0     # t0 後幾秒內 Mega 必須進 G1（* 要在 F1 後 3 s 內按）
STAR_WINDOW = (-1.0, 6.0)  # Mega G1 開始時刻相對 t0 的容許範圍（秒）
F1_LEAD_S = 3.0          # 在 Mega 每組結束（= 下一組開始）前幾秒送 F1（與 plans.json f1_lead_s 核對）
CATCHUP_GAP_S = 1.5      # 狀態檔停更恢復後補送 F1 之間的間隔（每下送前重讀狀態檔）
ACT_EARLY_S = 8.0        # 送 F1 前幾秒先把功率機切到前景
BAD_EVENT = re.compile(r"ABORT|LATE|NOT RUN|BOOT")
# v3（2026-10-22）：「照紀錄跑、不自己中斷」。F1 的下數一律由 Mega 狀態檔決定：
#   已送下數 = 程式送的 + 操作員在功率機視窗上手動按的 F1；應送下數 = Mega 走到哪裡。
#   少了就補、多了就等，絕不把 F1 送到功率機以外的視窗。只有 Mega 自己結束計畫（DONE / ABORT / 重開）才停。
VK_ESC = 0x1B
ESC_STOP_N, ESC_STOP_WIN_S = 3, 3.0   # 操作員主動停止：3 秒內連按 3 下 Esc
WARN_EVERY_S = 5.0                     # 同一種警告最多每 5 秒寫一次 log
PLAN_GONE_S = 10.0       # v3.1：狀態檔的 plan 連續這麼久都不是本計畫（也沒 PLAN DONE）才算 Mega 結束；單筆異常不算
# 0.12M：功率機最多 10 組 → 60A、COMP 各拆兩個。順序 = .ino PLANS[] = 記錄頁 PLAN_NAME（load_plan 會核對 plans.json）
PLAN_IDS = {"60A1": 1, "60A2": 2, "60B": 3, "CMP1": 4, "CMP2": 5, "C90A": 6, "C90B": 7, "C120": 8}   # 0.13M 加 C90A / C90B，0.14M 加 C120
BAR = "!" * 64


class ConfigError(Exception):
    pass


class Halt(Exception):
    """安全停止：停止所有自動送鍵。"""


# ---------------- 設定 / 時程 ----------------
def load_config(path):
    with open(path, "rb") as f:
        c = tomllib.load(f)
    title_re = c.get("title_re", "^C271-01-D7-.*06P$")
    try:
        re.compile(title_re)
    except (re.error, TypeError) as e:
        raise ConfigError(f"title_re 不合法: {e}")
    def path_of(key, default):
        v = c.get(key, default)
        if not isinstance(v, str) or not v:
            raise ConfigError(f"{key} 必須是字串")
        return v if os.path.isabs(v) else os.path.join(HERE, v)
    lead = c.get("activate_lead_s", ACT_EARLY_S)
    if not isinstance(lead, (int, float)) or isinstance(lead, bool) or not 1 <= lead <= 15:
        raise ConfigError("activate_lead_s 需 1～15")
    stale = c.get("status_stale_s", 3)
    if not isinstance(stale, (int, float)) or isinstance(stale, bool) or not 2 <= stale <= 10:
        raise ConfigError("status_stale_s 需 2～10")
    return {"title_re": title_re, "log_file": path_of("log_file", "f1timer.log"),
            "plans_file": path_of("plans_file", "plans.json"), "status_file": path_of("status_file", "mega_status.json"),
            "activate_lead_s": float(lead), "status_stale_s": float(stale)}


def load_plan(path, name):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    if name not in d["plans"]:
        raise ConfigError(f"沒有計畫 {name}；可用: {', '.join(d['plans'])}")
    k, p = d["constants"], d["plans"][name]
    groups = p["groups"]
    if p["id"] != PLAN_IDS.get(name):
        raise ConfigError(f"{name} 的 id {p['id']} 與程式不符，請重跑 gen_plans.py")
    if not 1 <= len(groups) + 1 <= k["PLAN_MAX_GROUPS"]:        # +1 = 功率機第 1 組（穩定組，F2 開始）
        raise ConfigError(f"{name} 功率機組數 {len(groups) + 1}（含穩定組）超過 {k['PLAN_MAX_GROUPS']}")
    if p.get("f1_lead_s") != F1_LEAD_S or p.get("f1_program") != len(groups):
        raise ConfigError(f"{name}：plans.json 是舊版（沒有 f1_lead_s / f1_program），請重跑 gen_plans.py")
    for i, g in enumerate(groups):
        last = i + 1 == len(groups)
        ok = (g["group"] == i + 1 and g.get("dyno_group") == i + 2 and 0 < g["mega_s"] <= g["len_s"] < p["dyno_group_s"]
              and (g["f1_at_s"] is None if last else g["f1_at_s"] == g["len_s"] - F1_LEAD_S > g["mega_s"]))
        if not ok:
            raise ConfigError(f"{name} 第 {i+1} 組資料不一致，請重跑 gen_plans.py")
    return d["fw_version"], p["id"], groups


# ---------------- log ----------------
class Logger:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8")

    def __call__(self, msg):
        line = f"{datetime.datetime.now().isoformat(timespec='milliseconds')} {msg}"
        print("\n" + line, flush=True)
        try:
            self.f.write(line + "\n"); self.f.flush()
        except OSError as e:
            print(f"(log 寫入失敗: {e})", flush=True)

    def close(self):
        self.f.close()


def beep():
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONHAND)
    except Exception:
        print("\a", end="", flush=True)


def big(log, msg):
    log(f"\n{BAR}\n!! {msg}\n!! 已停止自動送 F1。\n{BAR}")
    beep()


def read_status(path, tries=4, wait=0.03, opener=open, sleep=time.sleep):
    """讀 mega_status.json。剛好碰上 Chrome 取代檔案（沒有 FILE_SHARE_DELETE / 讀到一半）時短暫重試；
    仍失敗回 None（沿用上一份，交給新鮮度判斷）。REVIEW_4 R4-L1"""
    for i in range(tries):
        try:
            with opener(path, encoding="utf-8") as f:
                return json.loads(f.read())
        except (OSError, ValueError):
            if i + 1 < tries:
                sleep(wait)
    return None


# ---------------- Windows 實作（Linux 不會 import） ----------------
class WinOps:
    def __init__(self, title_re):
        from ctypes import wintypes
        from pywinauto import findwindows, keyboard, Application     # 開機時就 import（M4）
        self._fw, self._kb, self._App = findwindows, keyboard, Application
        self.title_re = title_re
        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetAsyncKeyState.restype = ctypes.c_short
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.u, self.wt = u, wintypes

    def find(self):
        return self._fw.find_windows(title_re=self.title_re, top_level_only=True)

    def activate(self, hwnd):
        self._App(backend="win32").connect(handle=hwnd).window(handle=hwnd).set_focus()

    def foreground(self):
        return self.u.GetForegroundWindow() or 0

    def send_f1(self):
        self._kb.send_keys("{F1}")          # 全程式唯一送鍵點

    def keys_down(self):
        return {vk for vk in range(1, 255) if vk not in MOUSE_VKS and self.u.GetAsyncKeyState(vk) & 0x8000}

    def keep_awake(self, on):
        """M9：計畫期間不讓系統睡眠 / 關螢幕（不送任何鍵）。自動鎖定仍要在 Windows 設定關掉。"""
        ES_CONTINUOUS, ES_SYSTEM, ES_DISPLAY = 0x80000000, 0x00000001, 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ((ES_SYSTEM | ES_DISPLAY) if on else 0))

    def _elevated(self, pid):
        k32, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
        h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        tok = self.wt.HANDLE()
        try:
            if not adv.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):   # TOKEN_QUERY
                return None
            ev, n = self.wt.DWORD(), self.wt.DWORD()
            ok = adv.GetTokenInformation(tok, 20, ctypes.byref(ev), 4, ctypes.byref(n))   # TokenElevation
            k32.CloseHandle(tok)
            return bool(ev.value) if ok else None
        finally:
            k32.CloseHandle(h)

    def privilege_mismatch(self, hwnd):
        """功率機是系統管理員、本程式不是 → 送出的按鍵會被 UIPI 靜默擋掉。回傳說明字串或 None。"""
        pid = self.wt.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        me = self._elevated(os.getpid())
        it = self._elevated(pid.value)
        if it is None and me is False:
            return "讀不到功率機的權限等級（多半表示它以系統管理員執行）"
        if it and not me:
            return "功率機以系統管理員執行、本程式不是"
        return None


# ---------------- 核心 ----------------
class Runner:
    def __init__(self, cfg, plan_name, plan_id, fw, groups, ops, log, *, dry_run=False, shadow=False,
                 status=None, clock=time.monotonic, wall=time.time, sleep=time.sleep, out=print):
        self.cfg, self.plan_name, self.plan_id, self.fw, self.groups = cfg, plan_name, plan_id, fw, groups
        self.ops, self.log, self.dry, self.shadow = ops, log, dry_run, shadow
        self.would = []                # shadow：[(group, mono, 換組後秒數)]
        self.op_f1 = []                # shadow：操作員實際按 F1 的 monotonic 時刻（R5-L3）
        self.clock, self.wall, self.sleep, self.out = clock, wall, sleep, out
        self.status_fn = status or (lambda: read_status(cfg["status_file"]))
        self.prev_keys, self.guard_until = set(), -1.0
        self.sent = []                 # [(group, mono)]
        self.next_i = 0                # 程式已送幾下 F1（= 下一下要結束的 Mega 組索引，0 起算）
        self.last_f1 = None            # (mono, wall) 最近一次功率機開始一組的時刻
        self.st, self.st_at = None, -1e9
        self.good_st = None            # v3.1：最近一份欄數正常的狀態（黏行那筆用它代替）
        self.fresh = False             # 最近一次讀到的狀態檔是否新鮮
        self.stale_since = None        # 停更開始的 monotonic（只用來顯示 / log）
        self.base = None               # ARMED 時的 boots / millis_backwards
        self.last_nano = None
        self.seen_events = 0
        self.hwnd = None
        self.esc_times = []            # v3：Esc 連按停止
        self.last_warn = {}            # v3：警告節流
        self.op_count = 0              # v3：操作員手動 F1 計入的下數

    def warn(self, key, msg, now=None):
        """v3：同一種狀況不洗版，每 WARN_EVERY_S 秒最多記一次。"""
        now = self.clock() if now is None else now
        if now - self.last_warn.get(key, -1e9) >= WARN_EVERY_S:
            self.last_warn[key] = now
            self.log(f"⚠ {msg}")

    # --- 狀態檔 ---
    def _age(self, st):
        return self.wall() - st["pc_epoch_ms"] / 1000.0

    def poll_status(self, now, force=False):
        """讀狀態檔。停更 / 讀不到 → self.fresh = False，**不停止**（阿陞 10/16 決定：HDD 偶爾寫慢）；
        只有新鮮的內容才做 ABORT / LATE / 重開 / FW 欄位檢查（有問題照樣 Halt）。"""
        if not force and now - self.st_at < STATUS_POLL_S:
            return self.st
        self.st_at = now
        st = self.status_fn()
        if st is not None:
            self.st = st
        age = None if self.st is None else self._age(self.st)
        self.fresh = age is not None and age <= self.cfg["status_stale_s"]
        if not self.fresh:
            if self.stale_since is None:
                self.stale_since = now
                if self.base is not None:
                    self.log(f"狀態檔停更（{'讀不到' if age is None else f'{age:.0f} s 沒更新'}），暫停送 F1、等待恢復（不停止）")
            return self.st
        if self.stale_since is not None:
            if self.base is not None:
                self.log(f"狀態檔恢復（停了 {now - self.stale_since:.0f} s）")
            self.stale_since = None
        s = self.st.get("s")
        if not s:
            if self.base is None:
                raise Halt("狀態檔還沒有 Mega 遙測（S 行）")
            self.fresh = False                              # v3：計畫中偶爾讀到空的 → 當作停更，不中斷
            return self.st
        if s.get("ncols", 0) < 21:
            if self.base is None:
                raise Halt("Mega 遙測沒有 sel 欄：Mega 不是 FW 0.11M 以後的版本（或記錄頁太舊）")
            # v3.1：計畫中出現 = 舊記錄頁把黏行寫進狀態檔；這筆不用，沿用上一份好的
            self.warn("ncols", f"狀態檔這筆只有 {s.get('ncols')} 欄（黏行），略過")
            self.st = self.good_st
            return self.st
        if self.base is not None:
            # v3.1：只有 BOOT 事件（boots 增加）才算確定重開。millis 倒退、ABORT / LATE 等事件可能是黏行假象，
            # 只警告；Mega 真的結束計畫時 plan 會一直不是本計畫，run() 等 PLAN_GONE_S 秒後停。
            if self.st.get("boots", 0) != self.base[0]:
                raise Halt("Mega 重開了（BOOT）：計畫已中斷，Mega 開機會自動歸零")
            if (self.st.get("millis_backwards", 0) != self.base[1]
                    or (self.last_nano is not None and s["nano_ms"] < self.last_nano)):
                self.warn("millis", "狀態檔的 Mega millis 倒退一次（多半是黏行），沒有 BOOT 事件，繼續")
            self.last_nano = s["nano_ms"]
            for e in self.st.get("events", []):
                if e.get("pc_ms", 0) / 1000.0 >= self.base[2] and BAD_EVENT.search(e.get("msg", "")):
                    self.warn("event", f"Mega 事件：{e['msg']}（不停止，照 Mega 狀態跟）")
        self.good_st = self.st
        return self.st

    def stale_line(self, now):
        self.out(f"\r⚠ 狀態檔 {now - self.stale_since:4.0f} s 沒更新：暫停送 F1，等待恢復（不會停止）…        ", end="", flush=True)

    # --- 鍵盤 ---
    def new_keys(self):
        now_down = self.ops.keys_down()
        new = now_down - self.prev_keys
        self.prev_keys = now_down
        return new

    def check_keys(self, now):
        """v3：按鍵不再中斷。F1 按在功率機視窗上 = 功率機真的換組了，計入已送下數；其他鍵只記 log。
        3 秒內連按 3 下 Esc = 操作員主動停止。"""
        for vk in sorted(self.new_keys()):
            if vk == VK_F1 and now <= self.guard_until:
                continue                                    # 自己送的 F1
            if self.shadow:                                 # 影子模式：操作員照常手動操作，只記錄
                if vk == VK_F1:
                    self.op_f1.append(now)
                    self.log(f"SHADOW 操作員 F1 {self._op_vs_would(now)}")
                else:
                    self.log(f"SHADOW 按鍵 VK 0x{vk:02X}")
                continue
            if vk == VK_ESC:
                self.esc_times = [t for t in self.esc_times if now - t <= ESC_STOP_WIN_S] + [now]
                if len(self.esc_times) >= ESC_STOP_N:
                    raise Halt(f"操作員連按 {ESC_STOP_N} 下 Esc，停止自動送 F1")
                self.log(f"Esc（再按 {ESC_STOP_N - len(self.esc_times)} 下停止自動送 F1）")
                continue
            if vk == VK_F1:
                if self.ops.foreground() == self.hwnd:
                    if self.next_i < len(self.groups):
                        self.next_i += 1; self.op_count += 1
                        self.last_f1 = (now, self.wall())
                        self.log(f"操作員在功率機上手動按 F1，已計入（程式這邊算第 {self.next_i}/{len(self.groups)} 下）；之後照 Mega 進度繼續")
                    else:
                        self.log("操作員手動按 F1，但程式的 F1 已全部送完（功率機可能多換了一組，請核對畫面）")
                else:
                    self.log("F1 按在功率機以外的視窗，功率機不會換組，不計入")
                continue
            self.warn(f"key{vk}", f"按鍵 VK 0x{vk:02X}（已忽略，不中斷；要停止請連按 {ESC_STOP_N} 下 Esc）", now)

    # --- 開始前檢查（M4、M5） ---
    def preflight(self):
        hwnds = self.ops.find()
        if len(hwnds) != 1:
            raise ConfigError(f"符合標題的功率機視窗有 {len(hwnds)} 個（需剛好 1 個）")
        pm = self.ops.privilege_mismatch(hwnds[0])
        if pm:
            raise ConfigError(f"{pm}；兩邊要用相同權限啟動")
        self.hwnd = hwnds[0]
        try:
            st = self.poll_status(self.clock(), force=True)
        except Halt as e:
            raise ConfigError(str(e))
        if not self.fresh:
            raise ConfigError(f"狀態檔讀不到或超過 {self.cfg['status_stale_s']:.0f} s 沒更新：{self.cfg['status_file']}（記錄頁有沒有選狀態檔？）")
        s = st["s"]
        if st.get("fw") and st["fw"] != self.fw:
            raise ConfigError(f"Mega FW {st['fw']} 與 plans.json 的 {self.fw} 不符")
        if s.get("sel") != self.plan_id:
            raise ConfigError(f"Mega SEQ 畫面選的不是 PLAN {self.plan_name}（sel={s.get('sel')}）；請在 Mega 用 ↑↓ 選到 PLAN {self.plan_name}")
        if s.get("plan"):
            raise ConfigError("Mega 已經在跑計畫；請先長按 # 中止、重新來過")
        self.base = (st.get("boots", 0), st.get("millis_backwards", 0), self.wall())
        self.last_nano = s["nano_ms"]
        return self.hwnd

    def wait_t0(self):
        """等操作員在功率機視窗上按第一下 F1（背景偵測，不攔截）。按在別的視窗不算（M3）。"""
        self.prev_keys = self.ops.keys_down()
        self.log(f"ARMED 計畫 {self.plan_name}：功率機 F2（第 1 組穩定組）→ 轉速穩定後在【功率機視窗】按第一下 F1（第 2 組），3 秒內在 Mega 按 *")
        last, changed_since = -1e9, None
        while True:
            now = self.clock()
            self.poll_status(now)
            st = self.st["s"]
            if self.fresh and (st.get("sel") != self.plan_id or st.get("plan") not in (0, self.plan_id)):
                changed_since = now if changed_since is None else changed_since   # v3.1：持續才算，單筆黏行不算
                if now - changed_since >= PLAN_GONE_S:
                    raise Halt(f"等待期間 Mega 選單／計畫變了（sel={st.get('sel')} plan={st.get('plan')}）")
            else:
                changed_since = None
            new = self.new_keys()
            if VK_F1 in new:
                if self.ops.foreground() == self.hwnd:
                    t0, t0w = now, self.wall()
                    self.log(f"\n{'#' * 64}\n## T0 偵測到功率機上的 F1（功率機第 2 組）。現在 3 秒內在 Mega 按 *。之後不要碰鍵盤！\n{'#' * 64}")
                    beep()
                    self.last_f1 = (t0, t0w)
                    return t0, t0w
                self.log("⚠ F1 不是按在功率機視窗上，不算 t0（請先點功率機視窗再按 F1；功率機若已開始錄，請先停掉）")
                beep()
            for vk in sorted(new - {VK_F1}):
                self.log(f"(t0 前按鍵 VK 0x{vk:02X}，忽略)")
            if not self.fresh:
                self.stale_line(now)
            elif now - last >= 1:
                last = now
                self.out("\r尚未偵測到 t0（在功率機視窗按 F1）…   ", end="", flush=True)
            self.sleep(POLL_S)

    def _op_vs_would(self, t_op):
        """R5-L3：操作員實際 F1 與最近一次「程式會送」的時差（正 = 操作員較晚）。"""
        if not self.would:
            return "（程式還沒有會送的時刻）"
        g, tw, _ = min(self.would, key=lambda w: abs(t_op - w[1]))
        return f"比程式會送的第 {g} 下 {'晚' if t_op >= tw else '早'} {abs(t_op - tw):.2f} s"

    # --- 送 F1 ---
    def tag(self, g):
        """程式送的這一下 F1：結束 Mega Gk（功率機第 k+1 組），開始功率機第 k+2 組；最後一下 = 第 N 下，功率機自己停。"""
        n = len(self.groups) + 1
        nxt = f"→ 功率機第 {g['group'] + 2}/{n} 組" if g["group"] < len(self.groups) else "（第 N 下，功率機停）"
        return f"程式第 {g['group']}/{len(self.groups)} 下 F1：結束 Mega G{g['group']}{nxt}"

    def activate(self, g):
        """v3：找不到 / 不只一個功率機視窗時不中斷，回 False 等下一輪再試。"""
        tag = self.tag(g)
        hwnds = self.ops.find()
        if len(hwnds) != 1:
            self.warn("win", f"{tag}：符合標題的功率機視窗有 {len(hwnds)} 個，等恢復成 1 個再送（不中斷）")
            return False
        if hwnds[0] != self.hwnd:
            self.log(f"功率機視窗換了（舊 {self.hwnd} → 新 {hwnds[0]}），改用新視窗")
            self.hwnd = hwnds[0]
        if not self.shadow:                                 # 影子模式不切前景
            try:
                self.ops.activate(self.hwnd)
            except Exception as e:
                self.warn("act", f"{tag}：切功率機到前景失敗（{type(e).__name__}），稍後再試")
                return False
        return True

    def fire(self, g, now_sched_info, lag=0.0):
        tag = self.tag(g)
        # REVIEW_4 R4-L2：送前再讀一次狀態檔（abort / 重開 / 組號）
        st = self.poll_status(self.clock(), force=True)
        s = st["s"]
        if not self.fresh:
            return False                                    # 剛好停更：這次不送，等恢復再判斷（不停止）
        if self.due(st, self.clock())[0] <= self.next_i:
            self.warn("recheck", f"{tag}：送前重讀狀態檔，現在還不該送（plan={s.get('plan')} grp={s.get('grp')}），這次不送")
            return False
        if self.shadow:
            now, noww = self.clock(), self.wall()
            self.would.append((g["group"], now, lag))
            self.last_f1 = (now, noww)
            self.next_i += 1
            recent = [t for t in self.op_f1 if abs(now - t) <= 15]
            op = (f"；操作員實際 F1 比這裡{'晚' if recent[-1] >= now else '早'} {abs(recent[-1] - now):.2f} s" if recent else "")
            self.log(f"SHADOW 此時會送 F1 {tag}（{now_sched_info}；前景{'是' if self.ops.foreground() == self.hwnd else '不是'}功率機；未送、未切視窗{op}）")
            return True
        if self.ops.foreground() != self.hwnd:              # v3：被別的視窗搶走 → 切回去，這次不送、下一輪再送
            self.warn("fg", f"{tag}：前景視窗不是功率機，切回功率機後再送（不中斷）")
            self.activate(g)
            return False
        self.guard_until = self.clock() + INJECT_GUARD_S
        if self.ops.foreground() != self.hwnd:              # 緊接送鍵前再確認一次
            self.warn("fg", f"{tag}：前景視窗不是功率機，切回功率機後再送（不中斷）")
            self.activate(g)
            return False
        self.ops.send_f1()
        now, noww = self.clock(), self.wall()
        self.guard_until = now + INJECT_GUARD_S
        self.sent.append((g["group"], now))
        self.last_f1 = (now, noww)
        self.next_i += 1
        self.log(f"F1 {tag} 已送出（{now_sched_info}）")
        return True

    def _done(self, st):
        return (st["s"].get("plan") == 0 and
                any("PLAN DONE" in e.get("msg", "") and e.get("pc_ms", 0) / 1000.0 >= self.base[2] for e in st.get("events", [])))

    def due(self, st, now):
        """依狀態檔算「到現在為止應該已送幾下」與目前組資訊：(due, cur, rem)。
        Mega 在 Gc → G1..G(c−1) 的結束都過了（c−1 下）；Gc 若不是最後一組且剩 ≤ F1_LEAD_S → 再 1 下；PLAN DONE → 全部。
        rem = Gc 剩幾秒（組結束 = 下一組開始；最後一組 = 內容結束）。"""
        n = len(self.groups)
        if self._done(st):
            return n, n + 1, 0.0
        s = st["s"]
        if s.get("plan") != self.plan_id or not s.get("grp"):
            return 0, 0, None
        cur = min(int(s["grp"]), n)
        g = self.groups[cur - 1]
        elapsed = self.wall() - st["grp_since_pc_ms"] / 1000.0
        rem = g["len_s"] - elapsed
        d = cur - 1 + (1 if cur < n and rem <= F1_LEAD_S else 0)
        return d, cur, rem

    def run(self, t0, t0w):
        """t0 = 操作員第一下 F1（＋3 s 內 *，Mega G1）。之後只跟著狀態檔：Mega 每組結束前 3 s 送 1 下，
        PLAN DONE 時送最後 1 下（共 len(groups) 下）。停更：不停止、不送；恢復後缺幾下補幾下（間隔 CATCHUP_GAP_S，每下重讀）。"""
        if self.dry:
            return self._run_dry(t0)
        n = len(self.groups)
        grp1_ok, stale_seen, activated, gone_since = False, False, -1, None
        last_send, last_draw = -1e9, -1e9
        while self.next_i < n:
            now = self.clock()
            self.check_keys(now)
            st = self.poll_status(now)
            if not self.fresh:
                stale_seen = True
                self.stale_line(now)
                self.sleep(POLL_S)
                continue
            s = st["s"]
            plan = s.get("plan")
            done = self._done(st)
            # v3.1（2026-10-29）：序列埠黏行會讓記錄頁寫出 plan=300、grp=600 這種值（60B 實機因此誤停）。
            # 欄位不合理的這一筆直接跳過；plan 合理但不是本計畫，要連續 PLAN_GONE_S 秒才算 Mega 結束。
            grp = s.get("grp")
            if (plan not in (0, *PLAN_IDS.values()) or not isinstance(grp, int) or isinstance(grp, bool)
                    or not 0 <= grp <= n):
                self.warn("garbled", f"狀態檔這筆欄位不合理（plan={plan} grp={grp}），略過")
                self.sleep(POLL_S); continue
            if not grp1_ok:                                 # Mega G1：v3 只警告，不中斷（照 Mega 實際開始的時刻跟）
                if (plan == self.plan_id and s.get("grp")) or done:
                    if plan == self.plan_id and s.get("grp") == 1 and not stale_seen:
                        rel = st["grp_since_pc_ms"] / 1000.0 - t0w
                        if not STAR_WINDOW[0] <= rel <= STAR_WINDOW[1]:
                            self.log(f"⚠ Mega G1 在第一下 F1 後 {rel:+.1f} s 才開始（建議 {STAR_WINDOW[0]:+.0f}～{STAR_WINDOW[1]:+.0f} s）；"
                                     "功率機第 2 組會多錄一段阻力 0，數據仍可用，照 Mega 繼續")
                    grp1_ok = True
                else:
                    if now - t0 > GRP1_TIMEOUT_S:
                        self.warn("g1", f"第一下 F1 後 {now - t0:.0f} s，Mega 還沒進 G1（* 還沒按？）；繼續等，不中斷")
                    self.sleep(POLL_S); continue
            if plan != self.plan_id and not done:
                if gone_since is None:
                    gone_since = now
                if now - gone_since < PLAN_GONE_S:
                    self.warn("gone", f"狀態檔 plan={plan}，不是本計畫；{PLAN_GONE_S:.0f} 秒內恢復就繼續")
                    self.sleep(POLL_S); continue
                raise Halt(f"Mega 計畫已結束或中止（plan={plan}，持續 {PLAN_GONE_S:.0f} 秒），沒有紀錄可以跟了；"
                           f"程式還有 {n - self.next_i} 下 F1 沒送")
            gone_since = None
            d, cur, rem = self.due(st, now)
            if plan == self.plan_id and s.get("grp"):
                self.last_grp_st = st                        # 停止後推算手動時刻用
            if d < self.next_i:                             # v3：已送比 Mega 多（多半是操作員提早手動按了 F1）→ 等 Mega 追上，不送
                self.warn("ahead", f"已送 {self.next_i} 下、Mega 目前只需要 {d} 下（有人提早按了 F1？）；等 Mega 追上，這段不送")
            if d > self.next_i + 1 and not stale_seen:      # v3：跳組 → 照 Mega 補送
                self.log(f"⚠ Mega 進度比已送多 {d - self.next_i} 下（狀態檔沒停更卻跳組）；照 Mega 補送")
                stale_seen = True
            g = self.groups[self.next_i]
            if d > self.next_i:
                if now - last_send < CATCHUP_GAP_S:
                    self.sleep(POLL_S); continue
                if activated != self.next_i and self.activate(g):
                    activated = self.next_i
                behind = d - self.next_i - 1
                info = (f"補送（停更後）：Mega {'PLAN DONE' if done else f'G{cur}'}，還差 {behind} 下" if stale_seen or behind
                        else ("Mega PLAN DONE" if done else f"Mega G{cur} 剩 {rem:.1f} s"))
                if self.fire(g, info, 0.0 if rem is None else rem):
                    last_send = self.clock()
                    if behind == 0:
                        stale_seen = False
                else:
                    self.sleep(POLL_S)                      # v3：這次沒送（前景被搶、重讀不符…）→ 稍等再試，不空轉
                continue
            # 還沒到：提早切前景、顯示倒數
            if cur == self.next_i + 1 and rem is not None:
                left = rem - F1_LEAD_S if cur < n else rem
                if activated != self.next_i and left <= self.cfg["activate_lead_s"] and self.activate(g):
                    activated = self.next_i
                if now - last_draw >= 0.5:
                    last_draw = now
                    what = f"{left:6.1f} s 後送" if cur < n else f"內容剩 {left:6.1f} s，PLAN DONE 時送最後"
                    self.out(f"\rMega G{cur}/{n}{'（HOLD）' if s.get('hold') else ''}｜{what}第 {self.next_i + 1}/{n} 下 F1   ", end="", flush=True)
            self.sleep(POLL_S)
        if self.op_count:
            self.log(f"其中 {self.op_count} 下是操作員手動按的（已計入）")
        self.log(f"DONE 程式 {n} 下 F1 全部送完（功率機共 {n + 1} 下，應已自己停）；記錄頁下載 CSV")

    def _run_dry(self, t0):
        """dry-run：沒有狀態檔，假設 Mega 照 .ino 時程（G1 在 t0），只顯示每下 F1 的時刻。"""
        for g in self.groups:
            at = g["start_s"] + (g["f1_at_s"] if g["f1_at_s"] is not None else g["mega_s"])
            sched = t0 + at
            while True:
                now = self.clock()
                if now >= sched:
                    break
                self.out(f"\r[DRY] {sched - now:7.1f}s 後{self.tag(g)}   ", end="", flush=True)
                self.sleep(min(0.5, sched - now))
            self.log(f"DRYRUN {self.tag(g)} 此時會送 F1（第一下 F1 後 {at} s，未送）")
            self.next_i += 1
        self.log("DONE（dry-run）")

    def remaining_schedule(self):
        """停止後：用最後一次狀態檔的組號與換組時刻，推算剩下每一下 F1 的本機時刻 (下數, wall, mono)。只供手動參考。"""
        st = getattr(self, "last_grp_st", None)
        if st is None or self.next_i >= len(self.groups):
            return []
        cur = int(st["s"]["grp"])
        if cur < 1 or cur > len(self.groups):
            return []
        start_w = st["grp_since_pc_ms"] / 1000.0
        off = self.wall() - self.clock()
        out, t = [], start_w - self.groups[cur - 1]["start_s"]
        for g in self.groups[self.next_i:]:
            w = t + g["start_s"] + (g["f1_at_s"] if g["f1_at_s"] is not None else g["mega_s"])
            out.append((g["group"], w, w - off))
        return out


def print_schedule(name, fw, groups, out=print):
    n = len(groups)
    out(f"計畫 {name}（Mega FW {fw}）：功率機 {n + 1} 組（每組設 600 s）= 穩定組 + Mega {n} 組；F1 共 {n + 1} 下 = 操作員 1 + 程式 {n}")
    out("  下  時機                                  Mega 組  內容                  內容 s  整組 s")
    out(f"  操  穩定後操作員按（＋3 s 內 Mega *）      —        F2 穩定組 → 功率機第 2 組")
    for g in groups:
        what = f"SEQ{g['seq']} {g['seq_name']}" if g["kind"] == "test" else "休息 REST5"
        when = f"G{g['group']} 開始後 {g['f1_at_s']} s（結束前 {F1_LEAD_S:.0f} s）" if g["f1_at_s"] is not None else "PLAN DONE 時（最後一下）"
        out(f" {g['group']:>3}  {when:<36}  G{g['group']:<6} {what:<20}  {g['mega_s']:>5}  {g['len_s']:>5}")


def manual_mode(r, log, clock=time.monotonic, sleep=time.sleep):
    """停止後：印剩下各組本機時刻，只倒數顯示，不送任何鍵（Ctrl+C 結束）。"""
    rem = r.remaining_schedule()
    if not rem:
        return
    log("請手動按 F1 的時刻（本機時間，推算值；以 Mega 畫面為準：每組結束前約 3 s、最後一下在 PLAN DONE）：\n" + "\n".join(
        f"  程式第 {g:>2} 下（結束 Mega G{g}）  {datetime.datetime.fromtimestamp(w).strftime('%H:%M:%S')}" for g, w, _ in rem))
    try:
        for g, w, m in rem:
            while clock() < m:
                print(f"\r[手動] 第 {g} 下（結束 Mega G{g}）請在 {datetime.datetime.fromtimestamp(w).strftime('%H:%M:%S')} 按 F1：還有 {m - clock():6.0f} s（Ctrl+C 結束）  ",
                      end="", flush=True)
                sleep(0.5)
    except KeyboardInterrupt:
        pass


def do_check(cfg, plan, ops, log):
    hwnds = ops.find()
    log(f"CHECK 符合標題的視窗 {len(hwnds)} 個: {hwnds}")
    ok = len(hwnds) == 1
    if ok:
        pm = ops.privilege_mismatch(hwnds[0])
        if pm:
            log(f"CHECK 失敗：{pm}。兩邊要用相同權限啟動"); ok = False
        else:
            ops.activate(hwnds[0]); time.sleep(0.5)
            fg = ops.foreground(); ok = fg == hwnds[0]
            log(f"CHECK 切前景 {'成功' if ok else '失敗'}（前景 {fg}，功率機 {hwnds[0]}）；未送任何鍵")
    st = read_status(cfg["status_file"])
    if st is None:
        log(f"CHECK 狀態檔讀不到：{cfg['status_file']}"); return 1
    age = time.time() - st["pc_epoch_ms"] / 1000
    s = st.get("s") or {}
    log(f"CHECK 狀態檔 {age:.1f} s 前更新；FW={st.get('fw') or '?'} sel={s.get('sel')} plan={s.get('plan')} cols={s.get('ncols')}")
    if age > cfg["status_stale_s"] or s.get("ncols", 0) < 21:
        ok = False
    if plan and s.get("sel") != PLAN_IDS.get(plan):
        log(f"CHECK Mega 選單不是 PLAN {plan}"); ok = False
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="功率機 F1 定時器（Mega 0.14M 計畫）")
    ap.add_argument("--plan", help=" / ".join(PLAN_IDS))
    ap.add_argument("--config", default=os.path.join(HERE, "config.toml"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="演練：Enter 當 t0，不送鍵、不切視窗")
    g.add_argument("--check", action="store_true", help="只檢查視窗、權限、切前景、狀態檔；不送鍵")
    g.add_argument("--shadow", action="store_true",
                   help="影子演練：讀真的狀態檔、跟著 Mega 跑完整邏輯，只記錄「此時會送 F1」，不送鍵、不切視窗；操作員照常手動")
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.config)
        if not a.check:
            if not a.plan:
                raise ConfigError("請指定 --plan " + " / ".join(PLAN_IDS))
            fw, pid, groups = load_plan(cfg["plans_file"], a.plan)
    except (OSError, ValueError, KeyError, ConfigError) as e:
        print(f"設定錯誤: {e}")
        return 2
    log, r, ops = None, None, None
    try:
        log = Logger(cfg["log_file"])
        if a.check:
            return do_check(cfg, a.plan, WinOps(cfg["title_re"]), log)
        print_schedule(a.plan, fw, groups)
        if a.dry_run:
            r = Runner(cfg, a.plan, pid, fw, groups, None, log, dry_run=True)
            input("\n[DRY-RUN] 按 Enter 模擬操作員第一下 F1 ...")
            t0, t0w = time.monotonic(), time.time()
            log(f"T0 DRYRUN 計畫 {a.plan}")
            r.run(t0, t0w)
            return 0
        ops = WinOps(cfg["title_re"])
        r = Runner(cfg, a.plan, pid, fw, groups, ops, log, shadow=a.shadow)
        try:
            r.preflight()
        except ConfigError as e:
            log(f"開始前檢查失敗：{e}")
            beep()
            return 2
        ops.keep_awake(True)
        log(f"START {'SHADOW（不送鍵）' if a.shadow else ''}計畫 {a.plan} FW {fw}")
        t0, t0w = r.wait_t0()
        r.run(t0, t0w)
        return 0
    except Halt as e:
        big(log, str(e))
        if r:
            manual_mode(r, log)
        return 3
    except KeyboardInterrupt:
        if log:
            big(log, "Ctrl+C 中止")
            if r:
                manual_mode(r, log)
        return 130
    except Exception as e:
        msg = f"程式例外 {type(e).__name__}: {e}"
        if log:
            big(log, msg)
            if r:
                manual_mode(r, log)
        else:
            print(msg)
        return 4
    finally:
        if ops:
            try:
                ops.keep_awake(False)
            except Exception:
                pass
        if log:
            log.close()


if __name__ == "__main__":
    sys.exit(main())
