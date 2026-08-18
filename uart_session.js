/* uart_session.js — EMS Bike UART 連線階段管理
   依 2026-08 廠商回饋實作：
   1) SET_CONTROL(0x10) 之後必須再送 START(0x01)，阻力輸出才會 ON。
      ON 之後可直接以 SET_CONTROL 切換模式/目標值，不需重送 START。
   2) 阻力 ON 時，下控 3 秒未收到上控封包 → 自動關閉阻力並切回 OFF。
      連續 30 秒未收到上控封包 → 下控直接斷電。
      因此 HEARTBEAT(0x40) 的生命週期綁在「串口開啟 ~ 關閉」，
      而不是「START ~ STOP」——STOP 之後仍需維持心跳，否則 30 秒後整台斷電。
   依賴 uart.js：buildUartPacket / crc16ccitt / formatHex
*/
(function (global) {
  'use strict';

  const CMD = {
    START: 0x01, STOP: 0x02, RESET_ERROR: 0x03, SHUTDOWN: 0x06,
    SET_CONTROL: 0x10, GET_VERSION: 0x20, GET_SYSTEM_INFO: 0x21, HEARTBEAT: 0x40,
    STATUS_REPORT: 0x80, SYSTEM_INFO: 0x81, ACK: 0xF0, ERROR_REPORT: 0xF1
  };
  const CMD_NAME = Object.fromEntries(Object.entries(CMD).map(([k, v]) => [v, k]));

  // 通訊協定 §6 CONTROL_MODE
  const MODE = { KP: 0, ERG: 1, DUTY: 2 };
  const MODE_NAME = { 0: 'KP', 1: 'ERG', 2: 'DUTY' };

  // §8 ACK_RESULT
  const ACK_RESULT = {
    0: 'ACK_OK', 1: 'ACK_CRC_ERROR', 2: 'ACK_PARAM_ERROR',
    3: 'ACK_BUSY', 4: 'ACK_UNKNOWN_CMD', 5: 'ACK_INVALID_STATE'
  };

  // §9 STATUS_FLAG / §10 ERROR_FLAG
  const STATUS_BITS = [[0x01, 'READY'], [0x02, 'RUNNING'], [0x04, 'TARGET_REACHED'], [0x08, 'ERG_LIMIT']];
  const ERROR_BITS = [[0x01, 'COMM_TIMEOUT'], [0x02, 'RPM_FAIL'], [0x04, 'POWER_FAIL'], [0x08, 'COIL_OUTPUT_FAIL']];

  function decodeBits(value, table) {
    const hit = table.filter(([bit]) => value & bit).map(([, name]) => name);
    return hit.length ? hit.join('|') : (value === 0 ? 'NONE' : '0x' + value.toString(16));
  }

  // 目標值換算：KP 以 0.1 為單位（0~140 = 0.0~14.0 KP），ERG 為 Watt，DUTY 為 0.1%
  function encodeTarget(mode, value) {
    if (mode === MODE.KP) return Math.round(Math.max(0, Math.min(14, Number(value) || 0)) * 10);
    if (mode === MODE.DUTY) return Math.round(Math.max(0, Math.min(100, Number(value) || 0)) * 10);
    // ERG: Watt。協定 v0.2 §14：MODE_ERG 接受 0~3000 W，超出範圍下控回 ACK_PARAM_ERROR。
    return Math.round(Math.max(0, Math.min(3000, Number(value) || 0)));
  }

  function decodeStatus(data) {
    if (!data || data.length < 13) return null;
    const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
    const mode = dv.getUint8(10), status = dv.getUint8(11);
    // 協定 v0.2 附錄 D.2：error 為 uint16_t（offset 12），DATA 固定 14 bytes（LEN=0x0F）。
    // v0.1 寫的是 uint8 / 13 bytes，但實機從一開始就送 14 bytes。
    // 仍保留 13 bytes 的退路：萬一遇到舊韌體，以 uint8 解讀即可，
    // 若直接要求 14 會讓整個 STATUS 顯示失效，那是更糟的失敗方式。
    const error = data.length >= 14 ? dv.getUint16(12, true) : dv.getUint8(12);
    return {
      rpm: dv.getUint16(0, true),
      est_current_mA: dv.getUint16(2, true),
      est_watt: dv.getUint16(4, true),
      duty_x10: dv.getUint16(6, true),
      target_value: dv.getUint16(8, true),
      mode, status, error,
      modeName: MODE_NAME[mode] || ('0x' + mode.toString(16)),
      statusText: decodeBits(status, STATUS_BITS),
      errorText: decodeBits(error, ERROR_BITS),
      running: !!(status & 0x02)
    };
  }

  class EmsUartSession {
    /**
     * @param {object} opts
     * @param {(pkt:Uint8Array)=>Promise} opts.write  實際寫入串口的函式
     * @param {(msg:string)=>void} [opts.log]
     * @param {number} [opts.heartbeatMs=1000] 心跳週期，下控 timeout 為 3000ms
     * @param {number} [opts.ackTimeoutMs=600]  等待 ACK 逾時
     * @param {number} [opts.linkTimeoutMs=1000] 多久沒收到 STATUS_REPORT 視為斷線（下控 report 週期 100ms）
     */
    constructor(opts) {
      this.write = opts.write;
      this.log = opts.log || (() => { });
      this.heartbeatMs = opts.heartbeatMs || 1000;
      this.ackTimeoutMs = opts.ackTimeoutMs || 600;
      this.linkTimeoutMs = opts.linkTimeoutMs || 1000;

      this.state = 'IDLE';          // IDLE | READY | RUNNING | FAULT
      this.linkAlive = false;
      this.lastStatus = null;
      this.lastRxAt = 0;
      this.mode = null;
      this.target = null;
      this.controlSet = false;   // 是否已收到 SET_CONTROL 的 ACK_OK（含手動送出的封包）

      this._hbTimer = null;
      this._wdTimer = null;
      this._pendingAck = new Map(); // cmd -> {resolve, timer}

      this.onState = opts.onState || (() => { });
      this.onStatus = opts.onStatus || (() => { });
      this.onAck = opts.onAck || (() => { });
      this.onError = opts.onError || (() => { });
    }

    _setState(s) {
      if (this.state === s) return;
      this.state = s;
      this.onState(s, this);
    }

    /* ---------- 生命週期：串口開啟後呼叫 begin()，關閉前呼叫 end() ---------- */

    begin() {
      this.startHeartbeat();
      this._wdTimer = setInterval(() => {
        const silent = Date.now() - this.lastRxAt;
        if (this.lastRxAt && silent > this.linkTimeoutMs && this.linkAlive) {
          this.linkAlive = false;
          this.log(`LINK LOST：已 ${silent} ms 未收到下控封包`);
          this.onState(this.state, this);
        }
      }, 500);
      this.log(`Session begin：HEARTBEAT ${this.heartbeatMs} ms（下控 timeout 3000 ms / 斷電 30 s）`);
    }

    end() {
      this.stopHeartbeat();
      if (this._wdTimer) clearInterval(this._wdTimer);
      this._wdTimer = null;
      this._pendingAck.forEach(p => { clearTimeout(p.timer); p.resolve(null); });
      this._pendingAck.clear();
      this.linkAlive = false;
      this.controlSet = false;
      this._setState('IDLE');
    }

    startHeartbeat() {
      this.stopHeartbeat();
      this._hbTimer = setInterval(() => { this.sendCmd(CMD.HEARTBEAT).catch(() => { }); }, this.heartbeatMs);
      this.sendCmd(CMD.HEARTBEAT).catch(() => { });
    }

    stopHeartbeat() {
      if (this._hbTimer) clearInterval(this._hbTimer);
      this._hbTimer = null;
    }

    setHeartbeatInterval(ms) {
      this.heartbeatMs = Math.max(100, Number(ms) || 1000);
      if (this._hbTimer) this.startHeartbeat();
    }

    /* ---------- 送出 ---------- */

    async sendCmd(cmd, data = []) {
      const pkt = buildUartPacket(cmd, data);
      await this.write(pkt);
      return pkt;
    }

    // HEARTBEAT 不需 ACK（協定附錄 A-8），其餘 HMI→MCU 指令等 ACK
    async sendAndWaitAck(cmd, data = []) {
      const wait = new Promise(resolve => {
        const timer = setTimeout(() => {
          this._pendingAck.delete(cmd);
          this.log(`ACK TIMEOUT：cmd=0x${cmd.toString(16).padStart(2, '0')}`);
          resolve(null);
        }, this.ackTimeoutMs);
        this._pendingAck.set(cmd, { cmd, resolve, timer });
      });
      await this.sendCmd(cmd, data);
      return wait;
    }

    /* ---------- 高階動作 ---------- */

    async setControl(mode, value) {
      const target = encodeTarget(mode, value);
      const ack = await this.sendAndWaitAck(CMD.SET_CONTROL, [mode & 0xFF, target & 0xFF, (target >> 8) & 0xFF]);
      if (ack && ack.result === 0) {
        this.mode = mode; this.target = target;
      }
      return ack;
    }

    async start() {
      const ack = await this.sendAndWaitAck(CMD.START);
      if (ack && ack.result === 0) this._setState('RUNNING');
      return ack;
    }

    async stop() {
      const ack = await this.sendAndWaitAck(CMD.STOP);
      if (ack && ack.result === 0) this._setState('READY');
      return ack; // 注意：心跳不停，避免 30 秒後下控斷電
    }

    async resetError() { return this.sendAndWaitAck(CMD.RESET_ERROR); }
    async getVersion() { return this.sendAndWaitAck(CMD.GET_VERSION); }
    async getSystemInfo() { return this.sendAndWaitAck(CMD.GET_SYSTEM_INFO); }

    async shutdown() {
      const ack = await this.sendAndWaitAck(CMD.SHUTDOWN);
      this.stopHeartbeat();
      this._setState('IDLE');
      return ack;
    }

    /**
     * 是否可以信任「下控目前正在 RUNNING」。
     * 只看 this.state 不夠：連線中斷後 state 會一直停在最後一次收到的 RUNNING，
     * 那個值已經過期。必須連線還活著、且最近一次 STATUS_REPORT 確實回報 running 才算數。
     */
    _confirmedRunning() {
      return !!(this.linkAlive && this.lastStatus && this.lastStatus.running);
    }

    /**
     * 完整開啟阻力序列：SET_CONTROL → ACK_OK → START → ACK_OK。
     * 只有在確認下控真的還在 RUNNING 時才略過 START。
     */
    async arm(mode, value) {
      const a1 = await this.setControl(mode, value);
      if (!a1) { this.log('ARM 失敗：SET_CONTROL 無 ACK'); return false; }
      if (a1.result !== 0) { this.log(`ARM 失敗：SET_CONTROL ${a1.resultName}`); return false; }
      // 先前這裡是 if (this.state === 'RUNNING') return true，連線中斷時會採信過期的
      // RUNNING 而不送 START，阻力沒開、卻仍回傳 true，按鈕看起來像沒反應。
      if (this._confirmedRunning()) return true;
      if (this.state === 'RUNNING') this.log('RUNNING 狀態未經下控確認（連線中斷或尚無回報），仍送出 START');
      const a2 = await this.start();
      if (!a2) { this.log('ARM 失敗：START 無 ACK'); return false; }
      if (a2.result !== 0) { this.log(`ARM 失敗：START ${a2.resultName}`); return false; }
      this.log(`阻力已 ON：${MODE_NAME[mode]} target=${this.target}`);
      return true;
    }

    /** 已 ON 狀態下調整目標；未 ON 時自動補完整序列 */
    async setTarget(mode, value) {
      // 判斷條件與 arm() 一致：未經下控確認的 RUNNING 不可採信，
      // 否則同樣會只送 SET_CONTROL 而漏掉 START。
      if (this._confirmedRunning()) {
        const ack = await this.setControl(mode, value);
        return !!(ack && ack.result === 0);
      }
      return this.arm(mode, value);
    }

    /** 安全歸零：目標歸 0 後送 STOP，心跳維持 */
    async safeZero(mode = MODE.KP) {
      await this.setControl(mode, 0);
      const ack = await this.stop();
      this.log('已送出目標歸零 + STOP（心跳持續維持）');
      return !!(ack && ack.result === 0);
    }

    /* ---------- 接收 ---------- */

    /** @param {{cmd:number, data:Uint8Array, rawBytes:Uint8Array}} pkt 由 parseSerialPacket 解出的封包 */
    onFrame(pkt) {
      if (!pkt) return;
      this.lastRxAt = Date.now();
      if (!this.linkAlive) { this.linkAlive = true; this.onState(this.state, this); }

      if (pkt.cmd === CMD.ACK) {
        const cmdEchoed = pkt.data[0];
        const result = pkt.data.length > 1 ? pkt.data[1] : 0;
        const info = {
          cmd: cmdEchoed, cmdName: CMD_NAME[cmdEchoed] || ('0x' + cmdEchoed.toString(16)),
          result, resultName: ACK_RESULT[result] || ('0x' + result.toString(16))
        };
        const pending = this._pendingAck.get(cmdEchoed);
        if (pending) { clearTimeout(pending.timer); this._pendingAck.delete(cmdEchoed); pending.resolve(info); }
        if (result === 0) {
          if (cmdEchoed === CMD.SET_CONTROL) {
            this.controlSet = true;
            if (this.state === 'IDLE') this._setState('READY');
          } else if (cmdEchoed === CMD.START) {
            this._setState('RUNNING');
          } else if (cmdEchoed === CMD.STOP) {
            this._setState('READY');
          }
        } else {
          this.log(`ACK NG：${info.cmdName} → ${info.resultName}`);
        }
        this.onAck(info);
        return;
      }

      if (pkt.cmd === CMD.ERROR_REPORT) {
        const code = pkt.data[0] || 0;
        const info = { code, text: decodeBits(code, ERROR_BITS) };
        this._setState('FAULT');
        this.log(`ERROR_REPORT：${info.text}`);
        this.onError(info);
        return;
      }

      if (pkt.cmd === CMD.STATUS_REPORT) {
        const st = decodeStatus(pkt.data);
        if (!st) return;
        this.lastStatus = st;
        this.mode = st.mode; this.target = st.target_value;
        // 以下控回報的 STATUS_FLAG 為準校正本地狀態
        if (st.error) this._setState('FAULT');
        else if (st.running && this.state !== 'RUNNING') this._setState('RUNNING');
        else if (!st.running && this.state === 'RUNNING') {
          this._setState('READY');
          this.log('下控回報阻力已 OFF（可能為 3 秒通訊 TIMEOUT）');
        }
        this.onStatus(st);
        return;
      }

      // GET_VERSION 的回覆直接以 0x20 回帶版本資料；GET_SYSTEM_INFO 以 0x81 回覆
      const infoKey = pkt.cmd === CMD.SYSTEM_INFO ? CMD.GET_SYSTEM_INFO
        : (pkt.cmd === CMD.GET_VERSION ? CMD.GET_VERSION : null);
      if (infoKey !== null) {
        const pending = this._pendingAck.get(infoKey);
        if (pending) {
          clearTimeout(pending.timer);
          this._pendingAck.delete(infoKey);
          pending.resolve({ result: 0, resultName: 'ACK_OK', data: pkt.data });
        }
        if (pkt.cmd === CMD.GET_VERSION && pkt.data.length >= 3) {
          this.log(`VERSION：${pkt.data[0]}.${pkt.data[1]}.${pkt.data[2]}`);
        }
      }
    }
  }

  global.EMS_CMD = CMD;
  global.EMS_MODE = MODE;
  global.EMS_MODE_NAME = MODE_NAME;
  global.EMS_ACK_RESULT = ACK_RESULT;
  global.emsDecodeStatus = decodeStatus;
  global.emsEncodeTarget = encodeTarget;
  global.EmsUartSession = EmsUartSession;
})(window);
