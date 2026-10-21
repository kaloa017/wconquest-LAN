/* Compact navigation, tile finder and statistics. Existing actions keep their guards. */
(function(root,factory){const api=factory();if(typeof exports==='object')Object.assign(exports,api);else{root.WCPolish=api;api.install(root)}})(typeof window==='undefined'?globalThis:window,function(){
  function parseTileTarget(value,mode='grid',grid=.18){
    const input=String(value).trim();if(mode==='grid'&&/^island:[a-z0-9_-]+$/i.test(input))return {key:input};
    const parts=input.replace(/[°()]/g,'').trim().split(/[,;\s]+/).filter(Boolean);
    if(parts.length!==2||parts.some(v=>!/^[-+]?\d+(?:\.\d+)?$/.test(v)))throw new Error('Enter two numbers, for example 200, 100 or 59.91, 10.75.');
    let [a,b]=parts.map(Number);
    if(mode==='latlng'){
      if(a< -85.14||a>=85.14||b< -180||b>=180)throw new Error('Use latitude −85.14 to below 85.14 and longitude −180 to below 180.');
      a=Math.floor(a/grid);b=Math.floor(b/grid);
    }else if(!Number.isInteger(a)||!Number.isInteger(b))throw new Error('Tile IDs use whole numbers. Choose latitude / longitude for decimals.');
    if(a< -473||a>472||b< -1000||b>999)throw new Error('That tile is outside the playable map.');
    return {key:`${a},${b}`,lat:(a+.5)*grid,lng:(b+.5)*grid};
  }
  function install(w){
    const doc=w.document;
    const init=initMap;initMap=function(){
      init();const finder=L.control({position:'topright'});finder.onAdd=()=>{
        const el=L.DomUtil.create('details','map-tile-finder');el.innerHTML='<summary>⌖ Find tile</summary><form><label>Find by<select id="tile-find-mode" data-ui-filter><option value="grid">Tile ID</option><option value="latlng">Latitude / longitude</option></select></label><label>Coordinates or island ID<input id="tile-find-value" data-ui-filter autocomplete="off" placeholder="200, 100" required></label><button class="btn btn-primary" type="submit">Find on map</button><p class="v4-sub">Tile ID: 200, 100 · Map coordinates: 59.91, 10.75</p><p role="status" id="tile-find-result"></p></form>';
        L.DomEvent.disableClickPropagation(el);L.DomEvent.disableScrollPropagation(el);
        el.querySelector('select').onchange=e=>{el.querySelector('input').placeholder=e.target.value==='grid'?'200, 100 or island:…':'59.91, 10.75'};
        el.querySelector('form').onsubmit=async event=>{
          event.preventDefault();const status=el.querySelector('[role="status"]');
          try{const target=parseTileTarget(el.querySelector('input').value,el.querySelector('select').value,GRID);if(target.key.startsWith('island:')&&!pacificIslands[target.key])throw new Error('Unknown island ID.');flyTo(target.key);await inspectIsland(target.key);status.textContent='Selected '+target.key;el.open=false}catch(error){status.textContent=error.message}
        };
        return el;
      };finder.addTo(map);
    };
    let statsScope='country';
    w.buildStatistics=async function(scope=statsScope){
      if(!currentUser)return;statsScope=scope;const el=doc.getElementById('stats-content');if(!el)return;
      const r=await api('GET','/api/statistics?scope='+encodeURIComponent(scope));if(!el.isConnected)return;if(r.error){el.textContent=r.error;return}
      const section=(title,values)=>card(title,`<div class="stats-grid">${Object.entries(values).map(([key,value])=>`<div><span>${esc(key.replaceAll('_',' '))}</span><strong>${key==='play_seconds'?formatPlaytime(value):fmtN(value,Number.isInteger(value)?0:2)}</strong></div>`).join('')}</div>`);
      el.innerHTML=card('Statistics · '+r.title,`${currentUser.is_admin?'<label>Statistics scope<select id="statistics-scope" class="form-input" data-ui-filter><option value="country">My country</option><option value="world">World totals · admin only</option></select></label>':''}<p>${esc(r.note)}</p><button class="btn btn-ghost" id="refresh-statistics">Refresh statistics</button>`)+section('Country & territory',r.totals)+section('Resources',r.resources)+section('Available units & committed troops',r.units)+section('Progression',r.progress)+section('Trade & banking',r.economy)+card('Buildings',`<div class="table-scroll"><table><tr><th>Building</th><th>Count</th><th>Total levels</th></tr>${r.buildings.map(b=>`<tr><td>${esc(BLD[b.type]?.name||b.type)}</td><td>${b.count}</td><td>${b.levels}</td></tr>`).join('')||'<tr><td colspan="3">No buildings yet.</td></tr>'}</table></div>`)+section('Terrains',Object.fromEntries(r.terrains.map(t=>[t.terrain,t.count])));
      const select=doc.getElementById('statistics-scope');if(select){select.value=scope;select.onchange=()=>w.buildStatistics(select.value)}doc.getElementById('refresh-statistics').onclick=()=>w.buildStatistics(statsScope);
    };
    menuItems.stats={icon:'📊',name:'Statistics',desc:'Your country and private world totals'};addNavigation('stats','📊 Statistics',w.buildStatistics);WCInterface.runtime.updateNavigation();
    const groups=[
      {id:'overview',name:'Overview',leaves:[['server','Server dashboard'],['host','Host operations']]},
      {id:'people',name:'Players',leaves:[['accounts','Account directory'],['players','Player actions'],['control','Country controls'],['email','Email & verification']]},
      {id:'world',name:'World',leaves:[['world','Events & balance'],['editor','Game editor'],['tools','Advanced tools']]},
      {id:'community',name:'Community',leaves:[['social','Factions & chat'],['announce','Announcements'],['advertisements','Advertisements']]},
      {id:'analytics',name:'Analytics',leaves:[['analytics','Guest history'],['ip-bans','IP restrictions']]}
    ];
    const labels={server:'Server dashboard',host:'Host tools',accounts:'Accounts',players:'Players',control:'Control center',world:'World',editor:'Game editor',tools:'Tools',social:'Factions & Chat',announce:'Announcements',advertisements:'Advertisements',analytics:'Analytics'};
    const leafButtons=[...doc.querySelectorAll('.admin-tabs .atab')];
    function buttonFor(id){return leafButtons.find(button=>button.dataset.admin===id||button.getAttribute('onclick')?.includes("'"+id+"'")||button.onclick?.toString().includes("'"+id+"'")||button.textContent.includes(labels[id]))}
    const controls=doc.querySelector('.admin-mobile-nav'),select=doc.getElementById('admin-section-select');
    controls.classList.add('admin-group-controls');select.innerHTML=groups.map(g=>`<option value="${g.id}">${g.name}</option>`).join('');select.setAttribute('data-ui-filter','');
    const toolLabel=doc.createElement('label');toolLabel.className='admin-tool-label';toolLabel.innerHTML='<span>Tool</span><select id="admin-tool-select" class="form-input" data-ui-filter></select>';controls.after(toolLabel);
    const tools=toolLabel.querySelector('select'),bar=doc.createElement('div');bar.className='admin-group-tabs';bar.setAttribute('role','tablist');bar.setAttribute('aria-label','Administration categories');
    bar.innerHTML=groups.map(g=>`<button class="btn btn-ghost" role="tab" data-admin-group="${g.id}">${g.name}</button>`).join('');controls.before(bar);doc.querySelector('.admin-tabs').hidden=true;
    let activeGroup='overview',activeLeaf='server';
    function sync(id){
      const group=groups.find(g=>g.leaves.some(([leaf])=>leaf===id));if(!group)return;activeGroup=group.id;activeLeaf=id;select.value=group.id;
      tools.innerHTML=group.leaves.map(([key,label])=>`<option value="${key}">${label}</option>`).join('');tools.value=id;toolLabel.hidden=group.leaves.length===1;
      for(const b of bar.querySelectorAll('button')){const active=b.dataset.adminGroup===group.id;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;b.setAttribute('aria-controls','admin-'+id)}
    }
    const previous=adminTab;adminTab=function(event,id){previous(event,id);const current=doc.querySelector('.admin-panel.active');if(current)sync(current.id.slice(6))};
    const navigationObserver=new MutationObserver(records=>{if(records.some(record=>record.target.classList?.contains('admin-panel'))){const current=doc.querySelector('.admin-panel.active');if(current&&current.id.slice(6)!==activeLeaf)sync(current.id.slice(6))}});
    navigationObserver.observe(doc.querySelector('.admin-tabs').parentElement,{subtree:true,attributes:true,attributeFilter:['class']});
    select.onchange=()=>buttonFor(groups.find(g=>g.id===select.value).leaves[0][0])?.click();tools.onchange=()=>buttonFor(tools.value)?.click();
    for(const b of bar.querySelectorAll('button'))b.onclick=()=>buttonFor(groups.find(g=>g.id===b.dataset.adminGroup).leaves[0][0])?.click();
    bar.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const items=[...bar.querySelectorAll('button')],index=items.indexOf(doc.activeElement);if(index<0)return;event.preventDefault();items[event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowRight'?1:-1)+items.length)%items.length].focus()};
    sync(activeLeaf);
    const dashboard=buildServerDashboard;let dashboardWork=null;buildServerDashboard=function(){if(dashboardWork)return dashboardWork;dashboardWork=(async()=>{await dashboard();const el=doc.getElementById('admin-server');if(!el||!currentUser?.is_admin)return;const r=await api('GET','/api/admin/release_notes');el.insertAdjacentHTML('beforeend',card('Administration',`<button class="btn btn-ghost" onclick="closeAdmin();openExpansionPanel('stats')">Open statistics · choose World totals</button><button class="btn btn-ghost" onclick="closeAdmin();openExpansionPanel('moderation')">Moderation & filters</button><details><summary>Admin release notes</summary><pre class="admin-release-notes">${esc(r.text||r.error||'No notes')}</pre></details>`))})().finally(()=>{dashboardWork=null});return dashboardWork};
    // addHostTab captured its original renderer; replace only this tab's callback.
    const server=buttonFor('server');server.onclick=event=>{adminTab(event,'server');buildServerDashboard()};
    const open=openAdmin;openAdmin=async function(){await open();if(currentUser?.is_admin)server.click()};
    const close=closeAdmin;closeAdmin=function(){statsScope='country';close()};
    const stop=stopPolling;stopPolling=function(){statsScope='country';const el=doc.getElementById('stats-content');if(el)el.replaceChildren();stop()};
  }
  return {parseTileTarget,install};
});
