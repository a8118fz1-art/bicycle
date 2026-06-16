const APP_VERSION="v16.17-final-erg-reverse-kp-anti-overshoot";

const FTMS_SERVICE=0x1826,INDOOR_BIKE_DATA=0x2AD2,CONTROL_POINT=0x2AD9;
let device,server,service,bikeChar,cpChar,currentKP=0,activeMode="NONE",controlArmed=false,lastSendAt=0,testTimer=null,testRunning=false,forceZero=false,sendKpInFlight=false;
let commMode="NONE";
// Web Serial runtime objects
let serialPort=null, serialReader=null, serialWriter=null;
let latestRpm=0,lastErgRpm=0,currentErgKP=null,lastErgSendAt=0,ergTargetWatt=0;
const POWER_RPM_POINTS=[10,20,30,40,50,60,70,80,90,100],POWER_TABLE=[{kp:0,p:[4.4,12.1,18.8,27.4,35.5,44.0,52.3,60.5,68.5,77.0]},{kp:1,p:[3.1,8.1,12.0,18.6,22.5,29.4,35.8,42.0,48.5,55.0]},{kp:2,p:[4.2,10.1,17.6,24.1,32.8,38.9,48.6,58.0,67.0,76.0]},{kp:3,p:[5.7,13.9,25.3,33.6,47.3,54.3,69.4,82.0,94.0,106.0]},{kp:4,p:[7.7,18.5,35.5,45.7,65.9,75.3,96.5,113.0,130.0,147.0]},{kp:5,p:[10.0,25.5,47.8,62.5,88.3,100.8,128.4,150.0,171.0,192.0]},{kp:6,p:[12.0,34.0,64.6,82.7,116.5,131.0,168.3,196.0,224.0,252.0]},{kp:7,p:[14.5,44.3,81.7,106.3,146.6,168.0,209.8,245.0,280.0,315.0]},{kp:8,p:[17.0,44.3,103.7,132.9,182.3,209.3,258.4,303.0,348.0,393.0]},{kp:9,p:[27.1,75.3,117.2,181.4,215.3,287.4,318.9,375.1,403.3,458.0]},{kp:10,p:[32.4,92.2,140.6,214.3,256.8,337.7,392.0,455.0,501.7,566.5]},{kp:11,p:[37.8,109.1,164.0,247.3,298.3,387.9,465.0,535.0,600.0,675.0]},{kp:12,p:[43.1,128.2,189.3,285.6,344.5,445.0,535.0,620.0,702.5,787.5]},{kp:13,p:[48.3,147.2,214.5,323.8,390.6,502.0,605.0,705.0,805.0,900.0]},{kp:14,p:[53.6,166.3,239.8,362.1,436.8,559.1,675.0,790.0,907.5,1012.5]}];
const $=id=>document.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
function log(m){$("log").textContent=`[${new Date().toLocaleTimeString()}] ${m}\n`+$("log").textContent}
function status(m){$("status").textContent=m;log(m)}
function clamp(v,min,max){return Math.max(min,Math.min(max,v))}
function lerp(a,b,t){return a+(b-a)*t}
function hex(v){return Array.from(new Uint8Array(v.buffer,v.byteOffset,v.byteLength)).map(b=>b.toString(16).padStart(2,"0")).join(" ")}
function u16(v,o){return o+1>=v.byteLength?null:v.getUint16(o,true)}
function i16(v,o){return o+1>=v.byteLength?null:v.getInt16(o,true)}
function updateState(){$("armedStatus").textContent=controlArmed?"YES":"NO";$("modeStatus").textContent=activeMode}
function setCommMode(mode){commMode=mode;window.commMode=mode;if(mode==="UART"){$("homeConnectionTitle").textContent="UART";$("homeConnectionText").textContent="UART mode ready";$("homeConnectionIcon").textContent="U";status("UART mode selected for validation.")}else if(mode==="BLE"){$("homeConnectionTitle").textContent="Connection";$("homeConnectionText").textContent="BLE mode ready";$("homeConnectionIcon").textContent="i";status("BLE mode selected.")}else{$("homeConnectionTitle").textContent="Connection";$("homeConnectionText").textContent="No active connection";$("homeConnectionIcon").textContent="i";}}
function setDisplayZero(){["rawRpm","correctedRpm","wattText","rawHex","flagsText","speedText","cadenceText","resistanceText","powerText"].forEach(id=>$(id).textContent="--")}function updateUartStatus(text){const el=$("uartPortStatus");if(el)el.textContent=text}function updateUartTx(text){const el=$("uartLastTx");if(el)el.textContent=text}function updateUartRx(text){const el=$("uartLastRx");if(el)el.textContent=text}function crc16ccitt(bytes){let crc=0xFFFF;for(const b of bytes){crc^=(b<<8);for(let i=0;i<8;i++){if(crc&0x8000){crc=((crc<<1)^0x1021)&0xFFFF;}else{crc=(crc<<1)&0xFFFF;}}}return crc}
function buildUartPacket(cmd,data=[]){const payload=[1+data.length,cmd,...data];const crc=crc16ccitt(payload);return Uint8Array.from([0x55,0xAA,...payload,crc&0xFF,crc>>8,0x0D])}
function formatHex(bytes){return Array.from(bytes).map(b=>b.toString(16).padStart(2,'0')).join(' ')}
function serialLog(message){const pre=$("serialLog"); if(pre) pre.textContent=`[${new Date().toLocaleTimeString()}] ${message}\n` + pre.textContent}
function shouldUseUart(){return commMode==="UART" && serialPort && serialWriter}
async function sendUartControl(cmd,data=[]){
  if(!shouldUseUart()) return false;
  await sendUartThroughSerial(buildUartPacket(cmd,data));
  return true;
}
function uartKpPayload(kp){const value=Math.round(kp*10);return [0x01,value&0xFF,(value>>8)&0xFF]}
function uartWattPayload(watt){const value=Math.round(watt);return [0x02,value&0xFF,(value>>8)&0xFF]}
async function sendUartKP(kp){return await sendUartControl(0x10,uartKpPayload(kp))}
async function sendUartWatt(watt){return await sendUartControl(0x10,uartWattPayload(watt))}
function uartValidate(){
  if(commMode!=="UART"){setCommMode("UART");status("UART validation mode active. Tap Setting again to show sample packet.");return;}
  const packet=buildUartPacket(0x10,[0x01,0xFA,0x00]);
  const hexStr=formatHex(packet);
  status(`UART validation packet built (${packet.length} bytes).`);
  log(`UART sample packet: ${hexStr}`);
  $("homeConnectionText").textContent=`UART packet: ${hexStr}`;
  if(serialPort && serialWriter){
    sendUartThroughSerial(packet);
  }else if(navigator.serial){
    status("Web Serial API available: open a port to send.");
  }else{
    status("Web Serial API unavailable in this browser.");
  }
}

function getSerialSettings(){
  const baudRate = Number($('uartBaudRate')?.value || 19200);
  const dataBits = Number($('uartDataBits')?.value || 8);
  const stopBits = Number($('uartStopBits')?.value || 1);
  const parity = $('uartParity')?.value || 'none';
  return {baudRate,dataBits,stopBits,parity};
}

function applyUartSettings(){
  const settings = getSerialSettings();
  localStorage.setItem('uartSettings', JSON.stringify(settings));
  status(`UART settings saved: ${settings.baudRate}/${settings.dataBits}/${settings.parity}/${settings.stopBits}`);
  updateUartStatus(`READY @ ${settings.baudRate}`);
}

function loadUartSettings(){
  const saved = localStorage.getItem('uartSettings');
  if(!saved) return;
  try{
    const settings = JSON.parse(saved);
    if($('uartBaudRate')) $('uartBaudRate').value = settings.baudRate;
    if($('uartDataBits')) $('uartDataBits').value = settings.dataBits;
    if($('uartParity')) $('uartParity').value = settings.parity;
    if($('uartStopBits')) $('uartStopBits').value = settings.stopBits;
    updateUartStatus(`READY @ ${settings.baudRate}`);
  }catch(e){log('UART settings load failed: '+e.message)}
}

async function openSerial(){
  if(!navigator.serial){status('Web Serial API not supported');return}
  try{
    const port = await navigator.serial.requestPort();
    const settings = getSerialSettings();
    await port.open(settings);
    serialPort = port;
    serialWriter = port.writable.getWriter();
    status('Serial port opened');
    log(`Serial port opened @ ${settings.baudRate}/${settings.dataBits}/${settings.parity}/${settings.stopBits}`);
    updateUartStatus(`OPEN @ ${settings.baudRate}`);
    setCommMode('UART');
    readSerialLoop();
  }catch(e){status('Serial open failed: '+e.message);log(e.message)}
}

async function closeSerial(){
  try{
    if(serialReader){await serialReader.cancel(); serialReader.releaseLock(); serialReader=null}
    if(serialWriter){serialWriter.releaseLock(); serialWriter=null}
    if(serialPort){await serialPort.close(); serialPort=null}
    status('Serial closed');
    updateUartStatus('CLOSED');
    setCommMode('NONE');
  }catch(e){status('Serial close failed: '+e.message);log(e.message)}
}

async function sendUartThroughSerial(packet){
  if(!serialPort || !serialWriter){
    const msg = 'Serial port not open';
    status(msg);
    log(msg);
    updateUartStatus('ERROR');
    const pre = $("serialLog"); if(pre) pre.textContent=`[${new Date().toLocaleTimeString()}] ERROR: ${msg}\n` + pre.textContent;
    return;
  }
  try{
    await serialWriter.write(packet);
    status('UART packet sent');
    const txHex = formatHex(packet);
    log('UART sent: '+txHex);
    updateUartTx(txHex);
    const pre = $("serialLog"); if(pre) pre.textContent=`[${new Date().toLocaleTimeString()}] TX: ${txHex}\n` + pre.textContent;
  }catch(e){
    const msg = 'Serial write failed: '+e.message;
    status(msg);
    log(msg);
    updateUartStatus('ERROR');
    const pre = $("serialLog"); if(pre) pre.textContent=`[${new Date().toLocaleTimeString()}] ERROR: ${msg}\n` + pre.textContent;
  }
}

async function readSerialLoop(){
  if(!serialPort || !serialPort.readable){
    log('Serial read loop not started: no readable stream available.');
    return;
  }
  serialReader = serialPort.readable.getReader();
  let rxBuf = new Uint8Array(0);
  try{
    while(true){
      const {value, done} = await serialReader.read();
      if(done) break;
      if(value && value.length){
        // append
        const tmp = new Uint8Array(rxBuf.length + value.length);
        tmp.set(rxBuf,0);
        tmp.set(value,rxBuf.length);
        rxBuf = tmp;
        // try parse frames
        let res;
        while((res = parseSerialPacket(rxBuf)) !== null){
          const {packet, consumed} = res;
          rxBuf = rxBuf.slice(consumed);
          handleParsedPacket(packet);
        }
      }
    }
  }catch(e){log('Serial read error: '+e.message)}
  finally{try{serialReader.releaseLock()}catch(e){}serialReader=null}
}

function parseSerialPacket(buf){
  // Find SOF
  let s = -1;
  for(let i=0;i<buf.length-1;i++){
    if(buf[i]===0x55 && buf[i+1]===0xAA){ s = i; break }
  }
  if(s<0){
    if(buf.length>0) serialLog(`RAW RX (no SOF yet): ${formatHex(buf.slice(-32))}`);
    return null;
  }
  if(buf.length < s+3) return null; // need LEN
  const LEN = buf[s+2];
  const total = 2 + 1 + LEN + 2 + 1; // SOF(2)+LEN(1)+LEN(CMD+DATA)+CRC(2)+EOF(1)
  if(buf.length < s + total) return null; // wait for more
  const eof = buf[s+total-1];
  if(eof !== 0x0D){
    serialLog(`BAD EOF at offset ${s}: ${formatHex(buf.slice(s, s+Math.min(16, buf.length-s)))}`);
    // corrupt frame, skip SOF
    return {packet:null, consumed: s+2};
  }
  const crcIndex = s + 3 + LEN;
  const crcL = buf[crcIndex];
  const crcH = buf[crcIndex+1];
  const transmitted = (crcH<<8) | crcL;
  const crcRange = Array.from(buf.slice(s+2, s+3+LEN));
  const computed = crc16ccitt(crcRange);
  if(computed !== transmitted){
    serialLog(`CRC MISMATCH cmd=0x${buf[s+3].toString(16).padStart(2,'0')} expected=0x${computed.toString(16).padStart(4,'0')} got=0x${transmitted.toString(16).padStart(4,'0')}`);
    // CRC mismatch: skip this SOF and continue
    return {packet:null, consumed: s+2};
  }
  const payloadStart = s+3; // CMD
  const payload = buf.slice(payloadStart, payloadStart+LEN);
  const cmd = payload[0];
  const data = payload.slice(1);
  const rawBytes = buf.slice(s, s+total);
  return {packet:{cmd, data, rawBytes}, consumed: s+total};
}

function handleParsedPacket(pkt){
  if(!pkt) return;
  const hex = formatHex(pkt.rawBytes);
  const pre=$("serialLog"); if(pre) pre.textContent=`[${new Date().toLocaleTimeString()}] FRAME RX: ${hex}\n` + pre.textContent;
  updateUartRx(hex);
  log('Parsed frame cmd=0x'+pkt.cmd.toString(16).padStart(2,'0'));
  if(pkt.cmd===0x80){
    // STATUS_REPORT, expect 13 bytes
    if(pkt.data.length>=13){
      const dv = new DataView(pkt.data.buffer, pkt.data.byteOffset, pkt.data.byteLength);
      const rpm = dv.getUint16(0,true);
      const est_current = dv.getUint16(2,true);
      const est_watt = dv.getUint16(4,true);
      const duty_x10 = dv.getUint16(6,true);
      const target_value = dv.getUint16(8,true);
      const mode = dv.getUint8(10);
      const statusFlag = dv.getUint8(11);
      const errorFlag = dv.getUint8(12);
      $("rawRpm").textContent = rpm>0?rpm.toString():"--";
      $("powerText").textContent = est_watt>0?est_watt+" W":"--";
      $("rawHex").textContent = hex;
      log(`STATUS_REPORT RPM=${rpm} W=${est_watt} MODE=${mode.toString(16)} STATUS=0x${statusFlag.toString(16)} ERR=0x${errorFlag.toString(16)}`);
    }
  }
}
function rpmCorrect(speed){if(forceZero||speed==null||speed<=0)return 0;return speed<=4.92?speed*2.03:speed*2.44}
function pAt(row,rpm){const xs=POWER_RPM_POINTS,ys=row.p;if(rpm<=xs[0]){const s=(ys[1]-ys[0])/(xs[1]-xs[0]);return Math.max(0,ys[0]+s*(rpm-xs[0]))}if(rpm>=xs[xs.length-1]){const n=xs.length,s=(ys[n-1]-ys[n-2])/(xs[n-1]-xs[n-2]);return Math.max(0,ys[n-1]+s*(rpm-xs[n-1]))}for(let i=0;i<xs.length-1;i++)if(rpm>=xs[i]&&rpm<=xs[i+1])return lerp(ys[i],ys[i+1],(rpm-xs[i])/(xs[i+1]-xs[i]));return 0}
function powerCorrect(kp,rpm){if(rpm<=0)return 0;const t=POWER_TABLE;if(kp<=t[0].kp)return pAt(t[0],rpm);if(kp>=t[t.length-1].kp)return pAt(t[t.length-1],rpm);for(let i=0;i<t.length-1;i++){const a=t[i],b=t[i+1];if(kp>=a.kp&&kp<=b.kp)return lerp(pAt(a,rpm),pAt(b,rpm),(kp-a.kp)/(b.kp-a.kp))}return 0}
window.powerCorrect=powerCorrect;

function kpForTargetWatt(targetWatt,rpm){
  if(!rpm||rpm<=0)return 0.1;
  const rows=POWER_TABLE;
  const w=Number(targetWatt||0);
  if(w<=0)return 0.1;
  const minW=pAt(rows[1]||rows[0],rpm);
  if(w<=minW)return 0.1;
  for(let i=1;i<rows.length-1;i++){
    const a=rows[i],b=rows[i+1],wa=pAt(a,rpm),wb=pAt(b,rpm);
    if(w>=wa&&w<=wb){
      const t=(w-wa)/(wb-wa||1);
      return clamp(lerp(a.kp,b.kp,t),0.1,14);
    }
  }
  return 14;
}
async function sendErgKP(kp){
  if(!cpChar)return;
  const safe=clamp(Number(kp||0.1),0.1,14);
  const r=Math.round(safe*10);
  await writeCP([0x04,r&255,(r>>8)&255],true);
  currentKP=safe;
  log(`ERG reverse KP sent=${safe.toFixed(1)} / Resistance=${r}`);
}
async function updateErgReverseControl(rpm){
  if(activeMode!=="ERG"||!controlArmed||forceZero||!cpChar||rpm<=0)return;
  const now=Date.now();
  if(now-lastErgSendAt<450)return;
  const target=ergTargetWatt||Number($("targetWatt").value||0);
  const base=kpForTargetWatt(target,rpm);
  const rpmRise=Math.max(0,rpm-lastErgRpm);
  const antiOvershoot=clamp(rpmRise*0.10,0,1.0);
  const desired=clamp(base-antiOvershoot,0.1,14);
  if(currentErgKP==null)currentErgKP=desired;
  let next=currentErgKP;
  if(desired<currentErgKP){
    next=Math.max(desired,currentErgKP-0.8); // fast down
  }else{
    next=Math.min(desired,currentErgKP+0.2); // slow up
  }
  next=Math.round(next*10)/10;
  if(Math.abs(next-currentErgKP)>=0.1 || Math.abs(next-currentKP)>=0.1){
    currentErgKP=next;
    lastErgSendAt=now;
    await sendErgKP(next);
  }
  lastErgRpm=rpm;
}

function parseBike(v){const flags=u16(v,0);let o=2,d={flags,rawHex:hex(v),speedKph:null,cadenceRpm:null,resistance:null,power:null};if((flags&1)===0){const sp=u16(v,o);d.speedKph=sp==null?null:sp/100;o+=2}if(flags&2)o+=2;if(flags&4){const c=u16(v,o);d.cadenceRpm=c==null?null:c/2;o+=2}if(flags&8)o+=2;if(flags&16)o+=3;if(flags&32){d.resistance=i16(v,o);o+=2}if(flags&64){d.power=i16(v,o);o+=2}return d}
function isIdleLoadState(){
  // 空載判定：尚未控制、NONE 模式、或測試/休息段送出 KP=0 時，都只使用 KP=0 實測表。
  return !controlArmed || activeMode==="NONE" || (activeMode==="KP" && currentKP<=0);
}
function onBike(e){
  if(forceZero)return;
  try{
    const d=parseBike(e.target.value);
    $("rawHex").textContent=d.rawHex;
    $("flagsText").textContent="0x"+d.flags.toString(16).padStart(4,"0");
    $("speedText").textContent=d.speedKph==null?"--":d.speedKph.toFixed(2)+" km/h";
    $("cadenceText").textContent=d.cadenceRpm==null?"--":d.cadenceRpm.toFixed(1)+" rpm";
    $("resistanceText").textContent=d.resistance==null?"--":d.resistance;
    $("powerText").textContent=d.power==null?"--":d.power+" W";
    const speedBase=d.speedKph!=null?d.speedKph:0;
    const rpm=rpmCorrect(speedBase);
    latestRpm=rpm;
    if(activeMode==="ERG"&&rpm>0)updateErgReverseControl(rpm);
    let p=0,wattDisplayArmed=false;

    if(rpm>0 && isIdleLoadState()){
      p=powerCorrect(0,rpm);
      wattDisplayArmed=true;
    }else if(activeMode==="ERG"){
      p=Number($("targetWatt").value||0);
      wattDisplayArmed=controlArmed;
    }else if(activeMode==="KP"){
      p=powerCorrect(currentKP,rpm);
      wattDisplayArmed=controlArmed&&rpm>0;
    }

    $("rawRpm").textContent=speedBase>0?speedBase.toFixed(2):"--";
    $("correctedRpm").textContent=rpm>0?rpm.toFixed(1):"--";
    $("wattText").textContent=(wattDisplayArmed&&rpm>0)?p.toFixed(1)+" W":((wattDisplayArmed&&p>0)?p.toFixed(1)+" W":"--");
  }catch(err){
    log("BLE parse error: "+err.message);
  }
}
async function connect(){try{forceZero=false;controlArmed=false;activeMode="NONE";currentKP=0;updateState();$("targetKp").value="5.0";status("掃描 FTMS 裝置中...");device=await navigator.bluetooth.requestDevice({filters:[{services:[FTMS_SERVICE]}],optionalServices:[FTMS_SERVICE]});$("deviceName").textContent=device.name||"FTMS Device";device.addEventListener("gattserverdisconnected",()=>{status("BLE disconnected.");$("controlStatus").textContent="--";setDisplayZero();controlArmed=false;activeMode="NONE";updateState()});server=await device.gatt.connect();service=await server.getPrimaryService(FTMS_SERVICE);bikeChar=await service.getCharacteristic(INDOOR_BIKE_DATA);await bikeChar.startNotifications();bikeChar.addEventListener("characteristicvaluechanged",onBike);try{cpChar=await service.getCharacteristic(CONTROL_POINT);$("controlStatus").textContent="Control Point OK";await writeCP([0x00],true);log("已要求 FTMS control.")}catch(e){$("controlStatus").textContent="Control Point unavailable";log(e.message)}status("FTMS 已連線，版本：v16.17-final-erg-reverse-kp-anti-overshoot")}catch(e){status("連線失敗："+e.message)}}
async function writeCP(bytes,urgent=false){if(!cpChar){log("Control Point not ready.");return false}const data=new Uint8Array(bytes);if(!urgent){const now=Date.now();if(now-lastSendAt<150)await sleep(150-(now-lastSendAt))}lastSendAt=Date.now();try{await cpChar.writeValue(data);return true}catch(e1){try{await cpChar.writeValueWithoutResponse(data);return true}catch(e2){log("CP write failed: "+e2.message);return false}}}
async function sendKP(kp,allowZero=false){
  if(sendKpInFlight) return;
  sendKpInFlight=true;
  try{
    forceZero=false;
    controlArmed=true;
    activeMode="KP";
    let v=Number(kp||0);
    currentKP=(allowZero&&v<=0)?0:clamp(v,0.1,14);
    $("targetKp").value=currentKP>0?currentKP.toFixed(1):"0.1";
    const r=Math.round(currentKP*10);
    if(await sendUartKP(currentKP)){
      updateState();
      log(`UART KP sent=${currentKP.toFixed(1)} / Resistance=${r}`);
      return;
    }
    await writeCP([0x00],true);
    await sleep(80);
    await writeCP([0x04,r&255,(r>>8)&255],true);
    updateState();
    log(`已送出 KP=${currentKP.toFixed(1)} / Resistance=${r}`);
  }finally{sendKpInFlight=false}}
async function sendWatt(w){
  forceZero=false;
  controlArmed=true;
  activeMode="ERG";
  const watt=clamp(Math.round(Number(w||0)),0,1200);
  ergTargetWatt=watt;
  currentErgKP=null;
  lastErgRpm=latestRpm;
  if(await sendUartWatt(watt)){
    updateState();
    log(`UART ERG target sent=${watt} W`);
    return;
  }
  await writeCP([0x00],true);
  await sleep(80);
  if(latestRpm>0){
    const kp=kpForTargetWatt(watt,latestRpm);
    currentErgKP=kp;
    lastErgSendAt=Date.now();
    await sendErgKP(kp);
  }else{log("ERG armed: waiting for pedal RPM...")}
  updateState();
  log(`已啟動 ERG Reverse KP Target=${watt} W`);
  if(latestRpm<=0)log("ERG: 等待踩踏 RPM 後自動計算 KP")
}
async function safeZeroStop(){stopTest();log("開始安全歸零序列...");let allOk=true;for(let i=1;i<=3;i++){const s1=await writeCP([0x00],true);await sleep(100);const s2=await writeCP([0x05,0,0],true);await sleep(160);const s3=await writeCP([0x04,0,0],true);await sleep(160);const s4=await writeCP([0x08,0x01],true);await sleep(250);if(!s1||!s2||!s3||!s4)allOk=false;log(`安全歸零序列 ${i}/3 已送出`)}const s5=await writeCP([0x00],true);await sleep(100);const s6=await writeCP([0x04,0,0],true);await sleep(300);if(!s5||!s6)allOk=false;forceZero=true;controlArmed=false;activeMode="NONE";currentKP=0;currentErgKP=null;ergTargetWatt=0;$("targetKp").value="5.0";setDisplayZero();updateState();status(allOk?"已完成安全歸零：Power=0 / Resistance=0 / Stop 重複送出。":"安全歸零部分失敗，請手動確認車輛已停止施力。")}
async function stopOutput(){await safeZeroStop()}
async function disconnect(){await safeZeroStop();await sleep(1000);try{if(bikeChar)bikeChar.removeEventListener("characteristicvaluechanged",onBike)}catch(e){}try{if(device&&device.gatt&&device.gatt.connected)device.gatt.disconnect()}catch(e){}$("deviceName").textContent="--";$("controlStatus").textContent="--";setDisplayZero();controlArmed=false;activeMode="NONE";updateState();setCommMode("NONE");status("已安全歸零並斷線。")}
function setMode(m){$("kpModeBtn").classList.toggle("active",m==="KP");$("ergModeBtn").classList.toggle("active",m==="ERG");$("kpPanel").classList.toggle("hidden",m!=="KP");$("ergPanel").classList.toggle("hidden",m!=="ERG")}
function adj(id,d,min,max){const e=$(id),step=Number(e.step||1);let v=clamp(Number(e.value||0)+d,min,max);e.value=step<1?v.toFixed(1):Math.round(v)}
function stopTest(){testRunning=false;if(testTimer)clearInterval(testTimer);testTimer=null;$("phase").textContent="--";$("timer").textContent="--";log("Test stopped.")}
async function start3Step(){setMode("KP");stopTest();testRunning=true;let ps=[{name:"Step 1",kp:3,sec:60},{name:"Step 2",kp:5,sec:60},{name:"Step 3",kp:7,sec:60}],i=0,st=Date.now();async function apply(){if(i>=ps.length){stopTest();log("3-Step complete.");return}let p=ps[i];$("phase").textContent=p.name+" / "+p.kp+" KP";st=Date.now();await sendKP(p.kp)}await apply();testTimer=setInterval(async()=>{if(!testRunning)return;let p=ps[i],left=Math.max(0,p.sec-(Date.now()-st)/1000);$("timer").textContent=left.toFixed(0)+" s";if(left<=0){i++;await apply()}},1000)}
async function startWingate(){setMode("KP");stopTest();testRunning=true;let kp=Number($("targetKp").value||7.5),st=Date.now();$("phase").textContent="Wingate 30s / "+kp.toFixed(1)+" KP";await sendKP(kp);testTimer=setInterval(()=>{let left=Math.max(0,30-(Date.now()-st)/1000);$("timer").textContent=left.toFixed(0)+" s";if(left<=0){stopTest();log("Wingate complete.")}},1000)}
async function startIntermittent(){setMode("KP");stopTest();testRunning=true;let round=1,work=true,st=Date.now(),workKp=Number($("targetKp").value||7.5);async function apply(){if(round>10){stopTest();log("Intermittent complete.");return}let kp=work?workKp:0;$("phase").textContent=`Round ${round} ${work?"Work":"Rest"} / ${kp.toFixed(1)} KP`;st=Date.now();await sendKP(kp,!work)}await apply();testTimer=setInterval(async()=>{let dur=work?5:20,left=Math.max(0,dur-(Date.now()-st)/1000);$("timer").textContent=left.toFixed(0)+" s";if(left<=0){if(work)work=false;else{work=true;round++}await apply()}},1000)}
$("connectBtn").onclick=connect;
// UART home button uses data-page navigation defined in ui.js.
// Keep it as page navigation only and use the UART TEST page controls for serial send/receive.
$("openSerialBtn").onclick=openSerial;
$("closeSerialBtn").onclick=closeSerial;
$("sendUartPortBtn").onclick=()=>{ const pkt = buildUartPacket(0x10,[0x01,0xFA,0x00]); sendUartThroughSerial(pkt); };
$("saveUartSettingsBtn").onclick=applyUartSettings;
$("stopOutputBtn").onclick=stopOutput;
$("disconnectBtn").onclick=disconnect;
$("kpModeBtn").onclick=()=>setMode("KP");
$("ergModeBtn").onclick=()=>setMode("ERG");
$("kpMinus").onclick=()=>adj("targetKp",-0.1,0.1,14);
$("kpPlus").onclick=()=>adj("targetKp",0.1,0.1,14);
$("wMinus").onclick=()=>adj("targetWatt",-5,0,1200);
$("wPlus").onclick=()=>adj("targetWatt",5,0,1200);
$("sendKpBtn").onclick=()=>sendKP($("targetKp").value);
$("sendWattBtn").onclick=()=>sendWatt($("targetWatt").value);
$("start3Step").onclick=start3Step;
$("startWingate").onclick=startWingate;
$("startIntermittent").onclick=startIntermittent;
$("stopTest").onclick=stopTest;
setMode("KP");updateState();setCommMode("NONE");loadUartSettings();log("[System] v16.17-final-erg-reverse-kp-anti-overshoot ready. ERG uses reverse KP lookup with anti-overshoot. Target KP range = 0.1-14.0.");
