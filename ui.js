(function(){
  const pages={home:"pageHome",freeRide:"pageFreeRide",erg:"pageErg",testMode:"pageTestMode",uartTest:"pageUartTest",threeStep:"pageThreeStep",threeStepResult:"pageThreeStepResult",wingate:"pageWingate",wingateResult:"pageWingateResult",intermittent:"pageIntermittent",intermittentResult:"pageIntermittentResult"};

  let activePage="home";
  function resetErgTimeDistance(){
    ergLiveState.started = false;
    ergLiveState.startAt = 0;
    ergLiveState.lastUpdateAt = 0;
    ergLiveState.distanceKm = 0;
    text("ergTimeView", "--:--");
    text("ergDistanceView", "--.--");
  }

  function showPage(key){
    activePage=key||"home";
    Object.values(pages).forEach(id=>document.getElementById(id)?.classList.remove("active"));
    document.getElementById(pages[key]||pages.home)?.classList.add("active");
    if(key==="uartTest" && typeof window.setCommMode==="function"){
      window.setCommMode("UART");
    }
    if(key==="erg"){
      resetErgTimeDistance();
    }
  }
  document.querySelectorAll("[data-page]").forEach(btn=>btn.addEventListener("click",()=>showPage(btn.dataset.page)));

  document.querySelectorAll(".mirror-stop").forEach(btn=>btn.addEventListener("click",(e)=>{
    e.preventDefault();
    e.stopImmediatePropagation();
    softStopOutputOnly();
  },true));

  let weight=70, age=25, gender="male";
  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
  const text=(id,val)=>{const el=document.getElementById(id); if(el) el.textContent=val;};

  const ergLiveState = {started:false,startAt:0,lastUpdateAt:0,distanceKm:0};
  function formatElapsedTime(ms){
    const totalSec = Math.floor(ms/1000);
    const minutes = String(Math.floor(totalSec/60)).padStart(2,'0');
    const seconds = String(totalSec%60).padStart(2,'0');
    return `${minutes}:${seconds}`;
  }

  function updateErgTimeDistance(rpm, speedText){
    const now = Date.now();
    const hasMovement = Number.isFinite(rpm) && rpm > 0;
    const speed = Number((speedText||"--").replace(/[^0-9.\-]/g,"")).valueOf();
    const validSpeed = Number.isFinite(speed) && speed > 0;

    if(hasMovement){
      if(!ergLiveState.started){
        ergLiveState.started = true;
        ergLiveState.startAt = now;
        ergLiveState.lastUpdateAt = now;
        ergLiveState.distanceKm = 0;
      } else {
        const deltaSec = (now - ergLiveState.lastUpdateAt) / 1000;
        if(validSpeed){
          ergLiveState.distanceKm += speed * deltaSec / 3600;
        }
        ergLiveState.lastUpdateAt = now;
      }
    } else if(ergLiveState.started){
      ergLiveState.lastUpdateAt = now;
    }

    const elapsedMs = ergLiveState.started ? now - ergLiveState.startAt : 0;
    const elapsedText = ergLiveState.started ? formatElapsedTime(elapsedMs) : "--:--";
    const distanceText = ergLiveState.started && validSpeed ? ergLiveState.distanceKm.toFixed(2) : (ergLiveState.started ? ergLiveState.distanceKm.toFixed(2) : "--.--");
    text("ergTimeView", elapsedText);
    text("ergDistanceView", distanceText);
  }

  // Soft STOP for FREE RIDE / ERG: clear load only, keep BLE notifications and live RPM/Watt updates.
  // Do not call app.js stopOutput()/safeZeroStop(), because that sets forceZero and blanks live data.
  async function softStopOutputOnly(){
    const prevKp=document.getElementById("targetKp")?.value||"5.0";
    try{
      if(typeof window.sendKP === "function"){
        await window.sendKP(0,true);
      }
    }catch(err){
      try{ if(typeof window.writeCP === "function") await window.writeCP([0x04,0,0],true); }catch(e){}
    }
    resetErgTimeDistance();
    // Restore the visible target setting for the next ENTER; internal output remains KP=0.
    const targetKp=document.getElementById("targetKp");
    if(targetKp) targetKp.value=Number(prevKp||5).toFixed(1);
    const kpMirror=document.getElementById("kpMirror");
    if(kpMirror) kpMirror.textContent=Number(prevKp||5).toFixed(1)+" KP";
    const statusEl=document.getElementById("status");
    if(statusEl) statusEl.textContent="Load cleared. Live RPM/Watt remains active.";
  }

  function getStep1Kp(genderValue, weightValue){
    const w = Number(weightValue || 0);
    if(genderValue === "female"){
      if(w < 50) return 2;
      if(w < 70) return 3;
      return 4;
    }
    if(w < 60) return 3;
    if(w < 80) return 4;
    return 5;
  }

  function syncStep1Kp(){
    const kp = getStep1Kp(gender, weight);
    text("stepParamKp", kp.toFixed(1));
    // Keep 3-STEP KP auto-sync scoped to the 3-STEP page only.
    // FREE RIDE owns #targetKp / #kpMirror through its own controls.
    if(activePage === "threeStep"){
      const targetKp = document.getElementById("targetKp");
      if(targetKp) targetKp.value = kp.toFixed(1);
      const kpMirror = document.getElementById("kpMirror");
      if(kpMirror) kpMirror.textContent = kp.toFixed(1) + " KP";
    }
  }

  function syncStatus(){
    const status=(document.getElementById("status")?.textContent||"").trim();
    const device=(document.getElementById("deviceName")?.textContent||"").trim();
    const control=(document.getElementById("controlStatus")?.textContent||"").trim();
    const panel=document.getElementById("homeConnectionPanel");
    if(!panel)return;
    panel.classList.remove("connected","failed");
    const icon=document.getElementById("homeConnectionIcon");
    const title=document.getElementById("homeConnectionTitle");
    const msg=document.getElementById("homeConnectionText");
    if(window.commMode==="UART"){
      icon.textContent="U";
      title.textContent="UART";
      msg.textContent="UART validation mode";
      return;
    }
    if(device && device!=="--" && (status.includes("已連線") || control!=="--")){
      panel.classList.add("connected");
      icon.textContent="✓"; title.textContent="Connected Device"; msg.textContent=device;
    }else if(status.includes("失敗") || status.toLowerCase().includes("failed") || status.includes("cancelled")){
      panel.classList.add("failed");
      icon.textContent="!"; title.textContent="Connection Failed"; msg.textContent=status.replace(/^連線失敗[:：]\s*/,"")||"Please reconnect.";
    }else{
      icon.textContent="i"; title.textContent="Connection"; msg.textContent="Tap BLE to connect";
    }
  }

  function cleanWatt(v){return (v||"--").replace(" W","").replace("w","").trim();}
  // Use the final Watt value shown by app.js in the shared live display.
  // This keeps Intermittent/Wingate aligned with the already-validated FREE RIDE Watt display.
  function getCurrentWattNumber(){
    const raw=(document.getElementById("wattText")?.textContent||"--").replace(/[^\d.\-]/g,"");
    const watt=Number(raw);
    return Number.isFinite(watt)?watt:0;
  }
  function syncLive(){
    const rpmText=(document.getElementById("correctedRpm")?.textContent||"--").replace(" rpm","").trim();
    const rpm=Number(rpmText);
    refreshNewTestRpmCache();
    const watt=cleanWatt(document.getElementById("wattText")?.textContent||"--");
    const speedText=document.getElementById("speedText")?.textContent||"--";
    ["freeRpmView","ergRpmView"].forEach(id=>text(id,Number.isFinite(rpm)?rpmText:"--"));
    ["freeWattView","ergWattView"].forEach(id=>text(id,watt||"--"));
    updateErgTimeDistance(rpm, speedText);
    const kp=document.getElementById("targetKp")?.value||"5.0";
    const tw=document.getElementById("targetWatt")?.value||"100";
    text("kpMirror",Number(kp).toFixed(1)+" KP");
    text("targetWattMirror",Number(tw).toFixed(0)+" watt");
    text("ergTargetView",Number(tw).toFixed(0));
    if(!threeStepFlow.running){
      syncStep1Kp();
      text("stepParamTime","10");
      text("stepParamMaxRpm","--");
    }
    text("stepParamRpm",rpm||"--");
    syncStatus();
    if(wingateFlow.running) updateWingateDisplay();
    if(intermittentFlow.running) updateInterDisplay();
  }

  function setWeight(v){
    weight=clamp(Math.round(v*10)/10,30,180);
    text("bodyWeightMirror",weight.toFixed(1));
    const w=document.getElementById("wingateWeight");
    if(w) w.value=weight.toFixed(1);
    syncStep1Kp();
    updateWingateLoad();
    updateInterLoad();
  }
  function setAge(v){age=clamp(Math.round(v),10,100); text("ageMirror",age);}

  function updateWingateLoad(){
    const input=document.getElementById("wingateWeight");
    const load=calcWingateKpFromWeight(input?.value||weight||70);   // v8：ROUND half-up，整數運算
    text("wingateLoad",load.toFixed(1));
    text("wingateLoadCard",load.toFixed(1));
    const kpInput=document.getElementById("targetKp");
    if(kpInput && !wingateFlow.running && activePage === "wingate") kpInput.value=load.toFixed(1);
  }

  /* ==================== 測試模式（依上控規格書 v8，2026-10-22 改寫） ====================
     共通規則（v8 04_Common_UI_State R1～R4）：
       R1 所有計時用單調時間（performance.now），不用 tick 次數遞減
       R2 取消、結束、BACK、REST 切換時 KP 0 必達（連送 3 次，app.js sendKP 忙碌時會丟指令）
       R3 倒數前先送 KP 0；R4 3 → 2 → 1 → GO，GO 才送測試 KP 並開始計時
     功率：即時與統計一律用 #wattText（UART 模式 = 下控 est_watt）；3-STEP 功率曲線用 KP × 踏頻 × 1.026。
     四捨五入：一律十進位 ROUND half-up（同 Excel ROUND），用整數運算，不用浮點 Math.round
     （舊版 62 / 82 / 114 / 134 / 154 kg 會少 0.1 kp）。 */
  const POWER_K = 1.026;                 // = 9.8 × 2π / 60（1 kp = 9.8 N·m），70 P03 已定案
  const SAMPLE_MS = 100;                 // 取樣週期：下控 STATUS_REPORT 10 Hz
  const nowMs = () => performance.now();
  const sleepMs = ms => new Promise(r => setTimeout(r, ms));

  /* 體重 → 0.1 kg 整數；x × 係數 的 ROUND(…, 1)，全用整數算 */
  const w10 = w => Math.round(clamp(Number(w || 0), 30, 180) * 10);
  function roundWeightTimes(w, permille){            // ROUND(w × permille / 1000, 1)
    return Math.floor((w10(w) * permille + 500) / 1000) / 10;
  }
  function roundKpTimes(kp, tenths){                  // ROUND(kp × tenths / 10, 1)，kp 為 0.1 解析度
    const k10 = Math.round(Number(kp) * 10);
    return Math.floor((k10 * tenths + 5) / 10) / 10;
  }
  function getCurrentRpmNumber(){
    const raw=(document.getElementById("correctedRpm")?.textContent||"0").replace(/[^\d.]/g,"");
    const rpm=Number(raw);
    return Number.isFinite(rpm)?rpm:0;
  }
  let lastNewTestValidRpm = 0, lastNewTestValidAt = 0;
  const NEW_TEST_MIN_VALID_RPM = 10;
  const NEW_TEST_RPM_FALLBACK_MS = 1500;
  function refreshNewTestRpmCache(){
    const rpm = getCurrentRpmNumber();
    if(Number.isFinite(rpm) && rpm >= NEW_TEST_MIN_VALID_RPM){ lastNewTestValidRpm = rpm; lastNewTestValidAt = Date.now(); }
    return rpm;
  }
  function getNewTestRpmSample(){
    const rpm = refreshNewTestRpmCache();
    if(Number.isFinite(rpm) && rpm >= NEW_TEST_MIN_VALID_RPM) return rpm;
    if(lastNewTestValidRpm >= NEW_TEST_MIN_VALID_RPM && (Date.now() - lastNewTestValidAt) <= NEW_TEST_RPM_FALLBACK_MS) return lastNewTestValidRpm;
    return 0;
  }
  function averageNumbers(list){
    const valid=list.filter(v=>Number.isFinite(v)&&v>0);
    return valid.length ? valid.reduce((a,v)=>a+v,0)/valid.length : 0;
  }

  /* R2：KP 0 必達。sendKP 正在送別的指令時會直接 return，所以連送 3 次，間隔 300 ms */
  async function sendKpZeroSure(){
    for(let i=0;i<3;i++){
      try{ if(typeof window.sendKP === "function") await window.sendKP(0,true); }catch(e){ console.warn("KP 0 send failed:",e); }
      await sleepMs(300);
    }
  }
  async function sendKpOnce(kp){
    try{ if(typeof window.sendKP === "function") await window.sendKP(kp,false); }catch(e){ console.warn("KP send failed:",e); }
  }
  /* R3 / R4：先送 KP 0，3 → 2 → 1 → GO。show(t) 負責把字顯示到該測試的畫面；flow.token 變了代表被取消 */
  async function countdown(flow, show){
    const token = flow.token;
    await sendKpZeroSure();
    for(const t of ["3","2","1"]){
      if(flow.token !== token) return false;
      show(t); await sleepMs(1000);
    }
    if(flow.token !== token) return false;
    show("GO");
    return true;
  }
  function setSvgContent(id, content){ const svg=document.getElementById(id); if(svg) svg.innerHTML=content; }
  function regression(points){
    const n=points.length;
    const sx=points.reduce((a,p)=>a+p.kp,0), sy=points.reduce((a,p)=>a+p.rpm,0);
    const sxx=points.reduce((a,p)=>a+p.kp*p.kp,0), sxy=points.reduce((a,p)=>a+p.kp*p.rpm,0);
    const d=n*sxx-sx*sx;
    if(Math.abs(d)<1e-9)return null;
    const a=(n*sxy-sx*sy)/d, b=(sy-a*sx)/n, meanY=sy/n;
    const ssTot=points.reduce((s,p)=>s+Math.pow(p.rpm-meanY,2),0);
    const ssRes=points.reduce((s,p)=>s+Math.pow(p.rpm-(a*p.kp+b),2),0);
    return {a,b,r2:ssTot>0?1-(ssRes/ssTot):1};
  }
  function mapPoint(x,y,minX,maxX,minY,maxY){
    const left=55,right=495,top=45,bottom=245;
    return {x:left+(x-minX)/(maxX-minX)*(right-left), y:bottom-(y-minY)/(maxY-minY)*(bottom-top)};
  }

  /* ---------------- 3-STEP（v8 30_TestMode_Menu 6～16、TEST MODE FORMULA） ---------------- */
  const THREE_STEP_REST_SECONDS=120, THREE_STEP_STEP_SECONDS=10;
  const THREE_STEP_MIN_VALID_RPM = 20;
  const threeStepFlow = {running:false,token:0,currentStep:1,phase:"ready",remaining:10,timerId:null,maxRpm:0,
                         rpmSamples:[],results:[],baseKp:4.0,nextStep:1,nextKp:4.0,label:""};
  function calcStep2Kp(kp1,rpmInt){ return kp1 + (rpmInt>=180?3:rpmInt>=150?2:1); }
  function calcStep3Kp(kp2,rpmInt){ return kp2 + (rpmInt>=180?4:rpmInt>=150?3:rpmInt>130?2:1); }   // 剛好 130 → +1
  function setThreeStepKp(kp){
    const v=Number(kp).toFixed(1);
    const targetKp=document.getElementById("targetKp"); if(targetKp)targetKp.value=v;
    text("stepParamKp",v);
    const km=document.getElementById("kpMirror"); if(km)km.textContent=v+" KP";
  }
  function setThreeStepIndicator(step){
    [1,2,3].forEach(n=>{
      const el=document.getElementById("stepIndicator"+n); if(!el)return;
      el.classList.remove("active","running","done");
      if(n<step)el.classList.add("done"); else if(n===step)el.classList.add("running");
    });
  }
  function resetThreeStepIndicator(){
    [1,2,3].forEach(n=>{
      const el=document.getElementById("stepIndicator"+n); if(!el)return;
      el.classList.remove("active","running","done"); if(n===1)el.classList.add("active");
    });
  }
  function updateThreeStepDisplay(){
    const f=threeStepFlow;
    text("stepParamTime",String(f.remaining));
    text("stepParamMaxRpm",f.maxRpm>0?String(Math.round(f.maxRpm)):"--");
    const btn=document.getElementById("start3Step");
    let state="READY", label="ENTER";
    if(f.running && f.phase==="countdown"){ state=f.label; label=f.label; }
    else if(f.running && f.phase==="rest"){ state="REST TO STEP "+f.nextStep; label="REST "+f.remaining+"s"; }
    else if(f.running && f.phase==="work"){ state="STEP "+f.currentStep; label="STEP "+f.currentStep+" / 10s"; }
    text("threeStepState",state);
    if(btn)btn.textContent=label;
  }
  function emptyThreeStepResult(message){
    text("threeStepMaxPower","-- watt");
    text("threeStepMaxPowerKp",message||"No valid RPM data");
    ["threeStepR1","threeStepR2","threeStepR3"].forEach((id,i)=>text(id,threeStepFlow.results[i]?.maxRpm>0?String(Math.round(threeStepFlow.results[i].maxRpm)):"--"));
    text("threeStepFormula","--");
    text("threeStepCalcStatus",message&&message.startsWith("INVALID")?"INVALID":"NO DATA");
    ["threeStepTrainHigh","threeStepTrainHigh2","threeStepTrainMid","threeStepTrainMid2"].forEach(id=>text(id,"--"));
    setSvgContent("threeStepRpmChart",`<text x="120" y="145">${message||"No valid RPM data"}</text><text x="18" y="35">rpm</text><text x="480" y="275">kp</text>`);
    setSvgContent("threeStepPowerChart",`<text x="120" y="145">${message||"No valid RPM data"}</text><text x="18" y="35">watt</text><text x="480" y="275">kp</text>`);
  }
  function renderThreeStepResult(){
    const points=threeStepFlow.results.map(r=>({kp:Number(r.kp),rpm:Number(r.maxRpm),step:r.step}));
    points.forEach((p,i)=>text("threeStepR"+(i+1),p.rpm>0?String(Math.round(p.rpm)):"--"));
    text("threeStepTrainWeight",(w10(weight)/10).toFixed(1));
    if(points.length!==3 || points.some(p=>!Number.isFinite(p.kp)||!Number.isFinite(p.rpm)||p.rpm<=0)){
      emptyThreeStepResult("INVALID: less than 3 valid points – please retest"); return;
    }
    const line=regression(points);
    if(!line){ emptyThreeStepResult("INVALID: regression failed – please retest"); return; }
    if(line.a>=0){ emptyThreeStepResult("INVALID: rpm did not drop with kp (slope ≥ 0) – please retest"); return; }
    // v8：KP 0.0～13.0 每 0.1 kp；Power = KP × 踏頻(KP) × 1.026
    const power=[];
    for(let k10=1;k10<=130;k10++){
      const kp=k10/10, rpm=line.a*kp+line.b, watt=kp*rpm*POWER_K;
      if(Number.isFinite(watt))power.push({kp,rpm,watt});
    }
    const validPower=power.filter(p=>p.rpm>0 && p.watt>0);
    if(!validPower.length){ emptyThreeStepResult("INVALID: no positive calculated power – please retest"); return; }
    const maxP=validPower.reduce((m,p)=>p.watt>m.watt?p:m,validPower[0]);
    text("threeStepMaxPower",Math.round(maxP.watt)+" watt");
    text("threeStepMaxPowerKp","@ "+maxP.kp.toFixed(1)+" kp");
    text("threeStepFormula","rpm="+line.a.toFixed(2)+"×kp+"+line.b.toFixed(1));
    text("threeStepCalcStatus","OK / R² "+line.r2.toFixed(3));
    // 4 項訓練值（TEST MODE FORMULA B16～B20），小數一位、ROUND half-up
    const high=maxP.kp;
    text("threeStepTrainHigh",high.toFixed(1));
    text("threeStepTrainHigh2",roundWeightTimes(weight,125).toFixed(1));
    text("threeStepTrainMid",roundKpTimes(high,6).toFixed(1));
    text("threeStepTrainMid2",roundWeightTimes(weight,77).toFixed(1));

    const minKp=0.1, maxKp=13.0;
    const rpmVals=points.map(p=>p.rpm).concat([line.a*minKp+line.b,Math.max(0,line.a*maxKp+line.b)]).filter(v=>Number.isFinite(v));
    const minRpm=Math.max(0,Math.min(...rpmVals)-10), maxRpm=Math.max(...rpmVals)+10;
    const p1=mapPoint(minKp,line.a*minKp+line.b,minKp,maxKp,minRpm,maxRpm);
    const kpEnd=Math.min(maxKp,line.b/(-line.a));
    const p2=mapPoint(kpEnd,line.a*kpEnd+line.b,minKp,maxKp,minRpm,maxRpm);
    const pointSvg=points.map(p=>{const q=mapPoint(p.kp,p.rpm,minKp,maxKp,minRpm,maxRpm);return `<circle cx="${q.x.toFixed(1)}" cy="${q.y.toFixed(1)}" r="6"/><text x="${(q.x+10).toFixed(1)}" y="${(q.y-10).toFixed(1)}">(${p.kp.toFixed(1)}, ${Math.round(p.rpm)})</text>`;}).join("");
    setSvgContent("threeStepRpmChart",`<line x1="55" y1="245" x2="495" y2="245"/><line x1="55" y1="45" x2="55" y2="245"/><line x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${p2.x.toFixed(1)}" y2="${p2.y.toFixed(1)}" class="chart-line"/>${pointSvg}<text x="18" y="35">rpm</text><text x="480" y="275">kp</text>`);
    const maxWatt=Math.max(...validPower.map(p=>p.watt))*1.1;
    const curve=validPower.map((p,i)=>{const q=mapPoint(p.kp,p.watt,0.1,maxKp,0,maxWatt);return (i===0?"M":"L")+q.x.toFixed(1)+" "+q.y.toFixed(1);}).join(" ");
    const mq=mapPoint(maxP.kp,maxP.watt,0.1,maxKp,0,maxWatt);
    setSvgContent("threeStepPowerChart",`<path d="${curve}" class="chart-line"/><circle cx="${mq.x.toFixed(1)}" cy="${mq.y.toFixed(1)}" r="8"/><text x="${Math.max(80,mq.x-70).toFixed(1)}" y="${Math.max(30,mq.y-18).toFixed(1)}">MAX ${Math.round(maxP.watt)} watt</text><text x="18" y="35">watt</text><text x="480" y="275">kp</text>`);
  }
  /* 一段計時：durationS 秒，每 SAMPLE_MS 叫一次 onTick(elapsedMs)；以單調時間判斷結束 */
  function runTimed(flow, durationS, onTick){
    return new Promise(resolve=>{
      const token=flow.token, t0=nowMs();
      clearInterval(flow.timerId);
      flow.timerId=setInterval(()=>{
        if(flow.token!==token){ clearInterval(flow.timerId); resolve(false); return; }
        const el=nowMs()-t0;
        flow.remaining=Math.max(0,Math.ceil((durationS*1000-el)/1000));
        onTick(el);
        if(el>=durationS*1000){ clearInterval(flow.timerId); flow.timerId=null; resolve(true); }
      },SAMPLE_MS);
    });
  }
  async function threeStepWork(step,kp){
    const f=threeStepFlow;
    f.phase="work"; f.currentStep=step; f.maxRpm=0; f.rpmSamples=[]; f.remaining=THREE_STEP_STEP_SECONDS;
    setThreeStepIndicator(step); setThreeStepKp(kp);
    await sendKpOnce(kp);                                    // WORK 開始才送這一段的 KP
    updateThreeStepDisplay();
    const ok=await runTimed(f,THREE_STEP_STEP_SECONDS,()=>{
      const rpm=getCurrentRpmNumber();
      if(Number.isFinite(rpm)&&rpm>=THREE_STEP_MIN_VALID_RPM){ f.rpmSamples.push(rpm); if(rpm>f.maxRpm)f.maxRpm=rpm; }
      updateThreeStepDisplay();
    });
    if(!ok) return false;
    f.results.push({step,kp:Number(Number(kp).toFixed(1)),maxRpm:f.maxRpm,maxRpmInt:Math.round(f.maxRpm),
                    avgRpm:averageNumbers(f.rpmSamples),sampleCount:f.rpmSamples.length,time:THREE_STEP_STEP_SECONDS});
    document.getElementById("stepIndicator"+step)?.classList.add("done");
    return true;
  }
  async function threeStepRest(nextStep,nextKp){
    const f=threeStepFlow;
    f.phase="rest"; f.nextStep=nextStep; f.nextKp=nextKp; f.remaining=THREE_STEP_REST_SECONDS; f.maxRpm=0; f.rpmSamples=[];
    [1,2,3].forEach(n=>{const el=document.getElementById("stepIndicator"+n); if(!el)return; el.classList.remove("active","running"); if(n<nextStep)el.classList.add("done"); else if(n===nextStep)el.classList.add("active");});
    await sendKpZeroSure();                                  // REST：KP 0（不送 STOP）
    setThreeStepKp(nextKp);                                  // 顯示下一段 KP，WORK 開始才送
    updateThreeStepDisplay();
    return await runTimed(f,THREE_STEP_REST_SECONDS,()=>updateThreeStepDisplay());
  }
  async function startThreeStepFlow(){
    const f=threeStepFlow;
    if(f.running)return;
    f.token++; f.running=true; f.results=[]; f.baseKp=getStep1Kp(gender,weight); f.nextStep=1; f.nextKp=f.baseKp;
    f.phase="countdown";
    if(!await countdown(f,t=>{f.label=t; updateThreeStepDisplay();})) return;
    const kp1=f.baseKp;
    if(!await threeStepWork(1,kp1)) return;
    const kp2=calcStep2Kp(kp1,f.results[0].maxRpmInt);      // 最大踏頻先四捨五入成整數再比門檻
    if(!await threeStepRest(2,kp2)) return;
    if(!await threeStepWork(2,kp2)) return;
    const kp3=calcStep3Kp(kp2,f.results[1].maxRpmInt);
    if(!await threeStepRest(3,kp3)) return;
    if(!await threeStepWork(3,kp3)) return;
    await sendKpZeroSure();                                  // 第 3 段後不休息，KP 0 後直接進結果頁
    f.running=false; f.phase="done";
    [1,2,3].forEach(n=>document.getElementById("stepIndicator"+n)?.classList.add("done"));
    updateThreeStepDisplay(); renderThreeStepResult(); showPage("threeStepResult");
  }
  async function cancelThreeStepFlow(){
    const f=threeStepFlow;
    const wasRunning=f.running;
    f.token++; clearInterval(f.timerId); f.timerId=null;
    f.running=false; f.phase="ready"; f.currentStep=1; f.nextStep=1; f.nextKp=f.baseKp;
    f.remaining=THREE_STEP_STEP_SECONDS; f.maxRpm=0; f.rpmSamples=[];
    resetThreeStepIndicator(); syncStep1Kp(); updateThreeStepDisplay();
    if(wasRunning) await sendKpZeroSure();
  }

  /* ---------------- WINGATE（v8 30_TestMode_Menu 17～26） ---------------- */
  const WINGATE_SECONDS=30;
  const wingateFlow={running:false,token:0,remaining:WINGATE_SECONDS,timerId:null,kp:5.3,samples:[],secondResults:[],label:""};
  const WINGATE_MIN_VALID_RPM=NEW_TEST_MIN_VALID_RPM;
  function calcWingateKpFromWeight(w){ return roundWeightTimes(w,75); }      // ROUND(體重 × 0.075, 1)
  function getWingateKp(){ return calcWingateKpFromWeight(document.getElementById("wingateWeight")?.value||weight||70); }
  function updateWingateDisplay(){
    const f=wingateFlow;
    text("wingateTimeView",f.running&&f.label===""?String(f.remaining):(f.running?f.label:"--"));
    const rpm=getNewTestRpmSample(); text("wingateRpmView",rpm>0?String(Math.round(rpm)):"--");
    const watt=getCurrentWattNumber(); text("wingateWattView",watt>0?String(Math.round(watt)):"--");
    text("wingateStateView",f.running?(f.label||"RUN"):"READY");
    const btn=document.getElementById("startWingate"); if(btn)btn.textContent=f.running?"RUNNING":"START";
  }
  function renderWingateResult(){
    const f=wingateFlow;
    const buckets=Array.from({length:WINGATE_SECONDS},(_,i)=>({sec:i+1,rpms:[],watts:[]}));
    f.samples.forEach(s=>{
      const i=Math.min(WINGATE_SECONDS-1,Math.floor(s.elapsedMs/1000));    // 1 秒時間窗以單調時間切分
      if(s.rpm>=WINGATE_MIN_VALID_RPM)buckets[i].rpms.push(s.rpm);
      if(s.watt>0)buckets[i].watts.push(s.watt);
    });
    f.secondResults=buckets.map(b=>({sec:b.sec,avgRpm:averageNumbers(b.rpms),watt:averageNumbers(b.watts),sampleCount:b.watts.length}));
    const valid=f.secondResults.filter(r=>r.watt>0);
    text("wingateResultKp",f.kp.toFixed(1)); text("wingateSampleCount",String(valid.length));
    if(!valid.length){
      text("wingatePeakPower","--");text("wingateAveragePower","--");text("wingateFatigueIndex","--");
      setSvgContent("wingatePowerChart",'<text x="430" y="215">No valid data</text><text x="8" y="220" transform="rotate(-90 8,220)">POWER (WATT)</text><text x="520" y="405">SECONDS</text>');
      return;
    }
    const peak=Math.max(...valid.map(r=>r.watt)), low=Math.min(...valid.map(r=>r.watt));
    const avg=valid.reduce((a,r)=>a+r.watt,0)/valid.length;
    text("wingatePeakPower",String(Math.round(peak)));
    text("wingateAveragePower",String(Math.round(avg)));
    text("wingateFatigueIndex",(peak>0?(peak-low)/peak*100:0).toFixed(1));   // (Peak − Low) / Peak × 100
    const left=55,right=1045,top=45,bottom=360,maxW=Math.max(peak,1);
    const pts=f.secondResults.map((r,i)=>({x:left+(i/(WINGATE_SECONDS-1))*(right-left),y:r.watt>0?bottom-(r.watt/maxW)*(bottom-top):bottom,w:r.watt}));
    const line=pts.map((p,i)=>(i?"L":"M")+p.x.toFixed(1)+" "+p.y.toFixed(1)).join(" ");
    const pk=pts.reduce((m,p)=>p.w>m.w?p:m,pts[0]);
    setSvgContent("wingatePowerChart",`<line x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}" class="grid-line"/><line x1="${left}" y1="${top}" x2="${left}" y2="${bottom}" class="grid-line"/><path d="${line}" class="chart-line"/><circle cx="${pk.x.toFixed(1)}" cy="${pk.y.toFixed(1)}" r="7"/><text x="${Math.min(pk.x+18,900).toFixed(1)}" y="${Math.max(pk.y-14,25).toFixed(1)}">PEAK ${Math.round(peak)} W</text><text x="8" y="220" transform="rotate(-90 8,220)">POWER (WATT)</text><text x="520" y="405">SECONDS</text>`);
  }
  async function startWingateFlow(){
    const f=wingateFlow;
    if(f.running)return;
    updateWingateLoad();
    f.token++; f.running=true; f.kp=getWingateKp(); f.samples=[]; f.secondResults=[]; f.remaining=WINGATE_SECONDS;
    if(!await countdown(f,t=>{f.label=t; updateWingateDisplay();})) return;
    f.label="";
    await sendKpOnce(f.kp);                                  // GO 時加載
    const ok=await runTimed(f,WINGATE_SECONDS,el=>{
      if(el<WINGATE_SECONDS*1000) f.samples.push({elapsedMs:el,rpm:getNewTestRpmSample(),watt:getCurrentWattNumber()});
      updateWingateDisplay();
    });
    if(!ok) return;
    await sendKpZeroSure();
    f.running=false; updateWingateDisplay(); renderWingateResult(); showPage("wingateResult");
  }
  async function cancelWingateFlow(){
    const f=wingateFlow, wasRunning=f.running;
    f.token++; clearInterval(f.timerId); f.timerId=null;
    f.running=false; f.label=""; f.remaining=WINGATE_SECONDS; f.samples=[]; f.secondResults=[];
    updateWingateDisplay();
    if(wasRunning) await sendKpZeroSure();
  }

  /* ---------------- INTERMITTENT（v8 30_TestMode_Menu 27～40） ---------------- */
  const INTER_WORK_S=5, INTER_REST_S=20, INTER_ROUNDS=10;
  const intermittentFlow={running:false,token:0,round:1,phase:"ready",remaining:INTER_WORK_S,timerId:null,kp:5.3,weight:70,
                          samples:[],wattSamples:[],workJ:0,lastSampleAt:0,maxRpm:0,results:[],label:""};
  const INTER_MIN_VALID_RPM = NEW_TEST_MIN_VALID_RPM;
  function calcInterKpFromWeight(w){ return roundWeightTimes(w,75); }
  function updateInterLoad(){
    const bw=w10(document.getElementById("interWeight")?.value||weight||70)/10;
    intermittentFlow.weight=bw; intermittentFlow.kp=calcInterKpFromWeight(bw);
    text("interKp",intermittentFlow.kp.toFixed(1));
    const kpInput=document.getElementById("targetKp");
    if(kpInput && !intermittentFlow.running && activePage === "intermittent") kpInput.value=intermittentFlow.kp.toFixed(1);
  }
  function clearInterTable(){
    const body=document.getElementById("interDataBody"); if(!body)return;
    body.innerHTML=Array.from({length:INTER_ROUNDS},(_,i)=>`<tr><td>${i+1}</td><td>--</td><td>--</td><td>--</td><td>--</td></tr>`).join("");
  }
  function updateInterTable(){
    const body=document.getElementById("interDataBody"); if(!body)return;
    body.innerHTML=Array.from({length:INTER_ROUNDS},(_,i)=>{
      const r=intermittentFlow.results[i];
      if(!r)return `<tr><td>${i+1}</td><td>--</td><td>--</td><td>--</td><td>--</td></tr>`;
      return `<tr><td>${r.round}</td><td>${r.kp.toFixed(1)}</td><td>${r.avgRpm>0?Math.round(r.avgRpm):"--"}</td><td>${r.avgWatt>0?Math.round(r.avgWatt):"--"}</td><td>${r.sampleCount}</td></tr>`;
    }).join("");
  }
  function updateInterDisplay(){
    const f=intermittentFlow;
    text("interRoundView",f.running?String(f.round):"--");
    text("interPhaseView",f.running?(f.label||f.phase.toUpperCase()):"READY");
    text("interTimeView",f.running&&!f.label?String(f.remaining):"--");
    const rpm=getNewTestRpmSample(); text("interRpmView",rpm>0?String(Math.round(rpm)):"--");
    const watt=getCurrentWattNumber(); text("interWattView",watt>0?String(Math.round(watt)):"--");
    const btn=document.getElementById("startIntermittent"); if(btn)btn.textContent=f.running?"RUNNING":"START";
  }
  function renderInterResult(){
    const f=intermittentFlow;
    const valid=f.results.filter(r=>r.avgWatt>0);
    text("interResultKp",f.kp.toFixed(1));
    const chart=document.getElementById("interBarChart");
    if(!valid.length){
      ["interPeakPower","interAveragePower","interFatigueIndex","interMaxRpm","interTotalWork"].forEach(id=>text(id,"--"));
      text("interResultStatus","NO DATA");
      if(chart)chart.innerHTML=Array.from({length:INTER_ROUNDS},(_,i)=>`<div style="--h:0"><b>--</b><span>${i+1}</span></div>`).join("");
      return;
    }
    const peak=Math.max(...valid.map(r=>r.avgWatt));
    const avg=valid.reduce((a,r)=>a+r.avgWatt,0)/valid.length;
    const final=f.results[INTER_ROUNDS-1]?.avgWatt||0;
    text("interPeakPower",String(Math.round(peak)));
    text("interAveragePower",String(Math.round(avg)));
    text("interFatigueIndex",final>0?((peak-final)/peak*100).toFixed(1):"--");   // (Peak − Final) / Peak × 100（v8 參考）
    text("interMaxRpm",f.maxRpm>0?String(Math.round(f.maxRpm)):"--");
    text("interTotalWork",(f.results.reduce((a,r)=>a+r.workJ,0)/1000).toFixed(1));  // 只算 WORK（v8 OPEN，暫定）
    text("interResultStatus",valid.length===INTER_ROUNDS?"OK":"PARTIAL");
    const maxChart=Math.max(peak,1);
    if(chart)chart.innerHTML=Array.from({length:INTER_ROUNDS},(_,i)=>{
      const r=f.results[i], w=r&&r.avgWatt>0?r.avgWatt:0, h=w>0?Math.max(8,Math.round(w/maxChart*100)):0;
      return `<div style="--h:${h}"><b>${w>0?Math.round(w):"--"}</b><span>${i+1}</span></div>`;
    }).join("");
  }
  async function startIntermittentFlow(){
    const f=intermittentFlow;
    if(f.running)return;
    updateInterLoad();
    f.token++; f.running=true; f.round=1; f.phase="work"; f.results=[]; f.maxRpm=0;
    clearInterTable(); updateInterTable();
    if(!await countdown(f,t=>{f.label=t; updateInterDisplay();})) return;
    f.label="";
    for(let round=1; round<=INTER_ROUNDS; round++){
      f.round=round; f.phase="work"; f.samples=[]; f.wattSamples=[]; f.workJ=0; f.lastSampleAt=0;
      await sendKpOnce(f.kp);
      const ok=await runTimed(f,INTER_WORK_S,el=>{
        const rpm=getNewTestRpmSample(), watt=getCurrentWattNumber();
        if(Number.isFinite(rpm)&&rpm>=INTER_MIN_VALID_RPM){ f.samples.push(rpm); if(rpm>f.maxRpm)f.maxRpm=rpm; }
        const elc=Math.min(el,INTER_WORK_S*1000);           // 最後一次 tick 可能超過 5 s，Δt 只算到 5 s 為止
        if(Number.isFinite(watt)&&watt>0){
          f.wattSamples.push(watt);
          f.workJ+=watt*Math.max(0,elc-f.lastSampleAt)/1000;   // Σ Power × Δt，Δt 用單調時間
        }
        f.lastSampleAt=elc;
        updateInterDisplay();
      });
      if(!ok) return;
      f.results.push({round,kp:f.kp,avgRpm:averageNumbers(f.samples),avgWatt:averageNumbers(f.wattSamples),sampleCount:f.wattSamples.length,workJ:f.workJ});
      updateInterTable();
      if(round===INTER_ROUNDS) break;                        // 第 10 回後不再休息
      f.phase="rest";
      await sendKpZeroSure();                                // REST：KP 0（不送 STOP）
      if(!await runTimed(f,INTER_REST_S,()=>updateInterDisplay())) return;
    }
    await sendKpZeroSure();
    f.running=false; f.phase="done"; updateInterDisplay(); renderInterResult(); showPage("intermittentResult");
  }
  async function cancelIntermittentFlow(){
    const f=intermittentFlow, wasRunning=f.running;
    f.token++; clearInterval(f.timerId); f.timerId=null;
    f.running=false; f.phase="ready"; f.label=""; f.remaining=INTER_WORK_S; f.samples=[]; f.wattSamples=[];
    updateInterDisplay();
    if(wasRunning) await sendKpZeroSure();
  }


  // FREE RIDE control repair: bind only the visible FREE RIDE controls.
  // This avoids changing app.js / FTMS / TEST flows while ensuring the visible UI controls
  // drive the hidden app.js #targetKp, ENTER, and STOP functions.
  function setFreeRideKpValue(v){
    const kp=clamp(Math.round(Number(v||0)*10)/10,0.1,14);
    const targetKp=document.getElementById("targetKp");
    if(targetKp) targetKp.value=kp.toFixed(1);
    const kpMirror=document.getElementById("kpMirror");
    if(kpMirror) kpMirror.textContent=kp.toFixed(1)+" KP";
    return kp;
  }
  function getFreeRideKpValue(){
    return Number(document.getElementById("targetKp")?.value||5);
  }
  function bindFreeRideControls(){
    const minus=document.getElementById("kpMinus");
    const plus=document.getElementById("kpPlus");
    const enter=document.getElementById("sendKpBtn");
    const stop=document.getElementById("stopOutputBtn");
    if(minus) minus.addEventListener("click",(e)=>{e.preventDefault();setFreeRideKpValue(getFreeRideKpValue()-0.1);},false);
    if(plus) plus.addEventListener("click",(e)=>{e.preventDefault();setFreeRideKpValue(getFreeRideKpValue()+0.1);},false);
    if(enter) enter.addEventListener("click",async(e)=>{
      e.preventDefault();
      const kp=setFreeRideKpValue(getFreeRideKpValue());
      if(typeof window.sendKP==="function") await window.sendKP(kp,false);
    },false);
    if(stop) stop.addEventListener("click",async(e)=>{
      e.preventDefault();
      await softStopOutputOnly();
    },false);
  }

  document.querySelectorAll(".weightMinus").forEach(b=>b.addEventListener("click",()=>setWeight(weight-1)));
  document.querySelectorAll(".weightPlus").forEach(b=>b.addEventListener("click",()=>setWeight(weight+1)));
  document.querySelectorAll(".ageMinus").forEach(b=>b.addEventListener("click",()=>setAge(age-1)));
  document.querySelectorAll(".agePlus").forEach(b=>b.addEventListener("click",()=>setAge(age+1)));
  document.getElementById("genderMale")?.addEventListener("click",()=>{gender="male";document.getElementById("genderMale").classList.add("active");document.getElementById("genderFemale").classList.remove("active");syncStep1Kp();});
  document.getElementById("genderFemale")?.addEventListener("click",()=>{gender="female";document.getElementById("genderFemale").classList.add("active");document.getElementById("genderMale").classList.remove("active");syncStep1Kp();});
  document.getElementById("wingateWeight")?.addEventListener("input",updateWingateLoad);
  document.getElementById("interWeight")?.addEventListener("input",updateInterLoad);

  const start3StepBtn=document.getElementById("start3Step");
  if(start3StepBtn){
    start3StepBtn.addEventListener("click",(e)=>{
      e.preventDefault();
      e.stopImmediatePropagation();
      if(!threeStepFlow.running)startThreeStepFlow();
    },true);
  }
  const stop3StepBtn=document.getElementById("stopTest");
  if(stop3StepBtn)stop3StepBtn.addEventListener("click",()=>cancelThreeStepFlow(),true);

  const sw=document.getElementById("startWingate");
  if(sw) sw.addEventListener("click",(e)=>{e.preventDefault();e.stopImmediatePropagation();startWingateFlow();},true);
  const si=document.getElementById("startIntermittent");
  if(si) si.addEventListener("click",(e)=>{e.preventDefault();e.stopImmediatePropagation();startIntermittentFlow();},true);
  document.querySelectorAll("[data-page]").forEach(btn=>btn.addEventListener("click",()=>{if(btn.dataset.page!=="wingate" && wingateFlow.running)cancelWingateFlow();if(btn.dataset.page!=="intermittent" && intermittentFlow.running)cancelIntermittentFlow();}));

  bindFreeRideControls();
  setInterval(syncLive,250);
  setWeight(70);setAge(25);syncStep1Kp();updateInterLoad();clearInterTable();updateWingateDisplay();updateInterDisplay();updateThreeStepDisplay();syncLive();
})();