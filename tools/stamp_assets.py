#!/usr/bin/env python3
"""把 HTML / JS 裡的 ?v= 查詢字串換成「版本號 + 檔案內容雜湊」。

問題：原本所有引用都寫死 ?v=16.55，但 app.js 改過好幾次內容早就不同，
瀏覽器仍然沿用舊快取，除非使用者自己 Ctrl+F5。

做法：掃描 index.html / uart_test.html / app.js 裡形如 "./NAME?v=XXX" 的引用，
以被引用檔案的 sha256 前 8 碼重新標記為 ?v=<版本>-<雜湊>。
內容一改雜湊就變，網址跟著變，瀏覽器必定重抓；內容沒變則完全不動檔案。

用法：
    python tools/stamp_assets.py          # 就地更新，commit 前執行
    python tools/stamp_assets.py --check  # 只檢查，有過期就以 exit 1 結束
"""
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ["index.html", "uart_test.html", "app.js"]

# 只標記 JS / CSS 資產，刻意不含 .html。
# HTML 之間的導覽連結若也雜湊，會形成循環相依：
#   index.html 引用 app.js，app.js 連到 uart_test.html，uart_test.html 又連回 index.html。
# 改動任一個都會讓下一個的雜湊失效，單趟掃描永遠收斂不了。
# 資產不會反過來引用 HTML，限定在 js/css 就沒有環，一趟就穩定。
# HTML 本身由 GitHub Pages 的 Cache-Control 控管，過期會自行重新驗證，不會像
# 帶固定 ?v= 的資產那樣永久卡在舊版。
REF = re.compile(r'(?P<prefix>\./)(?P<name>[A-Za-z0-9_.-]+\.(?:js|css))\?v=(?P<ver>[^"\'\s>]*)')


def app_version() -> str:
    """從 app.js 取 APP_VERSION，去掉開頭的 v。取不到就退回 0."""
    m = re.search(r'APP_VERSION\s*=\s*"v?([0-9.]+)"', (ROOT / "app.js").read_text(encoding="utf-8"))
    return m.group(1) if m else "0"


def digest(path: Path) -> str:
    """以正規化為 LF 的內容計算雜湊。

    本專案 core.autocrlf=true，同一份 commit 在工作目錄可能是 LF 也可能是 CRLF
    （直接解壓縮取得的是 LF，經 git checkout 還原的是 CRLF）。若直接雜湊原始位元組，
    同樣的內容會算出不同結果，換一台機器 clone 後 --check 就會誤報。
    先把 CRLF 收斂成 LF，雜湊才只反映真正的內容變動。
    """
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()[:8]


def main() -> int:
    check_only = "--check" in sys.argv
    version = app_version()
    stale = False

    for target in TARGETS:
        path = ROOT / target
        if not path.exists():
            print(f"跳過 {target}（不存在）")
            continue

        original = path.read_text(encoding="utf-8")

        def replace(match: re.Match) -> str:
            nonlocal stale
            referenced = ROOT / match.group("name")
            if not referenced.exists():
                print(f"  ! {target} 引用了不存在的 {match.group('name')}，保持原樣")
                return match.group(0)
            # 檔案引用自己時（例如 app.js 內連到 uart_test.html）一樣以被引用檔為準
            want = f"{version}-{digest(referenced)}"
            if match.group("ver") != want:
                stale = True
                print(f"  {target}: {match.group('name')}  {match.group('ver')} -> {want}")
            return f'./{match.group("name")}?v={want}'

        updated = REF.sub(replace, original)

        if updated != original and not check_only:
            path.write_text(updated, encoding="utf-8", newline="")

    if check_only:
        if stale:
            print("\n有引用的 ?v= 與檔案內容不符，請執行：python tools/stamp_assets.py")
            return 1
        print("所有 ?v= 都與檔案內容相符。")
        return 0

    print("\n完成。" if stale else "\n所有 ?v= 已是最新，未修改任何檔案。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
