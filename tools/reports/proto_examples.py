"""新增指令的封包範例（與上控 sendCmd 相同：LEN = CMD + DATA，CRC16/CCITT-FALSE 涵蓋 LEN+CMD+DATA，CRC 低位元組在前）"""
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

HYST60 = [240, 149, 95, 51, 11, 0, 0, 0, 0]
EXAMPLES = [
    ('SET_PARAM：參數 6（扭力倍率）= 1.0000', 0x30, bytes([6]) + struct.pack('<f', 1.0)),
    ('SET_PARAM：參數 6 = 1.0234', 0x30, bytes([6]) + struct.pack('<f', 1.0234)),
    ('GET_PARAM：讀參數 6', 0x31, bytes([6])),
    ('GET_PARAM 回應（下控 → 上控）：參數 6 = 1.0234', 0x31, bytes([6]) + struct.pack('<f', 1.0234)),
    ('SET_PARAM：參數 0（a）= 2.374758', 0x30, bytes([0]) + struct.pack('<f', 2.374758)),
    ('SAVE_PARAMS', 0x32, b''),
    ('LOAD_DEFAULTS', 0x33, b''),
    ('SET_HYST_ROW：第 2 行（最高 duty 60）', 0x34, bytes([2]) + struct.pack('<9h', *HYST60)),
    ('GET_HYST_ROW：讀第 2 行', 0x35, bytes([2])),
]

def rows():
    return [(name, f'0x{cmd:02X}', len(data) + 1, frame(cmd, data)) for name, cmd, data in EXAMPLES]

if __name__ == '__main__':
    import sys; sys.stdout.reconfigure(encoding='utf-8')
    # 自我檢查：與上控程式相同的 CRC 實作，用既有 HEARTBEAT 驗證格式
    print('HEARTBEAT', frame(0x40))
    for r in rows(): print(*r, sep=' | ')
