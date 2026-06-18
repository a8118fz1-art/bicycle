/* uart.js - 共用 UART 協定基本函式（CRC16-CCITT / 封包建構 / hex 格式化）
   由 index.html 與 uart_test.html 在 app.js / 內嵌腳本之前載入，
   確保兩端使用同一份實作，避免分歧。 */
function crc16ccitt(bytes){let crc=0xFFFF;for(const b of bytes){crc^=(b<<8);for(let i=0;i<8;i++){if(crc&0x8000){crc=((crc<<1)^0x1021)&0xFFFF;}else{crc=(crc<<1)&0xFFFF;}}}return crc}
function buildUartPacket(cmd,data=[]){const payload=[1+data.length,cmd,...data];const crc=crc16ccitt(payload);return Uint8Array.from([0x55,0xAA,...payload,crc&0xFF,crc>>8,0x0D])}
function formatHex(bytes){return Array.from(bytes).map(b=>b.toString(16).padStart(2,'0')).join(' ')}
