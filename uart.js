/* uart.js - 共用 UART 協定基本函式（CRC16-CCITT / 封包建構 / hex 格式化）
   由 index.html 與 uart_test.html 在 app.js / 內嵌腳本之前載入，
   確保兩端使用同一份實作，避免分歧。 */
function crc16ccitt(bytes){let crc=0xFFFF;for(const b of bytes){crc^=(b<<8);for(let i=0;i<8;i++){if(crc&0x8000){crc=((crc<<1)^0x1021)&0xFFFF;}else{crc=(crc<<1)&0xFFFF;}}}return crc}
function buildUartPacket(cmd,data=[]){const payload=[1+data.length,cmd,...data];const crc=crc16ccitt(payload);return Uint8Array.from([0x55,0xAA,...payload,crc&0xFF,crc>>8,0x0D])}
function formatHex(bytes){return Array.from(bytes).map(b=>b.toString(16).padStart(2,'0')).join(' ')}

/* parseUartFrame(buf, onDiag)
   從位元組串流中取出一個完整封包。回傳：
     null                      → 資料不足，等待更多位元組
     {packet, consumed}        → packet 為 null 表示該段損毀（已跳過 SOF）
   packet = {cmd, data:Uint8Array, rawBytes:Uint8Array}
   由 app.js 與 uart_test.html 共用，避免兩端解析行為分歧。 */
function parseUartFrame(buf,onDiag){
  const diag=onDiag||(()=>{});
  let s=-1;
  for(let i=0;i<buf.length-1;i++){if(buf[i]===0x55&&buf[i+1]===0xAA){s=i;break}}
  if(s<0){
    // 緩衝區尾端剛好是 0x55 時，那是 SOF 被切在兩次 read 之間的正常情況（0x55 已到、
    // 0xAA 還沒），不是雜訊。先前一律示警，導致封包記錄被「RAW RX (no SOF yet): 55」
    // 洗版，真正的 ACK / TIMEOUT 訊息被擠掉。只回報真正無法構成 SOF 開頭的位元組。
    const pending=buf.length>0&&buf[buf.length-1]===0x55?1:0;
    const junk=buf.slice(0,buf.length-pending);
    if(junk.length>0)diag(`RAW RX (no SOF yet): ${formatHex(junk.slice(-32))}`);
    return null;
  }
  if(buf.length<s+3)return null;
  const LEN=buf[s+2];
  const total=2+1+LEN+2+1; // SOF(2)+LEN(1)+LEN(CMD+DATA)+CRC(2)+EOF(1)
  if(buf.length<s+total)return null;
  if(buf[s+total-1]!==0x0D){
    diag(`BAD EOF at offset ${s}: ${formatHex(buf.slice(s,s+Math.min(16,buf.length-s)))}`);
    return {packet:null,consumed:s+2};
  }
  const crcIndex=s+3+LEN;
  const transmitted=(buf[crcIndex+1]<<8)|buf[crcIndex];
  const computed=crc16ccitt(Array.from(buf.slice(s+2,s+3+LEN)));
  if(computed!==transmitted){
    diag(`CRC MISMATCH cmd=0x${buf[s+3].toString(16).padStart(2,'0')} expected=0x${computed.toString(16).padStart(4,'0')} got=0x${transmitted.toString(16).padStart(4,'0')}`);
    return {packet:null,consumed:s+2};
  }
  const payload=buf.slice(s+3,s+3+LEN);
  return {packet:{cmd:payload[0],data:payload.slice(1),rawBytes:buf.slice(s,s+total)},consumed:s+total};
}
