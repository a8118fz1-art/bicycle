"""ems_mock.py — EMS 下控模擬器

依 2026-08 廠商回饋模擬下控行為，讓上控（index.html / uart_test.html）
在沒有實機的情況下就能驗證完整序列：

  * SET_CONTROL(0x10) 只設定參數，阻力仍為 OFF
  * START(0x01) 之後阻力才 ON；ON 狀態下可直接再送 SET_CONTROL 改值
  * 阻力 ON 時連續 3 秒未收到上控封包 → 阻力自動 OFF + ERR_COMM_TIMEOUT
  * 連續 30 秒未收到上控封包 → 模擬斷電（程式結束）
  * STATUS_REPORT 每 100 ms 回報一次
  * est_current 依 +32V 線圈實測上限 1.5 A @ DUTY 100% 換算

用法：
    python -m pip install pyserial
    python tools/ems_mock.py COM6
    python tools/ems_mock.py COM6 --rpm 90       # 固定模擬踩踏轉速
    python tools/ems_mock.py --selftest          # 不需硬體，驗證狀態機
"""

import argparse
import sys
import time

SOF = b"\x55\xAA"
EOF = 0x0D

CMD_START, CMD_STOP, CMD_RESET_ERROR, CMD_SHUTDOWN = 0x01, 0x02, 0x03, 0x06
CMD_SET_CONTROL, CMD_GET_VERSION, CMD_GET_SYSTEM_INFO, CMD_HEARTBEAT = 0x10, 0x20, 0x21, 0x40
CMD_STATUS_REPORT, CMD_SYSTEM_INFO, CMD_ACK, CMD_ERROR_REPORT = 0x80, 0x81, 0xF0, 0xF1

ACK_OK, ACK_CRC_ERROR, ACK_PARAM_ERROR, ACK_BUSY, ACK_UNKNOWN_CMD, ACK_INVALID_STATE = range(6)

MODE_KP, MODE_ERG, MODE_DUTY = 0, 1, 2

STATUS_READY, STATUS_RUNNING, STATUS_TARGET_REACHED, STATUS_ERG_LIMIT = 0x01, 0x02, 0x04, 0x08
ERR_NONE, ERR_COMM_TIMEOUT, ERR_RPM_FAIL, ERR_POWER_FAIL, ERR_COIL_OUTPUT_FAIL = 0x00, 0x01, 0x02, 0x04, 0x08

COMM_TIMEOUT_S = 3.0        # 阻力自動 OFF
POWER_OFF_TIMEOUT_S = 30.0  # 下控斷電
REPORT_INTERVAL_S = 0.1
COIL_MAX_CURRENT_MA = 1500  # +32V, DUTY 100% 實測約 1.5 A


def crc16_ccitt(data) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def build_packet(cmd: int, payload: bytes = b"") -> bytes:
    body = bytes([1 + len(payload), cmd]) + payload
    crc = crc16_ccitt(body)
    return SOF + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF, EOF])


def parse_frames(buf: bytearray):
    """從緩衝區取出所有完整封包，回傳 (frames, crc_errors)。buf 會被原地消耗。"""
    frames, crc_errors = [], 0
    while True:
        i = buf.find(SOF)
        if i < 0:
            del buf[:max(0, len(buf) - 1)]
            return frames, crc_errors
        if len(buf) < i + 3:
            del buf[:i]
            return frames, crc_errors
        length = buf[i + 2]
        total = 3 + length + 3
        if len(buf) < i + total:
            del buf[:i]
            return frames, crc_errors
        frame = bytes(buf[i:i + total])
        del buf[:i + total]
        if frame[-1] != EOF:
            crc_errors += 1
            continue
        crc_rx = frame[3 + length] | (frame[4 + length] << 8)
        if crc16_ccitt(frame[2:3 + length]) != crc_rx:
            crc_errors += 1
            continue
        frames.append((frame[3], frame[4:3 + length]))


class Controller:
    """下控狀態機。與傳輸層無關，方便 --selftest 驗證。"""

    def __init__(self, rpm=0, verbose=True):
        self.mode = MODE_KP
        self.target = 0
        self.output_on = False
        self.error = ERR_NONE
        self.rpm = rpm
        self.verbose = verbose
        self.last_rx = time.monotonic()
        self.powered = True
        self.buf = bytearray()

    def log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    # ---- 對外：餵入收到的位元組，取回要送出的位元組 ----
    def feed(self, data: bytes) -> bytes:
        out = bytearray()
        if data:
            self.buf.extend(data)
            frames, crc_errors = parse_frames(self.buf)
            for _ in range(crc_errors):
                out += build_packet(CMD_ACK, bytes([0x00, ACK_CRC_ERROR]))
            for cmd, payload in frames:
                self.last_rx = time.monotonic()
                out += self.handle(cmd, payload)
        return bytes(out)

    def handle(self, cmd: int, payload: bytes) -> bytes:
        if cmd == CMD_HEARTBEAT:
            return b""  # 協定附錄 A-8：Heartbeat 不需 ACK

        if cmd == CMD_SET_CONTROL:
            if len(payload) < 3:
                return build_packet(CMD_ACK, bytes([cmd, ACK_PARAM_ERROR]))
            mode = payload[0]
            target = payload[1] | (payload[2] << 8)
            if mode not in (MODE_KP, MODE_ERG, MODE_DUTY):
                return build_packet(CMD_ACK, bytes([cmd, ACK_PARAM_ERROR]))
            if mode == MODE_KP and target > 140:
                return build_packet(CMD_ACK, bytes([cmd, ACK_PARAM_ERROR]))
            if mode == MODE_DUTY and target > 1000:
                return build_packet(CMD_ACK, bytes([cmd, ACK_PARAM_ERROR]))
            self.mode, self.target = mode, target
            self.log(f"SET_CONTROL mode={mode} target={target} (output {'ON' if self.output_on else 'OFF'})")
            return build_packet(CMD_ACK, bytes([cmd, ACK_OK]))

        if cmd == CMD_START:
            if self.error:
                return build_packet(CMD_ACK, bytes([cmd, ACK_INVALID_STATE]))
            self.output_on = True
            self.log("START → 阻力輸出 ON")
            return build_packet(CMD_ACK, bytes([cmd, ACK_OK]))

        if cmd == CMD_STOP:
            self.output_on = False
            self.log("STOP → 阻力輸出 OFF")
            return build_packet(CMD_ACK, bytes([cmd, ACK_OK]))

        if cmd == CMD_RESET_ERROR:
            self.error = ERR_NONE
            self.log("RESET_ERROR")
            return build_packet(CMD_ACK, bytes([cmd, ACK_OK]))

        if cmd == CMD_SHUTDOWN:
            self.output_on = False
            self.powered = False
            self.log("SHUTDOWN → EMS OFF, Power OFF HMI")
            return build_packet(CMD_ACK, bytes([cmd, ACK_OK]))

        if cmd == CMD_GET_VERSION:
            return build_packet(CMD_GET_VERSION, bytes([1, 0, 0]))

        if cmd == CMD_GET_SYSTEM_INFO:
            return build_packet(CMD_SYSTEM_INFO, bytes([1, 0, 0, 0]))

        return build_packet(CMD_ACK, bytes([cmd, ACK_UNKNOWN_CMD]))

    # ---- 週期性行為 ----
    def tick(self) -> bytes:
        silent = time.monotonic() - self.last_rx
        if silent > POWER_OFF_TIMEOUT_S:
            self.powered = False
            self.log(f"通訊中斷 {silent:.1f}s → 下控斷電")
            return b""
        if self.output_on and silent > COMM_TIMEOUT_S:
            self.output_on = False
            self.error |= ERR_COMM_TIMEOUT
            self.log(f"通訊中斷 {silent:.1f}s → 阻力自動 OFF, ERR_COMM_TIMEOUT")
        return self.status_report()

    def duty_x10(self) -> int:
        if not self.output_on:
            return 0
        if self.mode == MODE_DUTY:
            return min(1000, self.target)
        if self.mode == MODE_KP:
            return int(min(1000, self.target / 140 * 1000))
        # ERG：以 rpm 粗略回推 duty
        if self.rpm <= 0:
            return 0
        return int(min(1000, self.target / max(1, self.rpm) * 100))

    def status_report(self) -> bytes:
        duty = self.duty_x10()
        est_current = int(COIL_MAX_CURRENT_MA * duty / 1000)
        est_watt = int(self.rpm * est_current / 1000 * 2.2) if self.output_on else 0
        status = STATUS_RUNNING if self.output_on else STATUS_READY
        if self.output_on and self.mode == MODE_ERG and duty >= 1000:
            status |= STATUS_ERG_LIMIT
        payload = (
            self.rpm.to_bytes(2, "little")
            + est_current.to_bytes(2, "little")
            + est_watt.to_bytes(2, "little")
            + duty.to_bytes(2, "little")
            + self.target.to_bytes(2, "little")
            + bytes([self.mode, status, self.error])
        )
        return build_packet(CMD_STATUS_REPORT, payload)


def selftest():
    c = Controller(rpm=90, verbose=True)
    print("--- 1. 只送 SET_CONTROL，阻力應維持 OFF ---")
    c.feed(build_packet(CMD_SET_CONTROL, bytes([MODE_KP, 50, 0])))
    assert not c.output_on, "SET_CONTROL 不應自行開啟阻力"
    assert c.duty_x10() == 0

    print("--- 2. 補送 START，阻力應 ON ---")
    out = c.feed(build_packet(CMD_START))
    frames, _ = parse_frames(bytearray(out))
    assert frames[0][0] == CMD_ACK and frames[0][1][1] == ACK_OK, frames
    assert c.output_on and c.duty_x10() > 0

    print("--- 3. ON 狀態下改值，不需重送 START ---")
    c.feed(build_packet(CMD_SET_CONTROL, bytes([MODE_KP, 100, 0])))
    assert c.output_on and c.target == 100

    print("--- 4. 3 秒無通訊 → 阻力自動 OFF ---")
    c.last_rx -= 3.5
    c.tick()
    assert not c.output_on and c.error & ERR_COMM_TIMEOUT

    print("--- 5. 30 秒無通訊 → 斷電 ---")
    c.last_rx -= 30
    c.tick()
    assert not c.powered

    print("--- 6. 參數越界應回 ACK_PARAM_ERROR ---")
    c2 = Controller(verbose=False)
    out = c2.feed(build_packet(CMD_SET_CONTROL, bytes([MODE_KP, 200, 0])))
    frames, _ = parse_frames(bytearray(out))
    assert frames[0][1][1] == ACK_PARAM_ERROR

    print("\n全部通過：下控狀態機符合廠商描述的行為。")


def serial_main(port_name: str, rpm: int):
    try:
        import serial
    except ImportError:
        print("缺少 pyserial，請執行：python -m pip install pyserial")
        sys.exit(1)

    ser = serial.Serial(port_name, baudrate=19200, bytesize=8,
                        parity="N", stopbits=1, timeout=0.02)
    print(f"下控模擬器已啟動：{port_name} @ 19200 8-N-1，rpm={rpm}")
    ctl = Controller(rpm=rpm)
    next_report = time.monotonic()
    try:
        while ctl.powered:
            data = ser.read(512)
            if data:
                reply = ctl.feed(data)
                if reply:
                    ser.write(reply)
            now = time.monotonic()
            if now >= next_report:
                next_report = now + REPORT_INTERVAL_S
                report = ctl.tick()
                if report:
                    ser.write(report)
    except KeyboardInterrupt:
        print("結束。")
    finally:
        ser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="EMS 下控模擬器")
    ap.add_argument("port", nargs="?", help="COM port，例如 COM6 或 /dev/ttyUSB0")
    ap.add_argument("--rpm", type=int, default=80, help="模擬踩踏轉速")
    ap.add_argument("--selftest", action="store_true", help="不需硬體，驗證狀態機")
    args = ap.parse_args()
    if args.selftest:
        selftest()
    elif args.port:
        serial_main(args.port, args.rpm)
    else:
        ap.print_help()
