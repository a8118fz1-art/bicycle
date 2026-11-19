"""
新增指令的封包範例。
格式與廠商協定（EMS Bike UART通訊協定-2026-06-12.pdf）相同：
    55 AA LEN CMD DATA CRC_L CRC_H 0D；LEN = CMD + DATA；CRC16/CCITT-FALSE 涵蓋 LEN+CMD+DATA。
ACK 格式沿用原協定：F0 + 被回應的 CMD + ACK_RESULT。
"""
import struct

def crc16(b):
    c = 0xFFFF
    for x in b:
        c ^= x << 8
        for _ in range(8): c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c

def frame(cmd, data=b''):
    body = bytes([1 + len(data), cmd]) + data
    c = crc16(body)
    return ' '.join(f'{x:02X}' for x in b'\x55\xAA' + body + bytes([c & 0xFF, c >> 8, 0x0D]))

# 廠商協定附錄 A 的原始範例：用來證明本程式的格式與 CRC 和原協定一致
VENDOR_APPENDIX = [
    ('A-1 SET_CONTROL KP=80', 0x10, bytes([0, 0x50, 0]), '55 AA 04 10 00 50 00 12 8D 0D'),
    ('A-2 SET_CONTROL ERG=250', 0x10, bytes([1, 0xFA, 0]), '55 AA 04 10 01 FA 00 97 48 0D'),
    ('A-3 SET_CONTROL DUTY=50.0%', 0x10, bytes([2, 0xF4, 1]), '55 AA 04 10 02 F4 01 E9 22 0D'),
    ('A-1 ACK OK', 0xF0, bytes([0x10, 0]), '55 AA 03 F0 10 00 3D FF 0D'),
    ('A-4 START', 0x01, b'', '55 AA 01 01 1F 3E 0D'),
    ('A-5 STOP', 0x02, b'', '55 AA 01 02 7C 0E 0D'),
    ('A-8 HEARTBEAT', 0x40, b'', '55 AA 01 40 FA 66 0D'),
    ('A-9 GET_VERSION', 0x20, b'', '55 AA 01 20 5C 0A 0D'),
    ('A-9 VERSION 回應', 0x20, bytes([1, 0, 0]), '55 AA 04 20 01 00 00 74 98 0D'),
    ('A-10 SYSTEM_INFO 回應', 0x81, bytes([0x8F, 0x0C, 1, 0, 0]), '55 AA 06 81 8F 0C 01 00 00 40 FE 0D'),
    ('A-11 ACK_PARAM_ERROR', 0xF0, bytes([0x10, 2]), '55 AA 03 F0 10 02 7F DF 0D'),
    ('A-14 ACK_UNKNOWN_CMD', 0xF0, bytes([0x99, 4]), '55 AA 03 F0 99 04 B9 1E 0D'),
    ('A-15 ACK_INVALID_STATE', 0xF0, bytes([0x01, 5]), '55 AA 03 F0 01 05 DA 9F 0D'),
]

DEFAULT = [2.374758, 0.00899796, 1.6251, 12.4604, 1.5790, 0.010934, 1.000, 0.353, 2.0]

EXAMPLES = [
    # (說明, 方向, CMD, DATA)
    ('SET_PARAM：參數 6（扭力倍率）= 1.0000', '上 → 下', 0x30, bytes([6]) + struct.pack('<f', 1.0)),
    ('　→ 成功：ACK_OK', '下 → 上', 0xF0, bytes([0x30, 0])),
    ('　→ 數值超出範圍或編號錯：ACK_PARAM_ERROR', '下 → 上', 0xF0, bytes([0x30, 2])),
    ('　→ 不在 STOP 狀態：ACK_INVALID_STATE', '下 → 上', 0xF0, bytes([0x30, 5])),
    ('　→ 舊韌體不認得：ACK_UNKNOWN_CMD', '下 → 上', 0xF0, bytes([0x30, 4])),
    ('SET_PARAM：參數 6 = 1.0234', '上 → 下', 0x30, bytes([6]) + struct.pack('<f', 1.0234)),
    ('SET_PARAM：參數 0（a）= 2.374758', '上 → 下', 0x30, bytes([0]) + struct.pack('<f', 2.374758)),
    ('SET_PARAM：參數 7（磁滯係數 k）= 0.353', '上 → 下', 0x30, bytes([7]) + struct.pack('<f', 0.353)),
    ('GET_PARAM：讀參數 6', '上 → 下', 0x31, bytes([6])),
    ('　→ PARAM_VALUE 回應：參數 6 = 1.0234', '下 → 上', 0x82, bytes([6]) + struct.pack('<f', 1.0234)),
    ('SAVE_PARAMS', '上 → 下', 0x32, b''),
    ('　→ 存檔完成：ACK_OK', '下 → 上', 0xF0, bytes([0x32, 0])),
]

def rows():
    return [(name, d, f'0x{cmd:02X}', len(data) + 1, frame(cmd, data)) for name, d, cmd, data in EXAMPLES]

def verify_vendor():
    return [(n, frame(c, d) == want) for n, c, d, want in VENDOR_APPENDIX]

if __name__ == '__main__':
    import sys; sys.stdout.reconfigure(encoding='utf-8')
    for n, ok in verify_vendor(): print('✔' if ok else '✘', n)
    for r in rows(): print(*r, sep=' | ')
