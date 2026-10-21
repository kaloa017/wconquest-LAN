/* Local presentation preferences, real-state onboarding and sync feedback.
   No telemetry, extra polling, framework or changes to game rules. */
(function(w){
  const doc=w.document,root=doc.documentElement;
  const read=(key,fallback)=>{try{return localStorage.getItem(key)||fallback}catch{return fallback}};
  let effects=['auto','reduced'].includes(read('wc-visual-effects','auto'))?read('wc-visual-effects','auto'):'auto';
  let motion=['auto','off'].includes(read('wc-visual-motion','auto'))?read('wc-visual-motion','auto'):'auto';
  const transparency=w.matchMedia('(prefers-reduced-transparency: reduce)');
  function apply(){root.dataset.effects=effects==='reduced'||transparency.matches||(effects==='auto'&&((navigator.deviceMemory&&navigator.deviceMemory<=4)||(navigator.hardwareConcurrency&&navigator.hardwareConcurrency<=4)))?'reduced':'glass';root.dataset.motion=motion}
  function save(next){
    if(next.effects!==undefined){if(!['auto','reduced'].includes(next.effects))return;effects=next.effects}
    if(next.motion!==undefined){if(!['auto','off'].includes(next.motion))return;motion=next.motion}
    try{localStorage.setItem('wc-visual-effects',effects);localStorage.setItem('wc-visual-motion',motion)}catch{}
    apply();doc.querySelectorAll('[data-display-option=effects]').forEach(el=>el.value=effects);doc.querySelectorAll('[data-display-option=motion]').forEach(el=>el.value=motion);
  }
  apply();transparency.addEventListener?.('change',apply);
  w.addEventListener('storage',event=>{if(event.key==='wc-visual-effects'||event.key==='wc-visual-motion'){effects=read('wc-visual-effects','auto');motion=read('wc-visual-motion','auto');apply()}});
  function options(){return `<p>Display choices apply only on this browser. Automatic mode reduces glass on smaller devices. System reduced-motion and transparency preferences are respected.</p><label>Surface effects<select class="form-input" data-display-option="effects" data-ui-filter><option value="auto" ${effects==='auto'?'selected':''}>Automatic · adaptive glass</option><option value="reduced" ${effects==='reduced'?'selected':''}>Reduced · solid surfaces</option></select></label><label>Interface motion<select class="form-input" data-display-option="motion" data-ui-filter><option value="auto" ${motion==='auto'?'selected':''}>Follow system preference</option><option value="off" ${motion==='off'?'selected':''}>Off · instant transitions</option></select></label><p class="v4-sub" role="status">Saved automatically on this device.</p>`}
  w.showDisplayOptions=()=>openCommunityDialog('Display options',options());
  doc.addEventListener('change',event=>{const key=event.target.dataset?.displayOption;if(key)save({[key]:event.target.value})});
  const displayButton=doc.createElement('button');displayButton.className='product-text-button';displayButton.type='button';displayButton.textContent='Display options';displayButton.onclick=w.showDisplayOptions;doc.querySelector('.auth-project-footer')?.appendChild(displayButton);
  const settings=buildSettings;buildSettings=function(){settings();if(!currentUser)return;
    const appearance=doc.getElementById('ui-settings-appearance')||doc.getElementById('settings-content');
    const section=doc.createElement('section');section.className='v4-card';section.id='display-options';section.innerHTML='<h3>Display & accessibility</h3>'+options();appearance.appendChild(section);
    const account=doc.getElementById('ui-settings-account'),content=doc.getElementById('settings-content');
    if(account)for(const child of [...content.children])if(child.classList.contains('v4-card')&&child.querySelector('h3')?.textContent==='Account email')account.appendChild(child);
    WCInterface.runtime.enhance(section);
  };

  // Keep errors visible without adding a single request or interval.
  const sync=doc.createElement('div');sync.id='product-sync-status';sync.className='sync-status';sync.hidden=true;sync.setAttribute('role','status');sync.setAttribute('aria-live','polite');
  const syncText=doc.createElement('span'),retry=doc.createElement('button');retry.className='btn btn-ghost';retry.type='button';retry.textContent='Retry';sync.append(syncText,retry);doc.querySelector('#navbar .nav-right')?.prepend(sync);
  let syncFailed=false;
  function syncState(error){syncFailed=!!error;sync.hidden=!error&&navigator.onLine!==false;syncText.textContent=navigator.onLine===false?'Offline · reconnect to sync':error?'Sync delayed · retrying':''}
  w.addEventListener('offline',()=>syncState('offline'));w.addEventListener('online',()=>syncState(syncFailed?'pending':''));syncState('');
  const apiBefore=api;api=async function(method,path,data){const generation=sessionGeneration,result=await apiBefore(method,path,data);
    if(generation===sessionGeneration&&method==='GET'&&/^\/api\/(me|map\/sync|spectator\/sync)(?:\?|$)/.test(path))syncState(result.error||'');return result;
  };
  retry.onclick=async()=>{if(retry.disabled)return;retry.disabled=true;try{if(currentUser){await refreshUser();await refreshTerritories()}else{const r=await api('GET','/api/spectator/sync?since='+encodeURIComponent(mapVersion));if(!r.error){applyTerritoryDelta(r.map);await refreshOnline(r.online);await drawFallout(r.fallout)}}}finally{retry.disabled=false}};
  const stop=stopPolling;stopPolling=function(){syncFailed=false;sync.hidden=true;stop()};

  // Recovery secrets stay inside the existing acknowledgement dialog.
  const textModal=showTextModal;showTextModal=function(title,text,done,label){textModal(title,text,done,label);
    if(!/recovery|reset code|private code/i.test(title))return;
    const dialog=doc.getElementById('v6-dialog'),pre=dialog?.querySelector('pre');if(!pre)return;
    const secret=String(text).split('\n')[0].trim(),actions=doc.createElement('div');actions.className='recovery-code-actions';
    const copy=doc.createElement('button');copy.type='button';copy.className='btn btn-ghost';copy.textContent='Copy recovery code';const status=doc.createElement('p');status.className='recovery-code-hint';status.setAttribute('role','status');status.textContent='Store this code privately. Anyone with it can recover your account.';
    copy.onclick=async()=>{try{if(!navigator.clipboard?.writeText)throw new Error('unavailable');await navigator.clipboard.writeText(secret);if(status.isConnected)status.textContent='Copied. Save it in a private password manager.'}catch{if(!status.isConnected)return;const range=doc.createRange();range.selectNodeContents(pre);const selection=w.getSelection();selection.removeAllRanges();selection.addRange(range);status.textContent='Automatic copying is unavailable. Select and copy the code manually.'}};
    actions.appendChild(copy);pre.after(actions,status);
  };

  function objectives(user){return [
    {done:(user.territory_count||0)>0,label:'Claim your first territory',note:'Choose unclaimed land on the map.',panel:'territory'},
    {done:Object.values(user.building_counts||{}).some(b=>(b.count||0)>0),label:'Construct your first building',note:'Select owned land to compare costs and production.',panel:'territory'},
    {done:(user.research||[]).length>0,label:'Complete your first research',note:'Choose an affordable project and let it finish.',panel:'research'}
  ]}
  function renderObjectives(){
    const el=doc.getElementById('empire-content'),u=currentUser;if(!el||!u)return;
    doc.getElementById('country-first-steps')?.remove();if((u.territory_count||0)>=10||(u.research||[]).length>=3)return;
    const steps=objectives(u),next=steps.find(s=>!s.done);if(!next)return;
    const section=doc.createElement('section');section.className='v4-card';section.id='country-first-steps';section.innerHTML=`<h3>Your next move</h3><p>${steps.filter(s=>s.done).length} / ${steps.length} first-country objectives complete.</p><progress value="${steps.filter(s=>s.done).length}" max="3" aria-label="First-country objectives"></progress><ul class="starter-objectives">${steps.map(s=>`<li data-complete="${s.done}"><span aria-hidden="true">${s.done?'✓':'○'}</span><span>${esc(s.label)}<br><small>${esc(s.note)}</small></span></li>`).join('')}</ul><button class="btn btn-primary" data-next-panel="${next.panel}">${next.panel==='territory'?'Choose a tile on the map':'Open Research'}</button><button class="btn btn-ghost" data-reopen-guide>Open the guide</button>`;
    el.prepend(section);
  }
  doc.addEventListener('click',event=>{const next=event.target.closest('[data-next-panel]');if(next){if(next.dataset.nextPanel==='territory'){if(isMobile())closeMobileSheet();else showPanel('territory');map?.getContainer().focus()}else openExpansionPanel(next.dataset.nextPanel)}if(event.target.closest('[data-reopen-guide]'))showTutorial(0)});
  const empire=buildEmpire;buildEmpire=async function(){await empire();renderObjectives()};
  PANELS.empire.f=()=>buildEmpire();
  w.WCProduct={preferences:()=>({effects,motion}),setPreferences:save,objectives,renderObjectives};
})(window);
