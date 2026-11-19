#!/usr/bin/env python3
"""
建置「EMS Bike TFT 上控 校正頁面規格」xlsx（給 TFT 上控廠商）

用法：
    python tools/reports/build_tft_cal_spec.py [輸出.xlsx]

與 build_param_proposal.py（給下控廠商）的指令與數值對應；下控指令定案後兩份一起更新。
"""
import os, sys
from datetime import date
from openpyxl import Workbook
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proto_examples
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.stdout.reconfigure(encoding='utf-8')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    f'~/Downloads/EMS Bike TFT上控 校正頁面規格_{date.today():%Y%m%d}.xlsx')

# 校正常數（與下控提案一致）
KP_CAL, KP_CHK, ERG_CHK = 5.2, 9.6, 300
KP_NM = 9.8
IDLE_S, HOLD_S, REPS = 60, 30, 3
GAIN_MIN, GAIN_MAX = 0.80, 1.20
IDLE_MIN, IDLE_MAX = 2.0, 3.5
SPREAD = 0.5

F = '微軟正黑體'
TITLE = Font(name=F, size=14, bold=True, color='123C6B')
H2 = Font(name=F, size=12, bold=True, color='123C6B')
BODY = Font(name=F, size=11)
BOLD = Font(name=F, size=11, bold=True)
RED = Font(name=F, size=11, bold=True, color='C0392B')
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
                c.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
            self.r += 1

cal_nm = KP_CAL * KP_NM; chk_nm = KP_CHK * KP_NM

# ==================== 0 說明 ====================
s = Sheet('0_說明')
s.title('EMS Bike TFT 上控　校正頁面規格')
s.lines(f"""
{date.today():%Y-%m-%d}。本文件是「提案」，請貴司評估後回覆，雙方確認後才定案。
""")
s.h('目的')
s.lines("""
　下控將新增「扭力倍率」參數，每台出廠時用功率機量測後寫入，取代目前的 VR1 手動調整。
　請在 TFT 上控的服務選單新增「校正」頁面：操作員只需輸入功率機讀數，上控自動控制負載、計算倍率並寫入下控。
""")
s.h('前提')
s.lines("""
　· 下控韌體需先支援新增指令（SET_PARAM / GET_PARAM / SAVE_PARAMS / GET_PARAM_CRC，見 3_使用的下控指令）。
　　指令碼與格式由下控廠商最後確認，本文件會同步更新。
　· 從現有的服務選單進入，不需另外設計進入方式。
　· 校正紀錄不需儲存；結果只顯示在畫面上。
""")
s.line('★ 所有扭力的輸入與顯示單位都是 N·m（與功率機一致），輸入到小數點後 2 位。', RED)
s.h('本文件各頁')
s.lines("""
　1_畫面流程　　　　：各畫面的動作、輸入與判定
　2_校正常數　　　　：程式內使用的固定數值（集中在一個常數表，之後可能調整）
　3_使用的下控指令　：每一步送出的指令與預期回應
　4_異常處理　　　　：通訊失敗、輸入錯誤、中途離開
　5_請貴司回覆
""")

# ==================== 1 畫面流程 ====================
s = Sheet('1_畫面流程', (16, 34, 30, 44))
s.title('1　畫面流程')
s.lines(f"""
　全程在功率機定轉速 60 rpm 下進行。每次負載都從 KP 0 直接上到目標（不可從高往下降）。
　倒數期間畫面顯示：剩餘秒數、目前 KP 設定、踏頻、下控回報功率。
""")
s.table(['畫面', '上控動作', '操作員', '判定 / 顯示'], [
    ('0 前置檢查', '讀下控版本與參數 CRC、讀目前倍率；即時顯示踏頻、VIN、通訊狀態',
     '按「已冷機（停機 30 分鐘以上）」確認', f'踏頻 60 ±1 rpm、VIN ≥ 23 V、通訊正常，三項都通過才能按「開始」'),
    ('1 空載', f'KP 0，倒數 {IDLE_S} 秒', '輸入功率機扭力讀數（空載）',
     f'{IDLE_MIN}～{IDLE_MAX} N·m。超出時提示「空載異常，請檢查鏈條」，操作員可選「繼續」或「中止」；選繼續時，結果畫面要標示「空載異常」'),
    ('2 量測（第 1～3 次）', f'KP {KP_CAL}，倒數 {HOLD_S} 秒 → KP 0，倒數 {IDLE_S} 秒',
     '負載倒數結束時輸入讀數；空載倒數結束時輸入讀數', f'淨扭力 = 負載讀數 − 前後兩次空載讀數平均。3 次做完，最大與最小差 > {SPREAD} N·m 時提示「讀數不穩定」並重做畫面 2'),
    ('3 計算與寫入', '計算新倍率 = 舊倍率 × 3 次淨扭力平均 ÷ ' + f'{cal_nm:.2f}',
     '確認數值後按「寫入」', f'顯示 3 次淨扭力、平均、舊倍率、新倍率。新倍率超出 {GAIN_MIN:.2f}～{GAIN_MAX:.2f}：顯示「超出範圍，請回報」，不可寫入'),
    ('4 驗證', f'依序：KP {KP_CAL}（{HOLD_S} 秒）→ KP 0（{IDLE_S} 秒）→ KP {KP_CHK}（{HOLD_S} 秒）→ KP 0（{IDLE_S} 秒）→ ERG {ERG_CHK} W（{HOLD_S} 秒）→ KP 0',
     '每一段結束輸入讀數（ERG 段輸入功率機「功率」W）', f'KP {KP_CAL}：淨扭力 {cal_nm:.1f} ±1%；KP {KP_CHK}：淨扭力 {chk_nm:.1f} ±2%；ERG {ERG_CHK} W：功率機功率 ±5%'),
    ('5 結果', 'KP 0', '按「完成」離開', '顯示「合格」或「不合格」與各項數值。KP 9.6 不合格時顯示「曲線不符，請回報，勿再調整」'),
])
s.r += 1
s.h('其他按鈕（畫面 0 與 5）')
s.lines("""
　· 「恢復上次倍率」：寫回本次校正前讀到的倍率並存檔（只在本次校正有寫入時可用）。
　· 「恢復 1.000」：倍率寫回 1.000 並存檔。
　· 兩個按鈕都要再跳一次確認。
""")

# ==================== 2 校正常數 ====================
s = Sheet('2_校正常數', (26, 14, 70))
s.title('2　校正常數（請集中在程式的常數表）')
s.table(['項目', '數值', '說明'], [
    ('校正點', f'KP {KP_CAL}', f'= {cal_nm:.2f} N·m 淨扭力（1 kp = {KP_NM} N·m）'),
    ('檢查點', f'KP {KP_CHK}', f'= {chk_nm:.1f} N·m；確認曲線形狀'),
    ('驗收點', f'ERG {ERG_CHK} W', '確認下控回報與實際功率一致'),
    ('空載等待', f'{IDLE_S} 秒', ''),
    ('負載停留', f'{HOLD_S} 秒', '操作員讀倒數最後 15 秒的平均或穩定值'),
    ('重複次數', f'{REPS} 次', ''),
    ('3 次差距上限', f'{SPREAD} N·m', '超過則重做'),
    ('空載範圍', f'{IDLE_MIN}～{IDLE_MAX} N·m', '超出只提示，可繼續'),
    ('倍率範圍', f'{GAIN_MIN:.2f}～{GAIN_MAX:.2f}', '超出不寫入'),
    ('KP 5.2 驗證容許', '±1%', f'{cal_nm * 0.99:.1f}～{cal_nm * 1.01:.1f} N·m'),
    ('KP 9.6 驗證容許', '±2%', f'{chk_nm * 0.98:.1f}～{chk_nm * 1.02:.1f} N·m'),
    ('ERG 300 W 驗證容許', '±5%', f'{ERG_CHK * 0.95:.0f}～{ERG_CHK * 1.05:.0f} W'),
    ('前置：踏頻', '60 ±1 rpm', ''),
    ('前置：VIN', '≥ 23 V', '低於此值多半是下控電源接觸問題，請拔插下控電源'),
])

# ==================== 3 使用的下控指令 ====================
s = Sheet('3_使用的下控指令', (52, 9, 7, 5, 75))
s.title('3　使用的下控指令（與下控廠商的「韌體修改規格」一致；以下控廠商最後確認為準）')
s.lines("""
　封包格式與原協定相同：55 AA LEN CMD DATA CRC_L CRC_H 0D。數值 little-endian。扭力倍率 = 參數編號 6（float32）。
　ACK 沿用原協定：F0 + 被回應的 CMD + 結果（0 OK、2 PARAM_ERROR、4 UNKNOWN_CMD、5 INVALID_STATE）。
""")
s.table(['時機', '送出', '預期回應', '處理'], [
    ('畫面 0', 'GET_VERSION (0x20)', '0x20 版本（格式不變）', '顯示'),
    ('畫面 0', 'GET_PARAM_CRC (0x36)', '0x84 + CRC16', '顯示供核對；若回 ACK UNKNOWN_CMD(4)：顯示「下控韌體不支援校正」並停止'),
    ('畫面 0', 'GET_PARAM (0x31) 編號 6', '0x82 + 編號 + float32', '記為「舊倍率」'),
    ('畫面 0', 'GET_SYSTEM_INFO (0x21)', '0x81（含 VIN）', '檢查 VIN ≥ 23 V'),
    ('畫面 1、2、4', 'SET_CONTROL (0x10) KP / ERG、START', 'ACK OK', '與現有用法相同'),
    ('畫面 3', 'STOP (0x02)', 'ACK OK', '參數只能在 STOP 狀態寫入'),
    ('畫面 3', 'SET_PARAM (0x30) 編號 6 + 新倍率', 'ACK OK', 'PARAM_ERROR / INVALID_STATE → 見 4_異常處理'),
    ('畫面 3', 'GET_PARAM (0x31) 編號 6', '0x82 + 編號 + float32', '4 byte 與寫入值完全相同才算成功'),
    ('畫面 3', 'SAVE_PARAMS (0x32)', 'ACK OK', '收到 ACK OK 才算完成（寫 flash 可能需要較久，等待至少 1 秒）'),
    ('畫面 3 之後', 'START (0x01)', 'ACK OK', '進入畫面 4'),
    ('「恢復」按鈕', 'STOP → SET_PARAM 6 → GET_PARAM 6 → SAVE_PARAMS → START', '同上', ''),
])
s.ws.column_dimensions['A'].width = 16; s.ws.column_dimensions['B'].width = 40
s.ws.column_dimensions['C'].width = 24; s.ws.column_dimensions['D'].width = 60
s.h('封包範例（CRC 已實際計算；與下控規格相同）')
s.table(['範例', '方向', 'CMD', 'LEN', '完整封包（hex）'], proto_examples.rows())
s.ws.column_dimensions['E'].width = 75
s.r += 1
s.lines("""
　格式核對：同一個程式重算原協定附錄 A 的 13 個範例，全部一致（例：HEARTBEAT = 55 AA 01 40 FA 66 0D）。
""")

# ==================== 4 異常處理 ====================
s = Sheet('4_異常處理', (34, 80))
s.title('4　異常處理')
s.table(['情況', '處理'], [
    ('GET_PARAM_CRC 回 ACK UNKNOWN_CMD', '下控是舊韌體：顯示「下控韌體不支援校正」，不進行校正'),
    ('倒數中踏頻偏離 60 ±1 rpm 超過 3 秒', '暫停倒數並提示，回到 60 rpm 後重新倒數該段'),
    ('通訊中斷 / 指令無回應（重送 3 次仍失敗）', 'KP 0，顯示「通訊失敗」，回到畫面 0'),
    ('SET_PARAM 回 PARAM_ERROR(2)', '顯示「數值超出下控允許範圍」，不存檔'),
    ('SET_PARAM 回 INVALID_STATE(5)', '重送 STOP 後再寫一次；仍失敗顯示「寫入失敗」'),
    ('讀回不一致 / SAVE_PARAMS 無 ACK', '寫回舊倍率（SET_PARAM 6 = 舊倍率），顯示「寫入失敗」。注意：SET_PARAM 寫入 RAM 後立即生效，失敗時一定要寫回舊值'),
    ('操作員中途離開', 'KP 0；未到畫面 3 不寫入任何參數；已寫入未存檔時寫回舊倍率'),
    ('輸入值明顯不合理（負值、> 200 N·m）', '拒絕輸入並提示重新輸入'),
])

# ==================== 5 請貴司回覆 ====================
s = Sheet('5_請貴司回覆')
s.title('5　請貴司回覆')
s.lines("""
　1. 以上畫面流程是否可行？畫面配置可依貴司現有風格調整。
　2. 數字輸入（小數點 2 位）用現有的輸入方式是否可行？
　3. 下控指令定案後，貴司實作需要的時間？
　4. 有無其他需要我方提供的資料？
""")

wb.save(OUT)
print('輸出', OUT)
