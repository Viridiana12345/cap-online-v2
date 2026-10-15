(() => {
  const form = document.getElementById('appointmentForm');
  if (!form) return;
  const doctor = form.querySelector('[name=doctor]');
  const grid = document.getElementById('monthDays'), title = document.getElementById('monthTitle');
  const status = document.getElementById('calendarStatus');
  let month = new Date(new Date().getFullYear(), new Date().getMonth(), 1), days = {}, selected = '', version = 0;
  const key = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  const time = value => new Date(value).toLocaleTimeString('es-MX',{hour:'numeric',minute:'2-digit',hour12:true});
  function slots(items, container, start, end, submit) {
    container.replaceChildren(); start.value = ''; end.value = ''; submit.disabled = true;
    for (const item of items) {
      if (!item.available) continue;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'slot-button';
      button.textContent = `${time(item.start)} – ${time(item.end)}`;
      button.setAttribute('aria-pressed','false');
      button.onclick = () => {
        container.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed','false'));
        button.setAttribute('aria-pressed','true'); start.value = item.start; end.value = item.end; submit.disabled = false;
      };
      container.append(button);
    }
  }
  function clearSlots() {
    slots([], document.getElementById('slotGrid'), form.querySelector('#id_start_at'), form.querySelector('#id_end_at'), document.getElementById('bookButton'));
    document.getElementById('slotStatus').textContent = 'Selecciona un día disponible.';
  }
  function draw() {
    title.textContent = month.toLocaleDateString('es-MX',{month:'long',year:'numeric'});
    grid.replaceChildren();
    const offset = (month.getDay()+6)%7;
    for(let i=0;i<offset;i++) grid.append(document.createElement('span'));
    for(let d=1;d<=new Date(month.getFullYear(),month.getMonth()+1,0).getDate();d++) {
      const date = new Date(month.getFullYear(),month.getMonth(),d), dateKey = key(date);
      const button = document.createElement('button'); button.type='button'; button.textContent=d;
      button.disabled = !(days[dateKey]?.length); button.className=selected===dateKey?'selected':'';
      button.setAttribute('aria-label',date.toLocaleDateString('es-MX',{dateStyle:'full'}));
      button.setAttribute('aria-pressed',String(selected===dateKey));
      button.onclick=()=>{selected=dateKey;draw();document.getElementById('slotStatus').textContent=date.toLocaleDateString('es-MX',{dateStyle:'full'});slots(days[dateKey],document.getElementById('slotGrid'),form.querySelector('#id_start_at'),form.querySelector('#id_end_at'),document.getElementById('bookButton'));};
      grid.append(button);
    }
  }
  async function load() {
    const current=++version; days={};selected='';clearSlots();draw();
    if(!doctor.value){status.textContent='Selecciona un especialista para ver sus horarios.';return;}
    status.textContent='Consultando disponibilidad…';
    try {
      const response=await fetch(`${form.dataset.availabilityUrl}?doctor=${encodeURIComponent(doctor.value)}&month=${key(month).slice(0,7)}`,{cache:'no-store'});
      if(!response.ok) throw Error(); const data=await response.json();if(current!==version)return;
      days=data.days;draw();
      status.textContent=data.availability_configured===false
        ? 'Este especialista todavía no ha configurado sus horarios de atención. Pídele que los agregue en Mis citas → Mi disponibilidad, o selecciona otro especialista.'
        : Object.values(days).some(s=>s.length)?'Elige un día para consultar sus horarios.':'No hay horarios disponibles este mes. Puedes consultar otro mes o especialista.';
    } catch(_){if(current===version)status.textContent='No se pudo cargar la disponibilidad. Vuelve a seleccionar el especialista para reintentar.';}
  }
  doctor.addEventListener('change',load);
  document.getElementById('previousMonth').onclick=()=>{month=new Date(month.getFullYear(),month.getMonth()-1,1);load();};
  document.getElementById('nextMonth').onclick=()=>{month=new Date(month.getFullYear(),month.getMonth()+1,1);load();};
  form.addEventListener('submit',e=>{if(!form.querySelector('#id_start_at').value||!confirm('¿Confirmas la solicitud de esta cita?'))e.preventDefault();});
  document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{
    document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));let count=0;
    document.querySelectorAll('.appointment-item').forEach(item=>{item.hidden=button.dataset.filter!=='all'&&item.dataset.status!==button.dataset.filter;if(!item.hidden)count++;});
    document.getElementById('filterEmpty').hidden=!!count;
  });
  const cancelDialog=document.getElementById('cancelDialog'), cancelForm=document.getElementById('cancelAppointmentForm');
  document.querySelectorAll('.cancel-form').forEach(f=>f.addEventListener('submit',e=>{
    e.preventDefault();cancelForm.action=f.action;cancelForm.reset();cancelDialog.showModal();
  }));
  document.getElementById('closeCancel').onclick=()=>cancelDialog.close();
  const dialog=document.getElementById('rescheduleDialog'), reschedule=document.getElementById('rescheduleForm'), date=document.getElementById('rescheduleDate');
  let editingDoctor='', editingId='', revision=0;
  const resetEdit=()=>slots([],document.getElementById('rescheduleSlots'),document.getElementById('rescheduleStart'),document.getElementById('rescheduleEnd'),document.getElementById('rescheduleButton'));
  document.querySelectorAll('.reschedule-trigger').forEach(button=>button.onclick=()=>{revision++;reschedule.reset();reschedule.action=button.dataset.url;editingDoctor=button.dataset.doctor;editingId=button.dataset.appointment;date.value='';date.min=key(new Date());resetEdit();document.getElementById('rescheduleDoctor').textContent=button.dataset.doctorName;document.getElementById('rescheduleStatus').textContent='Selecciona una fecha.';dialog.showModal();});
  document.querySelectorAll('[data-close-dialog]').forEach(b=>b.onclick=()=>dialog.close());
  dialog.addEventListener('close',()=>revision++);
  date.onchange=async()=>{const current=++revision;resetEdit();if(!date.value)return;const label=document.getElementById('rescheduleStatus');label.textContent='Consultando horarios…';try{const response=await fetch(`${form.dataset.availabilityUrl}?doctor=${editingDoctor}&date=${date.value}`,{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(current!==revision)return;slots(data.slots,document.getElementById('rescheduleSlots'),document.getElementById('rescheduleStart'),document.getElementById('rescheduleEnd'),document.getElementById('rescheduleButton'));label.textContent=data.slots.length?'Selecciona un horario de 30 minutos.':'No hay horarios disponibles.';}catch(_){if(current===revision)label.textContent='No se pudo consultar la disponibilidad.';}};
  reschedule.addEventListener('submit',e=>{if(!confirm('¿Confirmas el nuevo horario de tu cita?'))e.preventDefault();});
  load();
})();
