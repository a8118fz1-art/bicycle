#!/usr/bin/env python3
"""
建置「EMS Bike 下控 參數指令與微調 提案」xlsx（給下控廠商，與第六版一起寄）

用法：
    python tools/reports/build_param_proposal.py [輸出.xlsx]

內容是提案，需廠商確認後才定案；參數預設值與第六版（build_model_v6.py）一致。
"""
import os, sys
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.stdout.reconfigure(encoding='utf-8')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    f'~/Downloads/EMS Bike 下控 參數指令與微調提案_{date.today():%Y%m%d}.xlsx')

F = '微軟正黑體'
TITLE = Font(name=F, size=14, bold=True, color='123C6B')
H2 = Font(name=F, size=12, bold=True, color='123C6B')
BODY = Font(name=F, size=11)
BOLD = Font(name=F, size=11, bold=True)
RED = Font(name=F, size=11, bold=True, color='C0392B')
MONO = Font(name='Consolas', size=10.5)
HEAD_FILL = PatternFill('solid', fgColor='E8EEF6')
thin = Side(style='thin', color='9FB3CC')
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
wb = Workbook(); wb.remove(wb.active)

class Sheet:
    def __init__(self, name, widths=(110,)):
        self.ws = wb.create_sheet(name); self.r = 1
        for i, w in enumerate(widths): self.ws.column_dimensions[chr(65 + i)].width = w
    def line(self, text='', font=BODY):
        self.ws.cell(self.r, 1, text).font = font; self.r += 1
    def title(self, t): self.line(t, TITLE)
    def h(self, t): self.r += 1; self.line(t, H2)
    def lines(self, txt, font=BODY):
        for t in txt.strip('\n').split('\n'): self.line(t, font)
    def table(self, head, data):
        for j, v in enumerate(head):
            c = self.ws.cell(self.r, 1 + j, v); c.font = BOLD; c.fill = HEAD_FILL; c.border = BOX
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        self.r += 1
        for row in data:
            for j, v in enumerate(row):
                c = self.ws.cell(self.r, 1 + j, v); c.font = BODY; c.border = BOX
                c.alignment = Alignment(horizontal='left' if j == len(row) - 1 else 'center', wrap_text=True)
            self.r += 1

# ==================== 0 說明 ====================
s = Sheet('0_說明')
s.title('EMS Bike 下控　參數指令與微調　提案')
s.lines(f"""
{date.today():%Y-%m-%d}。本文件是「提案」，請貴司評估後回覆，雙方確認後才定案。與「下控扭力模型 第六版」一起提供。
""")
s.h('目的')
s.lines("""
　希望這次韌體更新一次完成，之後不需要再為了調整模型而重燒韌體：
　　1. 第六版模型常數改成可用指令讀寫、存在下控內（之後只需寫入新數值）。
　　2. 每台出廠校正改用指令寫入的微調參數，取代刻度太粗的 VR1。　　→ 需先確認，見 1_微調（請確認）
　　3. 磁滯補償：往下調整時依補償表修正，補償數值可用指令寫入。　　→ 見 3_新增協定 第三節
""")
s.h('本文件各頁')
s.lines("""
　1_微調（請確認）　　：微調參數的做法與要請貴司確認的問題
　2_參數表　　　　　　：參數編號、預設值、允許範圍
　3_新增協定　　　　　：新增指令、磁滯補償表、版本確認、狀態旗標
　4_出廠校正流程　　　：由 TFT 上控執行的校正步驟，說明各指令的使用時機
　5_請貴司回覆　　　　：本提案需要回覆的事項彙整
""")
s.line('★ 現有封包格式、既有指令與 STATUS_REPORT 欄位都不變；以下全部是新增。', RED)

# ==================== 1 微調 ====================
s = Sheet('1_微調（請確認）')
s.title('1　微調：用參數取代 VR1（需貴司確認後才定案）')
s.h('背景')
s.lines("""
　VR1 刻度太粗，每台很難調進 ±1%，而且要拆蓋轉電阻。
　同設計的兩台實測曲線差 3～19%，兩塊板同一 duty 的回報電流差 20～38%，需要每台可調的手段。
""")
s.h('提案：新增 2 個每台可調參數')
s.table(['參數', '預設值', '作用'], [
    ('扭力倍率', '1.000', '模型算出的淨扭力 × 倍率；同時套用到回報功率（est_watt）與 ERG / KP 換算 duty'),
    ('空載補正', '0 N·m', '加在 tare 上，補每台機械阻力的差異'),
])
s.ws.column_dimensions['A'].width = 110
s.h('請貴司確認')
s.lines("""
　1. VR1 實際調整的是什麼？（電流迴路增益？電流量測比例？其他？）
　2. 改用程式倍率後，VR1 能否固定在出廠位置不再調整？或 VR1 有其他功能必須保留？
　3. 倍率只套在模型計算（回報功率與 duty 換算），不改變線圈實際輸出——我方傾向這樣做，貴司是否同意？
　4. 每台板子電流量測的差異大概多大？倍率允許範圍我方暫定 0.80～1.20，是否足夠？
　5. 參數存 flash 是否可行？可寫入次數？開機讀到損壞資料時的處理方式？
""")
s.h('若同意：出廠校正由 TFT 上控執行（見 4_出廠校正流程）')
s.lines("""
　上控在 60 rpm 用 KP 5.2（51.0 N·m）量 3 次，依功率機實測算出新倍率，以 SET_PARAM 寫入、SAVE_PARAMS 存檔。
　空載補正（參數 7）不自動調整，維持 0；空載只檢查範圍。
""")

# ==================== 2 參數表 ====================
s = Sheet('2_參數表', (8, 18, 14, 16, 60))
s.title('2　參數表')
s.lines("""
　數值格式 float32（IEEE 754，little-endian）。預設值即第六版。超出允許範圍的寫入一律回 ERROR、不寫入。
""")
s.table(['編號', '參數', '預設值', '允許範圍（暫定）', '說明'], [
    (0, 'a', '2.374758', '1.0～4.0', '第六版模型常數'),
    (1, 'b', '0.00899796', '0～0.03', '第六版模型常數'),
    (2, 'x0', '1.6251', '0～10', '第六版模型常數（正向式、反解式、觸底判斷都會用到）'),
    (3, 'c0', '12.4604', '1～50', '第六版模型常數；轉速係數前係數 = (c0 + 60) / 60 由此計算'),
    (4, 'tare 常數', '1.5790', '0～6', '第六版空載常數'),
    (5, 'tare 斜率', '0.010934', '0～0.05', '第六版空載斜率'),
    (6, '扭力倍率', '1.000', '0.80～1.20', '每台微調（待第 1 頁確認）'),
    (7, '空載補正 N·m', '0', '−3～+3', '每台微調（待第 1 頁確認）'),
    (8, '磁滯歸零重置時間 s', '2', '0.5～30', 'duty 0 維持超過此時間，清除「最高 duty」記錄（見 3_新增協定 第三節）'),
    (9, '磁滯補償開關', '1', '0 或 1', '0 = 關閉補償'),
])
s.r += 1
s.lines("""
　· 轉速係數前係數不另外存，由 c0 計算，避免兩者不一致。
　· 寫入後立即生效（RAM）；需 SAVE_PARAMS 才會保留到下次開機。
""")

# ==================== 3 新增協定 ====================
s = Sheet('3_新增協定', (26, 14, 46, 46))
s.title('3　新增協定')
s.lines("""
　封包格式不變：55 AA LEN CMD DATA CRC16 0D（CRC 與現行相同）。
　下列指令碼為我方暫定，未與現有 0x01～0x03、0x06、0x10、0x20、0x21、0x40、0x80、0x81、0xF0、0xF1 衝突；貴司如有編號規則可調整。
""")
s.h('一、參數讀寫')
s.table(['指令', '方向', 'DATA', '回應'], [
    ('0x30 SET_PARAM', '上控 → 下控', '編號 (1 byte) + 數值 (float32, 4 byte)', 'ACK；超出範圍或不在 STOP 狀態回 ERROR'),
    ('0x31 GET_PARAM', '上控 → 下控', '編號 (1 byte)', 'CMD 0x31：編號 + 數值'),
    ('0x32 SAVE_PARAMS', '上控 → 下控', '無', '參數與磁滯表存入 flash 後回 ACK'),
    ('0x33 LOAD_DEFAULTS', '上控 → 下控', '無', '恢復第六版預設值後回 ACK（不自動存檔）'),
])
s.line('　寫入限制：只有在 STOP 狀態可寫入；開機時檢查 flash 資料，損壞則使用預設值。')
s.h('二、版本確認')
s.lines("""
　GET_VERSION（0x20）回應在現有欄位之後加 2 byte：目前參數表（含磁滯表）的 CRC16。
　用途：上控可確認下控內的參數是否與我方預期一致。
""")
s.h('三、磁滯補償')
s.lines("""
　現象：從高 duty 往下調時，實際扭力比模型高（見第六版 7_磁滯與歸零），曾到 duty 60 降回 10 約高 24%。
　機制：
　　1. 下控記錄「上次歸零後到過的最高 duty」；duty 0 維持超過參數 8 的時間後清除。
　　2. 目前 duty 低於最高 duty 時，依補償表查出偏高量 h（%），目標淨扭力 ÷ (1 + h) 後再反解 duty；
　　　 回報功率（est_watt）也一併用 × (1 + h) 修正。
　　3. 表格之間線性內插。參數 9 = 0 時整個機制關閉。
""")
s.table(['指令', '方向', 'DATA', '說明'], [
    ('0x34 SET_HYST_ROW', '上控 → 下控', '行號 (1 byte) + 9 × int16', '行號 0～4 = 最高 duty 20 / 40 / 60 / 80 / 100；9 格 = 目前 duty 10～90；單位 0.1%'),
    ('0x35 GET_HYST_ROW', '上控 → 下控', '行號 (1 byte)', '回應格式與寫入相同'),
])
s.line('　存檔共用 0x32 SAVE_PARAMS。')
s.r += 1
s.line('　出廠預設值（單位 0.1%）：最高 duty 40、60 兩行填我方實測，其他行先填 0，補測後再用指令寫入。', BOLD)
hd = ['最高 duty＼目前 duty'] + [str(d) for d in range(10, 100, 10)]
rows = [(20, [0] * 9), (40, [219, 84, 8, 0, 0, 0, 0, 0, 0]), (60, [240, 149, 95, 51, 11, 0, 0, 0, 0]),
        (80, [0] * 9), (100, [0] * 9)]
for col in 'EFGHIJ': s.ws.column_dimensions[col].width = 9
s.table(hd, [[str(p)] + v for p, v in rows])
s.lines("""
　來源：新車台 2026-11-15～16。最高 60 = 30 與 90 踏頻平均；最高 40 = 120 踏頻（單次）。
""")
s.h('四、STATUS_REPORT 旗標新增 3 個 bit（位置請貴司指定未使用的 bit）')
s.table(['旗標', '意義', '', ''], [
    ('ERG 觸底', '目標功率低於空載阻力，已夾到 duty 0', '', ''),
    ('超出能力', 'duty 100 仍達不到目標（ERG 或 KP），已夾到 duty 100', '', ''),
    ('磁滯補償作用中', '目前 duty 有套用補償', '', ''),
])

# ==================== 4 出廠校正流程 ====================
s5 = Sheet('4_出廠校正流程', (14, 30, 30, 36))
s5.title('4　出廠校正流程（由 TFT 上控執行，供貴司了解指令使用時機）')
s5.lines("""
　條件：冷機（停機 30 分鐘以上）；功率機定轉速 60 rpm；操作員把功率機扭力讀數（N·m）輸入上控。
　每次負載都從 KP 0 直接上去（不從高往下降，避免磁滯）。
""")
s5.table(['步驟', '上控動作', '操作員', '判定'], [
    ('0 前置', 'GET_VERSION（含參數 CRC）、GET_PARAM 6', '確認冷機', '踏頻 60 ±1、VIN ≥ 23 V、通訊正常'),
    ('1 空載', 'KP 0，等 60 秒', '輸入空載讀數', '2.0～3.5 N·m；超出提示「檢查鏈條」，操作員可選擇繼續'),
    ('2 量測 ×3', 'KP 5.2 停 30 秒 → KP 0 停 60 秒', '每次輸入負載讀數與空載讀數', '3 次淨扭力差 ≤ 0.5 N·m，否則重做'),
    ('3 寫入', '新倍率 = 舊倍率 × 平均淨扭力 ÷ 51.0；SET_PARAM 6 → GET_PARAM 6 比對 → SAVE_PARAMS', '確認寫入', '新倍率 0.80～1.20，超出不寫入'),
    ('4 驗證', 'KP 5.2、KP 9.6、ERG 300 W 各一次', '輸入讀數', 'KP 5.2 ±1%；KP 9.6 ±2%；ERG 300 W 總功率 ±5%'),
])
s5.r += 1
s5.lines("""
　淨扭力 = 負載讀數 − 前後兩次空載讀數的平均。
　KP 9.6 不合格代表這台曲線形狀與模型不同，倍率無法修正，請回報我方，不要再調整。
　倍率只套在模型計算上，所以只要差異是整體比例，一次就會收斂。
""")

# ==================== 5 請貴司回覆 ====================
s = Sheet('5_請貴司回覆')
s.title('5　請貴司回覆')
s.lines("""
　1. 微調參數（倍率、空載補正）取代 VR1 是否可行？請一併回答 1_微調 的 5 個問題。
　2. 參數讀寫指令（0x30～0x33）與 GET_VERSION 加 CRC 是否可行？指令碼是否需要調整？
　3. 磁滯補償（0x34、0x35）請一併實作；實作方式如有疑問請提出。另請說明驅動是單端還是 H 橋、能否快速洩放線圈電流。
　4. 狀態旗標要用哪幾個 bit？
　5. 下控是否量測線圈或煞車溫度？（若有，我方會再提溫度補償參數）
　6. 以上若可行，預估完成時間？
""")

wb.save(OUT)
print('輸出', OUT)
