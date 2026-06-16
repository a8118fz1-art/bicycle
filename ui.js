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
    const bw=Number(input?.value||weight||70);
    const load=Math.round((bw*0.075)*10)/10;
    text("wingateLoad",load.toFixed(1));
    text("wingateLoadCard",load.toFixed(1));
    const kpInput=document.getElementById("targetKp");
    if(kpInput && !wingateFlow.running && activePage === "wingate") kpInput.value=load.toFixed(1);
  }

  const THREE_STEP_REST_SECONDS=120;
  const threeStepFlow = {running:false,currentStep:1,phase:"ready",remaining:10,timerId:null,maxRpm:0,rpmSamples:[],results:[],baseKp:4.0,nextStep:1,nextKp:4.0};
  const THREE_STEP_MIN_VALID_RPM = 20;

  function getCurrentRpmNumber(){
    const raw=(document.getElementById("correctedRpm")?.textContent||"0").replace(/[^\d.]/g,"");
    const rpm=Number(raw);
    return Number.isFinite(rpm)?rpm:0;
  }
  // RPM cache for newly added tests only. 3-STEP continues using getCurrentRpmNumber() directly.
  let lastNewTestValidRpm = 0;
  let lastNewTestValidAt = 0;
  const NEW_TEST_MIN_VALID_RPM = 10;
  const NEW_TEST_RPM_FALLBACK_MS = 1500;
  function refreshNewTestRpmCache(){
    const rpm = getCurrentRpmNumber();
    if(Number.isFinite(rpm) && rpm >= NEW_TEST_MIN_VALID_RPM){
      lastNewTestValidRpm = rpm;
      lastNewTestValidAt = Date.now();
    }
    return rpm;
  }
  function getNewTestRpmSample(){
    const rpm = refreshNewTestRpmCache();
    if(Number.isFinite(rpm) && rpm >= NEW_TEST_MIN_VALID_RPM) return rpm;
    if(lastNewTestValidRpm >= NEW_TEST_MIN_VALID_RPM && (Date.now() - lastNewTestValidAt) <= NEW_TEST_RPM_FALLBACK_MS){
      return lastNewTestValidRpm;
    }
    return 0;
  }
  function averageNumbers(list){
    const valid=list.filter(v=>Number.isFinite(v)&&v>0);
    if(!valid.length) return 0;
    return valid.reduce((a,v)=>a+v,0)/valid.length;
  }
  function calcTestWattFromAvgRpm(kp,avgRpm){
    if(Number.isFinite(kp)&&Number.isFinite(avgRpm)&&avgRpm>0){
      // Use the same power table interpolation as app.js for consistency
      const pw=(typeof window.powerCorrect==="function")?window.powerCorrect(kp,avgRpm):0;
      return pw>0?pw:(kp*avgRpm*0.98);
    }
    return 0;
  }
  function isValidThreeStepRpm(rpm){
    return Number.isFinite(rpm) && rpm >= THREE_STEP_MIN_VALID_RPM;
  }
  function getStableStepMaxRpm(){
    if(!threeStepFlow.rpmSamples.length)return 0;
    return Math.max(...threeStepFlow.rpmSamples);
  }
  function getStableStepAvgRpm(){
    if(!threeStepFlow.rpmSamples.length)return 0;
    const sum=threeStepFlow.rpmSamples.reduce((a,v)=>a+v,0);
    return sum/threeStepFlow.rpmSamples.length;
  }
  function calcStep2Kp(rpm){
    if(rpm>=180)return threeStepFlow.baseKp+3;
    if(rpm>=150)return threeStepFlow.baseKp+2;
    return threeStepFlow.baseKp+1;
  }
  function calcStep3Kp(step2Kp,rpm){
    if(rpm>=180)return step2Kp+4;
    if(rpm>=150)return step2Kp+3;
    if(rpm>=130)return step2Kp+2;
    return step2Kp+1;
  }
  function setThreeStepKp(kp){
    const v=Number(kp).toFixed(1);
    const targetKp=document.getElementById("targetKp");
    if(targetKp)targetKp.value=v;
    text("stepParamKp",v);
    const km=document.getElementById("kpMirror");
    if(km)km.textContent=v+" KP";
  }
  function setThreeStepIndicator(step){
    [1,2,3].forEach(n=>{
      const el=document.getElementById("stepIndicator"+n);
      if(!el)return;
      el.classList.remove("active","running","done");
      if(n<step)el.classList.add("done");
      else if(n===step)el.classList.add("running");
    });
  }
  function resetThreeStepIndicator(){
    [1,2,3].forEach(n=>{
      const el=document.getElementById("stepIndicator"+n);
      if(!el)return;
      el.classList.remove("active","running","done");
      if(n===1)el.classList.add("active");
    });
  }
  function updateThreeStepDisplay(){
    text("stepParamTime",String(threeStepFlow.remaining));
    text("stepParamMaxRpm",threeStepFlow.maxRpm>0?String(Math.round(threeStepFlow.maxRpm)):"--");
    const isRest=threeStepFlow.running && threeStepFlow.phase==="rest";
    const isWork=threeStepFlow.running && threeStepFlow.phase==="work";
    text("threeStepState",isRest?("REST TO STEP "+threeStepFlow.nextStep):(isWork?("STEP "+threeStepFlow.currentStep):"READY"));
    const btn=document.getElementById("start3Step");
    if(btn)btn.textContent=isRest?("REST "+threeStepFlow.remaining+"s"):(isWork?("STEP "+threeStepFlow.currentStep+" / 10s"):"ENTER");
  }

  function setSvgContent(id, content){
    const svg=document.getElementById(id);
    if(svg) svg.innerHTML=content;
  }
  function regression(points){
    const n=points.length;
    const sx=points.reduce((a,p)=>a+p.kp,0);
    const sy=points.reduce((a,p)=>a+p.rpm,0);
    const sxx=points.reduce((a,p)=>a+p.kp*p.kp,0);
    const sxy=points.reduce((a,p)=>a+p.kp*p.rpm,0);
    const d=n*sxx-sx*sx;
    if(Math.abs(d)<1e-9)return null;
    const a=(n*sxy-sx*sy)/d;
    const b=(sy-a*sx)/n;
    const meanY=sy/n;
    const ssTot=points.reduce((sum,p)=>sum+Math.pow(p.rpm-meanY,2),0);
    const ssRes=points.reduce((sum,p)=>sum+Math.pow(p.rpm-(a*p.kp+b),2),0);
    const r2=ssTot>0 ? 1-(ssRes/ssTot) : 1;
    return {a,b,r2};
  }
  function mapPoint(x,y,minX,maxX,minY,maxY){
    const left=55,right=495,top=45,bottom=245;
    const px=left+(x-minX)/(maxX-minX)*(right-left);
    const py=bottom-(y-minY)/(maxY-minY)*(bottom-top);
    return {x:px,y:py};
  }
  function emptyThreeStepResult(message){
    text("threeStepMaxPower","-- watt");
    text("threeStepMaxPowerKp",message||"No valid RPM data");
    ["threeStepR1","threeStepR2","threeStepR3"].forEach((id,i)=>text(id,threeStepFlow.results[i]?.maxRpm>0?String(threeStepFlow.results[i].maxRpm):"--"));
    text("threeStepFormula","--");
    text("threeStepCalcStatus","NO DATA");
    setSvgContent("threeStepRpmChart",'<text x="155" y="145">No valid RPM data</text><text x="18" y="35">rpm</text><text x="480" y="275">kp</text>');
    setSvgContent("threeStepPowerChart",'<text x="155" y="145">No valid RPM data</text><text x="18" y="35">watt</text><text x="480" y="275">kp</text>');
  }
  function renderThreeStepResult(){
    const points=threeStepFlow.results.map(r=>({kp:Number(r.kp),rpm:Number(r.maxRpm),step:r.step}));
    points.forEach((p,i)=>text("threeStepR"+(i+1),p.rpm>0?String(Math.round(p.rpm)):"--"));
    if(points.length!==3 || points.some(p=>!Number.isFinite(p.kp)||!Number.isFinite(p.rpm)||p.rpm<=0)){
      emptyThreeStepResult("Waiting for valid RPM data");
      return;
    }
    const line=regression(points);
    if(!line){emptyThreeStepResult("Regression failed");return;}
    const power=[];
    // 3-STEP final result: scan every 0.1 KP only within the tested load range,
    // with an absolute upper limit of 13.0 KP. Do not extrapolate directly to 13 KP
    // unless the actual tested maximum KP reached 13 KP.
    const testedMaxKp=Math.max(...points.map(p=>p.kp).filter(v=>Number.isFinite(v)));
    const scanMaxKp=Math.min(13.0, Math.max(0.1, testedMaxKp));
    const scanMaxStep=Math.round(scanMaxKp*10);
    for(let i=1;i<=scanMaxStep;i++){
      const kp=Math.round(i)/10;
      const rpm=line.a*kp+line.b;
      const watt=kp*rpm*0.98;
      if(Number.isFinite(watt))power.push({kp,rpm,watt});
    }
    const validPower=power.filter(p=>p.rpm>0 && p.watt>0);
    if(!validPower.length){emptyThreeStepResult("No positive calculated power");return;}
    const maxP=validPower.reduce((m,p)=>p.watt>m.watt?p:m,validPower[0]);
    text("threeStepMaxPower",Math.round(maxP.watt)+" watt");
    text("threeStepMaxPowerKp","@ "+maxP.kp.toFixed(1)+" kp");
    text("threeStepFormula","rpm="+line.a.toFixed(2)+"×kp+"+line.b.toFixed(1));
    text("threeStepCalcStatus","OK / R² "+line.r2.toFixed(3));

    const minKp=Math.min(...points.map(p=>p.kp),0.1), maxKp=scanMaxKp;
    const rpmVals=points.map(p=>p.rpm).concat([line.a*minKp+line.b,line.a*maxKp+line.b]).filter(v=>Number.isFinite(v));
    const minRpm=Math.max(0,Math.min(...rpmVals)-10), maxRpm=Math.max(...rpmVals)+10;
    const p1=mapPoint(minKp,line.a*minKp+line.b,minKp,maxKp,minRpm,maxRpm);
    const p2=mapPoint(maxKp,line.a*maxKp+line.b,minKp,maxKp,minRpm,maxRpm);
    const pointSvg=points.map(p=>{const q=mapPoint(p.kp,p.rpm,minKp,maxKp,minRpm,maxRpm);return `<circle cx="${q.x.toFixed(1)}" cy="${q.y.toFixed(1)}" r="6"/><text x="${(q.x+10).toFixed(1)}" y="${(q.y-10).toFixed(1)}">(${p.kp.toFixed(1)}, ${Math.round(p.rpm)})</text>`;}).join("");
    setSvgContent("threeStepRpmChart",`<line x1="55" y1="245" x2="495" y2="245"/><line x1="55" y1="45" x2="55" y2="245"/><line x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${p2.x.toFixed(1)}" y2="${p2.y.toFixed(1)}" class="chart-line"/>${pointSvg}<text x="18" y="35">rpm</text><text x="480" y="275">kp</text>`);

    const maxWatt=Math.max(...validPower.map(p=>p.watt))*1.1;
    const curve=validPower.map((p,i)=>{const q=mapPoint(p.kp,p.watt,0.1,scanMaxKp,0,maxWatt);return (i===0?"M":"L")+q.x.toFixed(1)+" "+q.y.toFixed(1);}).join(" ");
    const mq=mapPoint(maxP.kp,maxP.watt,0.1,scanMaxKp,0,maxWatt);
    setSvgContent("threeStepPowerChart",`<path d="${curve}" class="chart-line"/><circle cx="${mq.x.toFixed(1)}" cy="${mq.y.toFixed(1)}" r="8"/><text x="${Math.max(80,mq.x-70).toFixed(1)}" y="${Math.max(30,mq.y-18).toFixed(1)}">MAX ${Math.round(maxP.watt)} watt</text><text x="18" y="35">watt</text><text x="480" y="275">kp</text>`);
  }

  async function applyThreeStepOutputKp(kp){
    setThreeStepKp(kp);
    try{
      if(typeof window.sendKP === "function") await window.sendKP(kp,false);
    }catch(e){
      console.warn("3-Step KP command skipped:",e);
    }
  }
  async function clearThreeStepOutputForRest(visibleNextKp){
    try{
      if(typeof window.sendKP === "function") await window.sendKP(0,true);
    }catch(e){
      console.warn("3-Step rest KP clear skipped:",e);
    }
    // Keep the next calculated KP visible during rest, but do not send it until the next WORK starts.
    setThreeStepKp(visibleNextKp);
  }
  function finishThreeStepStep(){
    const step=threeStepFlow.currentStep;
    const currentKp=Number(document.getElementById("targetKp")?.value||threeStepFlow.baseKp);
    const stableMaxRpm=getStableStepMaxRpm();
    const stableAvgRpm=getStableStepAvgRpm();
    threeStepFlow.results.push({step,kp:Number(currentKp.toFixed(1)),maxRpm:Math.round(stableMaxRpm),avgRpm:Math.round(stableAvgRpm),sampleCount:threeStepFlow.rpmSamples.length,time:10});
    document.getElementById("stepIndicator"+step)?.classList.add("done");
    if(step===1){startThreeStepRest(2,calcStep2Kp(stableMaxRpm));return;}
    if(step===2){startThreeStepRest(3,calcStep3Kp(currentKp,stableMaxRpm));return;}
    threeStepFlow.running=false;
    threeStepFlow.phase="done";
    clearInterval(threeStepFlow.timerId);
    threeStepFlow.timerId=null;
    [1,2,3].forEach(n=>document.getElementById("stepIndicator"+n)?.classList.add("done"));
    updateThreeStepDisplay();
    renderThreeStepResult();
    showPage("threeStepResult");
  }
  async function startThreeStepRest(nextStep,nextKp){
    clearInterval(threeStepFlow.timerId);
    threeStepFlow.running=true;
    threeStepFlow.phase="rest";
    threeStepFlow.nextStep=nextStep;
    threeStepFlow.nextKp=Number(nextKp);
    threeStepFlow.remaining=THREE_STEP_REST_SECONDS;
    threeStepFlow.maxRpm=0;
    threeStepFlow.rpmSamples=[];
    [1,2,3].forEach(n=>{
      const el=document.getElementById("stepIndicator"+n);
      if(!el)return;
      el.classList.remove("active","running");
      if(n<nextStep)el.classList.add("done");
      else if(n===nextStep)el.classList.add("active");
    });
    await clearThreeStepOutputForRest(nextKp);
    updateThreeStepDisplay();
    threeStepFlow.timerId=setInterval(()=>{
      threeStepFlow.remaining-=1;
      if(threeStepFlow.remaining<=0){
        threeStepFlow.remaining=0;
        updateThreeStepDisplay();
        startThreeStepStep(nextStep,nextKp);
      }else updateThreeStepDisplay();
    },1000);
  }
  async function startThreeStepStep(step,kp){
    clearInterval(threeStepFlow.timerId);
    threeStepFlow.running=true;
    threeStepFlow.phase="work";
    threeStepFlow.currentStep=step;
    threeStepFlow.remaining=10;
    threeStepFlow.maxRpm=0;
    threeStepFlow.rpmSamples=[];
    setThreeStepIndicator(step);
    await applyThreeStepOutputKp(kp);
    updateThreeStepDisplay();
    threeStepFlow.timerId=setInterval(()=>{
      const rpm=getCurrentRpmNumber();
      if(isValidThreeStepRpm(rpm)){
        threeStepFlow.rpmSamples.push(rpm);
        if(rpm>threeStepFlow.maxRpm)threeStepFlow.maxRpm=rpm;
      }
      threeStepFlow.remaining-=1;
      if(threeStepFlow.remaining<=0){
        threeStepFlow.remaining=0;
        updateThreeStepDisplay();
        finishThreeStepStep();
      }else updateThreeStepDisplay();
    },1000);
  }
  function startThreeStepFlow(){
    threeStepFlow.baseKp=getStep1Kp(gender,weight);
    threeStepFlow.results=[];
    threeStepFlow.nextStep=1;
    threeStepFlow.nextKp=threeStepFlow.baseKp;
    startThreeStepStep(1,threeStepFlow.baseKp);
  }
  function cancelThreeStepFlow(){
    clearInterval(threeStepFlow.timerId);
    threeStepFlow.timerId=null;
    threeStepFlow.running=false;
    threeStepFlow.phase="ready";
    threeStepFlow.currentStep=1;
    threeStepFlow.nextStep=1;
    threeStepFlow.nextKp=threeStepFlow.baseKp;
    threeStepFlow.remaining=10;
    threeStepFlow.maxRpm=0;
    threeStepFlow.rpmSamples=[];
    resetThreeStepIndicator();
    syncStep1Kp();
    updateThreeStepDisplay();
  }




  const wingateFlow={
    running:false,
    remaining:30,
    timerId:null,
    kp:5.3,
    samples:[],
    watts:[],
    secondResults:[]
  };
  const WINGATE_MIN_VALID_RPM=NEW_TEST_MIN_VALID_RPM;

  function calcWingateKpFromWeight(w){
    const bw=clamp(Math.round(Number(w||70)*10)/10,30,180);
    return Math.round((bw*0.075)*10)/10;
  }
  function getWingateKp(){
    const input=document.getElementById("wingateWeight");
    return calcWingateKpFromWeight(input?.value||weight||70);
  }
  async function applyWingateKp(kp,allowZero){
    const kpInput=document.getElementById("targetKp");
    if(kpInput)kpInput.value=Number(kp).toFixed(1);
    try{
      if(typeof window.sendKP === "function") await window.sendKP(kp,!!allowZero);
      else if(!allowZero) document.getElementById("sendKpBtn")?.click();
    }catch(e){
      console.warn("Wingate KP command skipped:",e);
    }
  }
  function updateWingateDisplay(){
    text("wingateTimeView",wingateFlow.running?String(wingateFlow.remaining):"--");
    const rpm=getNewTestRpmSample();
    text("wingateRpmView",rpm>0?String(Math.round(rpm)):"--");
    const watt=getCurrentWattNumber();
    text("wingateWattView",watt>0?String(Math.round(watt)):"--");
    text("wingateStateView",wingateFlow.running?"RUN":"READY");
    const btn=document.getElementById("startWingate");
    if(btn)btn.textContent=wingateFlow.running?"RUNNING":"START";
  }
  function buildWingateSecondResults(){
    const seconds=Array.from({length:30},(_,i)=>({sec:i+1,rpms:[],watts:[]}));
    wingateFlow.samples.forEach(sample=>{
      const sec=Math.min(30,Math.max(1,Math.floor(sample.elapsedMs/1000)+1));
      if(Number.isFinite(sample.rpm)&&sample.rpm>=WINGATE_MIN_VALID_RPM) seconds[sec-1].rpms.push(sample.rpm);
      if(Number.isFinite(sample.watt)&&sample.watt>0) seconds[sec-1].watts.push(sample.watt);
    });
    return seconds.map(bucket=>{
      const avgRpm=averageNumbers(bucket.rpms);
      const avgWatt=averageNumbers(bucket.watts);
      return {
        sec:bucket.sec,
        avgRpm,
        watt:avgWatt,
        sampleCount:bucket.watts.length
      };
    });
  }
  function renderWingateResult(){
    wingateFlow.secondResults=buildWingateSecondResults();
    const valid=wingateFlow.secondResults.filter(r=>r.watt>0 && r.avgRpm>0);
    text("wingateResultKp",wingateFlow.kp.toFixed(1));
    text("wingateSampleCount",String(valid.length));
    if(!valid.length){
      text("wingatePeakPower","--");text("wingateAveragePower","--");text("wingateFatigueIndex","--");
      setSvgContent("wingatePowerChart",'<text x="430" y="215">No valid RPM data</text><text x="8" y="220" transform="rotate(-90 8,220)">POWER (WATT)</text><text x="520" y="405">SECONDS</text>');
      return;
    }
    const peak=Math.max(...valid.map(r=>r.watt));
    const low=Math.min(...valid.map(r=>r.watt));
    const avg=valid.reduce((a,r)=>a+r.watt,0)/valid.length;
    const fatigue=peak>0?((peak-low)/peak*100):0;
    text("wingatePeakPower",String(Math.round(peak)));
    text("wingateAveragePower",String(Math.round(avg)));
    text("wingateFatigueIndex",fatigue.toFixed(1));

    const left=55,right=1045,top=45,bottom=360;
    const maxW=Math.max(peak,1);
    const points=wingateFlow.secondResults.map((r,i)=>{
      const x=left+(i/29)*(right-left);
      const y=r.watt>0?bottom-(r.watt/maxW)*(bottom-top):bottom;
      return {x,y,w:r.watt,sec:r.sec};
    });
    const line=points.map((p,i)=>(i?"L":"M")+p.x.toFixed(1)+" "+p.y.toFixed(1)).join(" ");
    const peakPoint=points.reduce((m,p)=>p.w>m.w?p:m,points[0]);
    const axis=`<line x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}" class="grid-line"/><line x1="${left}" y1="${top}" x2="${left}" y2="${bottom}" class="grid-line"/>`;
    setSvgContent("wingatePowerChart",axis+`<path d="${line}" class="chart-line"/><circle cx="${peakPoint.x.toFixed(1)}" cy="${peakPoint.y.toFixed(1)}" r="7"/><text x="${Math.min(peakPoint.x+18,900).toFixed(1)}" y="${Math.max(peakPoint.y-14,25).toFixed(1)}">PEAK ${Math.round(peak)} W</text><text x="8" y="220" transform="rotate(-90 8,220)">POWER (WATT)</text><text x="520" y="405">SECONDS</text>`);
  }
  async function finishWingateFlow(){
    wingateFlow.running=false;
    clearInterval(wingateFlow.timerId);
    wingateFlow.timerId=null;
    await applyWingateKp(0,true);
    updateWingateDisplay();
    renderWingateResult();
    showPage("wingateResult");
  }
  async function startWingateFlow(){
    if(wingateFlow.running)return;
    updateWingateLoad();
    wingateFlow.kp=getWingateKp();
    wingateFlow.remaining=30;
    wingateFlow.samples=[];
    wingateFlow.watts=[];
    wingateFlow.secondResults=[];
    wingateFlow.running=true;
    await applyWingateKp(wingateFlow.kp,false);
    updateWingateDisplay();
    clearInterval(wingateFlow.timerId);
    let wingateMsLeft = 30000;
    wingateFlow.timerId=setInterval(async()=>{
      if(!wingateFlow.running)return;
      const rpm=getNewTestRpmSample();
      const elapsedMs=30000-wingateMsLeft;
      const watt=getCurrentWattNumber();
      if(Number.isFinite(rpm)&&rpm>=WINGATE_MIN_VALID_RPM){
        wingateFlow.samples.push({elapsedMs,rpm,watt:Number.isFinite(watt)&&watt>0?watt:0});
      }
      wingateFlow.watts.push(Number.isFinite(watt)&&watt>0?watt:0);
      wingateMsLeft-=250;
      wingateFlow.remaining=Math.max(0,Math.ceil(wingateMsLeft/1000));
      if(wingateMsLeft<=0){
        await finishWingateFlow();
        return;
      }
      updateWingateDisplay();
    },250);
  }
  async function cancelWingateFlow(){
    clearInterval(wingateFlow.timerId);
    wingateFlow.timerId=null;
    wingateFlow.running=false;
    wingateFlow.remaining=30;
    wingateFlow.samples=[];
    wingateFlow.watts=[];
    wingateFlow.secondResults=[];
    await applyWingateKp(0,true);
    updateWingateDisplay();
  }

  const intermittentFlow = {
    running:false,
    round:1,
    phase:"ready",
    remaining:5,
    phaseMs:5000,
    timerId:null,
    kp:5.3,
    weight:70,
    samples:[],
    wattSamples:[],
    results:[]
  };
  const INTER_MIN_VALID_RPM = NEW_TEST_MIN_VALID_RPM;

  function calcInterKpFromWeight(w){
    const bw=clamp(Math.round(Number(w||70)*10)/10,30,180);
    return Math.round((bw*0.075)*10)/10;
  }
  function updateInterLoad(){
    const input=document.getElementById("interWeight");
    const bw=clamp(Math.round(Number(input?.value||weight||70)*10)/10,30,180);
    intermittentFlow.weight=bw;
    intermittentFlow.kp=calcInterKpFromWeight(bw);
    text("interKp",intermittentFlow.kp.toFixed(1));
    const kpInput=document.getElementById("targetKp");
    if(kpInput && !intermittentFlow.running && activePage === "intermittent") kpInput.value=intermittentFlow.kp.toFixed(1);
  }
  async function applyInterKp(kp,allowZero){
    const kpInput=document.getElementById("targetKp");
    if(kpInput) kpInput.value=Number(kp).toFixed(1);
    try{
      if(typeof window.sendKP === "function") await window.sendKP(kp,!!allowZero);
      else if(!allowZero) document.getElementById("sendKpBtn")?.click();
    }catch(e){
      console.warn("Intermittent KP command skipped:",e);
    }
  }
  function clearInterTable(){
    const body=document.getElementById("interDataBody");
    if(!body)return;
    body.innerHTML=Array.from({length:10},(_,i)=>`<tr><td>${i+1}</td><td>--</td><td>--</td><td>--</td><td>--</td></tr>`).join("");
  }
  function updateInterTable(){
    const body=document.getElementById("interDataBody");
    if(!body)return;
    body.innerHTML=Array.from({length:10},(_,i)=>{
      const r=intermittentFlow.results[i];
      if(!r)return `<tr><td>${i+1}</td><td>--</td><td>--</td><td>--</td><td>--</td></tr>`;
      return `<tr><td>${r.round}</td><td>${r.kp.toFixed(1)}</td><td>${r.avgRpm>0?Math.round(r.avgRpm):"--"}</td><td>${r.avgWatt>0?Math.round(r.avgWatt):"--"}</td><td>${r.sampleCount}</td></tr>`;
    }).join("");
  }
  function updateInterDisplay(){
    text("interRoundView",intermittentFlow.running?String(intermittentFlow.round):"--");
    text("interPhaseView",intermittentFlow.running?intermittentFlow.phase.toUpperCase():"READY");
    text("interTimeView",intermittentFlow.running?String(intermittentFlow.remaining):"--");
    const rpm=getNewTestRpmSample();
    text("interRpmView",rpm>0?String(Math.round(rpm)):"--");
    const watt=getCurrentWattNumber();
    text("interWattView",watt>0?String(Math.round(watt)):"--");
    const btn=document.getElementById("startIntermittent");
    if(btn)btn.textContent=intermittentFlow.running?"RUNNING":"START";
  }
  function recordInterRound(){
    const samples=intermittentFlow.samples.slice();
    const wattSamples=intermittentFlow.wattSamples.slice();
    const avgRpm=averageNumbers(samples);
    const avgWatt=averageNumbers(wattSamples);
    intermittentFlow.results.push({
      round:intermittentFlow.round,
      kp:intermittentFlow.kp,
      avgRpm,
      avgWatt,
      sampleCount:wattSamples.length
    });
    intermittentFlow.samples=[];
    intermittentFlow.wattSamples=[];
    updateInterTable();
  }
  function renderInterResult(){
    const valid=intermittentFlow.results.filter(r=>r.avgWatt>0);
    text("interResultKp",intermittentFlow.kp.toFixed(1));
    if(!valid.length){
      text("interPeakPower","--");text("interAveragePower","--");text("interLowestPower","--");text("interResultStatus","NO DATA");
      const chart=document.getElementById("interBarChart");
      if(chart)chart.innerHTML=Array.from({length:10},(_,i)=>`<div style="--h:0"><b>--</b><span>${i+1}</span></div>`).join("");
      return;
    }
    const peak=Math.max(...valid.map(r=>r.avgWatt));
    const low=Math.min(...valid.map(r=>r.avgWatt));
    const avg=valid.reduce((a,r)=>a+r.avgWatt,0)/valid.length;
    text("interPeakPower",String(Math.round(peak)));
    text("interAveragePower",String(Math.round(avg)));
    text("interLowestPower",String(Math.round(low)));
    text("interResultStatus",valid.length===10?"OK":"PARTIAL");
    const maxChart=Math.max(peak,1);
    const chart=document.getElementById("interBarChart");
    if(chart){
      chart.innerHTML=Array.from({length:10},(_,i)=>{
        const r=intermittentFlow.results[i];
        const w=r&&r.avgWatt>0?r.avgWatt:0;
        const h=w>0?Math.max(8,Math.round(w/maxChart*100)):0;
        return `<div style="--h:${h}"><b>${w>0?Math.round(w):"--"}</b><span>${i+1}</span></div>`;
      }).join("");
    }
  }
  async function startInterPhase(phase){
    intermittentFlow.phase=phase;
    intermittentFlow.remaining=phase==="work"?5:20;
    intermittentFlow.phaseMs=intermittentFlow.remaining*1000;
    if(phase==="work"){
      intermittentFlow.samples=[];
      intermittentFlow.wattSamples=[];
      await applyInterKp(intermittentFlow.kp,false);
    }else{
      await applyInterKp(0,true);
    }
    updateInterDisplay();
  }
  async function finishIntermittent(){
    intermittentFlow.running=false;
    clearInterval(intermittentFlow.timerId);
    intermittentFlow.timerId=null;
    intermittentFlow.phase="done";
    await applyInterKp(0,true);
    updateInterDisplay();
    renderInterResult();
    showPage("intermittentResult");
  }
  async function startIntermittentFlow(){
    if(intermittentFlow.running)return;
    updateInterLoad();
    intermittentFlow.running=true;
    intermittentFlow.round=1;
    intermittentFlow.phase="work";
    intermittentFlow.remaining=5;
    intermittentFlow.phaseMs=5000;
    intermittentFlow.samples=[];
    intermittentFlow.wattSamples=[];
    intermittentFlow.results=[];
    clearInterTable();
    updateInterTable();
    await startInterPhase("work");
    clearInterval(intermittentFlow.timerId);
    intermittentFlow.timerId=setInterval(async()=>{
      if(!intermittentFlow.running)return;
      if(intermittentFlow.phase==="work"){
        const rpm=getNewTestRpmSample();
        const watt=getCurrentWattNumber();
        if(Number.isFinite(rpm) && rpm>=INTER_MIN_VALID_RPM) intermittentFlow.samples.push(rpm);
        if(Number.isFinite(watt) && watt>0) intermittentFlow.wattSamples.push(watt);
      }
      intermittentFlow.phaseMs-=250;
      intermittentFlow.remaining=Math.max(0,Math.ceil(intermittentFlow.phaseMs/1000));
      if(intermittentFlow.phaseMs<=0){
        if(intermittentFlow.phase==="work"){
          recordInterRound();
          await startInterPhase("rest");
        }else{
          if(intermittentFlow.round>=10){
            await finishIntermittent();
            return;
          }
          intermittentFlow.round+=1;
          await startInterPhase("work");
        }
      }else{
        updateInterDisplay();
      }
    },250);
  }
  async function cancelIntermittentFlow(){
    clearInterval(intermittentFlow.timerId);
    intermittentFlow.timerId=null;
    intermittentFlow.running=false;
    intermittentFlow.phase="ready";
    intermittentFlow.remaining=5;
    intermittentFlow.phaseMs=5000;
    intermittentFlow.samples=[];
    intermittentFlow.wattSamples=[];
    await applyInterKp(0,true);
    updateInterDisplay();
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