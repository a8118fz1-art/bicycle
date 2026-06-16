import sys
import time
from pathlib import Path

try:
    import serial
except ImportError:
    print('Missing pyserial. Install with: python -m pip install pyserial')
    sys.exit(1)


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def build_uart_packet(cmd: int, payload: bytes) -> bytes:
    length = 1 + len(payload)
    body = bytes([length, cmd]) + payload
    crc = crc16_ccitt(body)
    return bytes([0x55, 0xAA]) + body + bytes([crc & 0xFF, (crc >> 8) & 0xFF, 0x0D])


def parse_hex_bytes(value: str) -> bytes:
    if not value.strip():
        return b''
    return bytes(int(x, 16) for x in value.strip().split())


def main():
    if len(sys.argv) < 2:
        print('Usage: python tools/uart_mock.py <COM_PORT> [--port2 <PAIR_PORT>]')
        print('Example: python tools/uart_mock.py COM5 --port2 COM6')
        sys.exit(1)

    port_name = sys.argv[1]
    port2 = None
    if '--port2' in sys.argv:
        idx = sys.argv.index('--port2')
        if idx + 1 < len(sys.argv):
            port2 = sys.argv[idx + 1]

    ser = serial.Serial(port_name, baudrate=19200, bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                        timeout=0.5)
    print(f'Opened {port_name} @ 19200 8-N-1')
    if port2:
        ser2 = serial.Serial(port2, baudrate=19200, bytesize=serial.EIGHTBITS,
                             parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                             timeout=0.5)
        print(f'Opened pair port {port2} @ 19200 8-N-1')
    else:
        ser2 = None

    def send_status_report(out_ser):
        # Example STATUS_REPORT: RPM=90, current=1500, watt=250, duty=450, target=250, mode=1, status=0x06, error=0x00
        payload = bytearray(13)
        payload[0:2] = (90).to_bytes(2, 'little')
        payload[2:4] = (1500).to_bytes(2, 'little')
        payload[4:6] = (250).to_bytes(2, 'little')
        payload[6:8] = (450).to_bytes(2, 'little')
        payload[8:10] = (250).to_bytes(2, 'little')
        payload[10] = 1
        payload[11] = 0x06
        payload[12] = 0x00
        packet = build_uart_packet(0x80, bytes(payload))
        out_ser.write(packet)
        print('Sent STATUS_REPORT:', packet.hex(' '))

    try:
        while True:
            data = ser.read(1024)
            if data:
                print('RX:', data.hex(' '))
                if ser2:
                    ser2.write(data)
                    continue
                # auto-respond for SET_CONTROL
                if len(data) >= 8 and data[0] == 0x55 and data[1] == 0xAA:
                    length = data[2]
                    cmd = data[3]
                    print(f'Parsed cmd=0x{cmd:02x}, len={length}')
                    if cmd == 0x10:
                        send_status_report(ser)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print('Exiting...')
    finally:
        ser.close()
        if ser2:
            ser2.close()


if __name__ == '__main__':
    main()
