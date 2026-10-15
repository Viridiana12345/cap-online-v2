(() => {
  const node=document.getElementById("schedule-data"),doctorField=document.querySelector('[name="doctor"]');
  if(!node||!doctorField)return;
  const capSchedules=JSON.parse(node.textContent),capSchedule=()=>capSchedules[String(doctorField.value||"")]||null;
  const capRanges=date=>capSchedule()?.weekly?.[String((date.getDay()+6)%7)]||[];
  const capLocal=(date,h,m)=>new Date(date.getFullYear(),date.getMonth(),date.getDate(),h,m,0,0);
  const capConflict=(start,end)=>(capSchedule()?.occupied||[]).some(([from,to])=>start<new Date(to)&&end>new Date(from));
  const capTime=date=>date.toLocaleTimeString("es-MX",{hour:"numeric",minute:"2-digit"});

  renderCalendar=function(){
    const calendar=document.getElementById("calGrid");document.getElementById("calMonthLabel").textContent=`${MONTHS_ES[viewMonth]} ${viewYear}`;
    let html=DAYS_ES.map(day=>`<div class="cal-dow">${day}</div>`).join("");const first=new Date(viewYear,viewMonth,1).getDay(),count=new Date(viewYear,viewMonth+1,0).getDate();
    for(let i=0;i<first;i++)html+='<div class="cal-day empty"></div>';
    for(let day=1;day<=count;day++){const date=new Date(viewYear,viewMonth,day);date.setHours(0,0,0,0);const ranges=capRanges(date);const busy=(capSchedule()?.occupied||[]).some(([value])=>{const item=new Date(value);return item.getFullYear()===viewYear&&item.getMonth()===viewMonth&&item.getDate()===day});const disabled=date<today||!doctorField.value||!ranges.length;const classes=["cal-day",date.getTime()===today.getTime()?"today":"",selectedDate&&date.getTime()===selectedDate.getTime()?"selected":"",busy?"has-busy":"",disabled?"disabled":""].filter(Boolean).join(" ");html+=`<div class="${classes}" data-day="${day}">${day}</div>`}
    calendar.innerHTML=html;calendar.querySelectorAll(".cal-day:not(.disabled):not(.empty)").forEach(item=>item.addEventListener("click",()=>{selectedDate=new Date(viewYear,viewMonth,Number(item.dataset.day));selectedSlot=null;clearSummary();renderCalendar();renderSlots()}));
  };
  renderSlots=function(){
    const section=document.getElementById("slotSection"),slots=document.getElementById("slotsGrid"),schedule=capSchedule();if(!selectedDate||!schedule){section.style.display="none";return}section.style.display="block";document.getElementById("slotDateTitle").textContent=selectedDate.toLocaleDateString("es-MX",{weekday:"long",day:"numeric",month:"long"});const duration=schedule.duration||60;let html="";
    capRanges(selectedDate).forEach(range=>{const[sh,sm]=range.start.split(":").map(Number),[eh,em]=range.end.split(":").map(Number);for(let minute=sh*60+sm;minute+duration<=eh*60+em;minute+=30){const start=capLocal(selectedDate,Math.floor(minute/60),minute%60),end=new Date(start.getTime()+duration*60000),occupied=capConflict(start,end),past=start<=new Date(),active=selectedSlot&&selectedSlot.h===start.getHours()&&selectedSlot.m===start.getMinutes(),state=occupied?"busy":past?"past":active?"selected-slot":"";html+=`<button type="button" class="slot-btn ${state}" data-h="${start.getHours()}" data-m="${start.getMinutes()}" ${occupied||past?"disabled":""}><span class="slot-time">${capTime(start)}</span><span class="slot-sub">${occupied?"No disponible":past?"Ya pasó":`hasta ${capTime(end)}`}</span></button>`}});
    slots.innerHTML=html||'<p class="muted">Este especialista no tiene horarios disponibles para este día.</p>';slots.querySelectorAll(".slot-btn:not(:disabled)").forEach(button=>button.addEventListener("click",()=>{selectedSlot={h:Number(button.dataset.h),m:Number(button.dataset.m)};renderSlots();updateSummary()}));
  };
  updateSummary=function(){
    if(!selectedDate||!selectedSlot)return;const duration=capSchedule()?.duration||60,start=capLocal(selectedDate,selectedSlot.h,selectedSlot.m),end=new Date(start.getTime()+duration*60000);
    document.getElementById("hidden_start").value=formatDjangoDateTime(start);document.getElementById("hidden_end").value=formatDjangoDateTime(end);
    document.getElementById("summaryVal").textContent=start.toLocaleDateString("es-MX",{weekday:"long",day:"numeric",month:"long",year:"numeric"})+" · "+capTime(start);
    document.getElementById("summarySub").textContent=`Fin: ${capTime(end)} · Duración: ${duration} minutos`;document.getElementById("selSummary").classList.add("visible");document.getElementById("submitBtn").disabled=false;
  };
  doctorField.addEventListener("change",()=>{selectedDate=null;selectedSlot=null;clearSummary();document.getElementById("slotSection").style.display="none";renderCalendar()});renderCalendar();
})();
