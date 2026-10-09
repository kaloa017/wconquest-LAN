/* Private battle orders and late-game space. Existing game actions stay intact. */
let privateBattleLayer=null, privateBattleSignature='', battlePlan=null, planLayer=null;
let progressionBusy=false, spaceSnapshot=null, spaceTutorialOpen=false, airstrikeBusy=false;

function clearPrivateBattles(){privateBattleLayer?.remove();privateBattleLayer=null;privateBattleSignature=''}
function drawPrivateBattles(campaigns){
  if(!map||!currentUser)return clearPrivateBattles();
  const active=campaigns.filter(c=>c.status==='active'&&(c.attacker===currentUser.id||c.defender===currentUser.id));
  const signature=JSON.stringify(active.map(c=>[c.id,c.from_key,c.target_key,c.progress,Math.round(c.attack_org),Math.round(c.defense_org)]));
  if(signature===privateBattleSignature)return;
  clearPrivateBattles();privateBattleSignature=signature;privateBattleLayer=L.layerGroup().addTo(map);
  for(const c of active){
    const attacking=c.attacker===currentUser.id,color=attacking?'#79c8ff':'#ff9a86';
    L.polyline([pointForKey(c.from_key),pointForKey(c.target_key)],{color,weight:4,dashArray:'8 6',interactive:false}).addTo(privateBattleLayer);
    const icon=L.divIcon({className:'private-battle-icon',iconSize:[58,34],iconAnchor:[29,17],html:`<button class="battle-pin ${attacking?'attacking':'defending'}" aria-label="${attacking?'Attacking':'Defending'} battle: ${Math.round(c.progress)} percent progress">⚔ ${Math.round(c.progress)}%</button>`});
    L.marker(pointForKey(c.target_key),{icon,zIndexOffset:700}).bindTooltip(`${attacking?'Your offensive':'Defending your territory'} · ${fmtN(c.troops)} troops<br>Organization: attacker ${Math.round(c.attack_org)}% · defender ${Math.round(c.defense_org)}%`).on('click',()=>battlePlan?appendPlanTarget(c.target_key):openExpansionPanel('operations')).addTo(privateBattleLayer);
  }
}
function renderOperations(result){
  const el=document.getElementById('operations-content');if(!el)return;
  const uid=currentUser?.id;if(!uid){el.textContent='Log in to manage operations.';return}
  const focused=el.contains(document.activeElement)?document.activeElement.getAttribute('onclick'):null;
  const scroll=el.closest('.panel-content')?.scrollTop||0;
  const battleCard=c=>{
    const mine=c.attacker===uid,active=c.status==='active';
    return card(`${mine?'⚔ Offensive':'🛡 Defense'} · ${esc(c.target_key)}`,`<div class="battle-status"><span class="chip ${active?'gold':''}">${esc(c.status)}</span><span>${fmtN(c.troops)} troops · ${fmtN(c.lost)} lost</span></div><div class="battle-meters"><label>Attacker organization <b>${Math.round(c.attack_org)}%</b><progress max="100" value="${c.attack_org}"></progress></label><label>Defender organization <b>${Math.round(c.defense_org)}%</b><progress max="100" value="${c.defense_org}"></progress></label></div><p class="v4-sub">Supply ${Math.round(c.supply*100)}% · ${esc(c.tactic)} attack · ${esc(c.posture)} defense</p>${mine&&c.targets_remaining?.length?`<p class="route-summary">Next: ${c.targets_remaining.map(esc).join(' → ')}</p>`:''}${active?`<div class="battle-commands">${(mine?['balanced','careful','breakthrough']:['hold','entrench','counterattack']).map(t=>`<button class="btn btn-ghost btn-sm" aria-pressed="${(mine?c.tactic:c.posture)===t}" onclick="campaignOrder(${c.id},'${mine?'tactic':'posture'}','${t}')">${esc(t)}</button>`).join('')}</div>${mine?`<button class="btn btn-danger btn-sm" onclick="campaignOrder(${c.id},'retreat')">↩ Retreat survivors</button>`:''}`:`<p>${esc(c.summary)}</p>`}<button class="btn btn-ghost btn-sm" onclick="flyTo('${c.target_key}')">🗺 Show on map</button>`);
  };
  const active=result.campaigns.filter(c=>c.status==='active'),ended=result.campaigns.filter(c=>c.status!=='active');
  el.innerHTML=card('⚔ Command your front',`<p>Pick a friendly starting tile, then click adjacent targets on the map. One force follows the route automatically after each victory.</p><button class="btn btn-primary btn-full" onclick="beginBattlePlan()">🗺 Plan an offensive</button><details class="game-help"><summary>How battles work</summary><p>Only the attacker and current defender see battle markers. Food and a friendly source tile keep supply flowing. Organization reaching zero forces retreat. Use careful tactics to reduce losses or breakthrough to push harder. A declared faction war is required to attack another player.</p><p>Orders run every ${result.tick_seconds}s. Naval and air assaults remain immediate landings. Select a tile with an available air assault and press <kbd>F</kbd>, or use its button.</p></details>`)+(active.length?active.map(battleCard).join(''):card('No active battles','<p>Plan an offensive, or select an enemy tile beside your land. Survivors automatically return when an offensive ends.</p>'))+(ended.length?`<details class="battle-history"><summary>Recent battles (${fmtN(ended.length)})</summary>${ended.map(battleCard).join('')}</details>`:'');
  if(el.closest('.panel-content'))el.closest('.panel-content').scrollTop=scroll;
  if(focused)[...el.querySelectorAll('button')].find(b=>b.getAttribute('onclick')===focused)?.focus({preventScroll:true});
}
buildOperations=async function(){
  const generation=sessionGeneration,uid=currentUser?.id,el=document.getElementById('operations-content');
  if(!uid){if(el)el.textContent='Log in to manage operations.';return}
  const result=await api('GET','/api/campaigns');
  if(generation!==sessionGeneration||uid!==currentUser?.id)return;
  if(result.error){if(el)el.textContent=result.error;return}
  drawPrivateBattles(result.campaigns);renderOperations(result);
};

PANELS.operations.f=buildOperations;

function cancelBattlePlan(){battlePlan=null;planLayer?.remove();planLayer=null;document.getElementById('battle-planner')?.remove()}
function beginBattlePlan(source=selectedKey){
  if(!currentUser)return toast('Log in to plan an offensive','error');
  const sources=groupTiles();if(!sources.length)return toast('Claim a starting territory first','error');
  if(!sources.includes(source))source=sources[0];cancelBattlePlan();
  battlePlan={source,targets:[],generation:sessionGeneration};
  if(isMobile())closeMobileSheet();
  const bar=document.createElement('section');bar.id='battle-planner';bar.className='battle-planner';bar.setAttribute('aria-label','Offensive planner');
  bar.innerHTML=`<div class="planner-heading"><b>🗺 Plan an offensive</b><button class="btn btn-ghost btn-sm" onclick="cancelBattlePlan()" aria-label="Cancel offensive plan">✕</button></div><p class="v4-sub">Click adjacent targets on the map. Only you can see this draft. Up to 64 tiles per route.</p><div class="planner-fields"><label>Starting tile<select class="form-input" id="plan-source">${sources.map(key=>`<option value="${esc(key)}" ${key===source?'selected':''}>${esc(key)}</option>`).join('')}</select></label><label>Troops<input id="plan-troops" class="form-input" type="number" min="1" step="1" max="${currentUser.army}" value="${Math.max(1,Math.floor(currentUser.army*.75))}"></label><label>Tactic<select id="plan-tactic" class="form-input"><option value="balanced">Balanced</option><option value="careful">Careful</option><option value="breakthrough">Breakthrough</option></select></label></div><p id="plan-route" class="route-summary" aria-live="polite">Click the first target next to your starting tile.</p><div class="planner-actions"><button class="btn btn-ghost" id="plan-undo">↩ Undo</button><button class="btn btn-primary" id="plan-start" disabled>⚔ Start offensive</button></div>`;
  const body=document.createElement('div');body.className='planner-body';
  const actions=bar.lastElementChild;for(const child of [...bar.children].slice(1,-1))body.appendChild(child);bar.insertBefore(body,actions);
  document.body.appendChild(bar);bar.querySelector('#plan-source').onchange=e=>{battlePlan.source=e.target.value;battlePlan.targets=[];updateBattlePlan()};bar.querySelector('#plan-undo').onclick=()=>{battlePlan.targets.pop();updateBattlePlan()};bar.querySelector('#plan-start').onclick=submitBattlePlan;
  bar.querySelector('#plan-troops').addEventListener('input',updateBattlePlan);
  const costs=document.createElement('p');costs.id='plan-travel-cost';costs.className='v4-sub';body.appendChild(costs);updateBattlePlan();
  flyTo(source);
  if(map)map.setZoom(Math.max(9,map.getZoom()));
  if(isMobile()&&map)map.panBy([0,map.getSize().y*.25],{animate:false});
  bar.querySelector('#plan-source').focus({preventScroll:true});
}
function appendPlanTarget(key){
  if(!battlePlan)return;
  const previous=battlePlan.targets.at(-1)||battlePlan.source;
  if(key===previous)return;
  if(key===battlePlan.source||battlePlan.targets.includes(key))return toast('That tile is already in your route','error');
  if(dist(previous,key)>1)return toast('Choose a tile touching the last target','error');
  if(groupTiles().includes(key))return toast('Choose an enemy or unclaimed tile','error');
  if(battlePlan.targets.length>=64)return toast('Start another route after these 64 targets','error');
  battlePlan.targets.push(key);updateBattlePlan();
}
function updateBattlePlan(){
  planLayer?.remove();planLayer=null;if(!battlePlan)return;
  document.getElementById('plan-route').textContent=[battlePlan.source,...battlePlan.targets].join(' → ');
  document.getElementById('plan-start').disabled=!battlePlan.targets.length;
  const troops=Number(document.getElementById('plan-troops').value),rate=gameConfig.military_travel_cost?.land;
  if(rate&&Number.isSafeInteger(troops)&&troops>0){const perTile=Object.fromEntries(Object.entries(rate).map(([r,v])=>[r,Math.ceil(v*troops)]));document.getElementById('plan-travel-cost').textContent=`Departure: ${fmtCost(perTile)}. Queued advance: ${fmtCost(Object.fromEntries(Object.entries(rate).map(([r,v])=>[r,Math.ceil(v*troops*gameConfig.queued_advance_cost_multiplier)])))} per tile at this troop count (+25%); later steps use survivors. The route stops if you cannot afford the next step.`}
  if(map&&battlePlan.targets.length)planLayer=L.polyline([battlePlan.source,...battlePlan.targets].map(pointForKey),{color:'#ffe08a',weight:4,dashArray:'4 8',interactive:false}).addTo(map);
}
async function submitBattlePlan(){
  const plan=battlePlan,button=document.getElementById('plan-start');if(!plan?.targets.length)return;
  const troops=Number(document.getElementById('plan-troops').value),tactic=document.getElementById('plan-tactic').value;
  if(!Number.isSafeInteger(troops)||troops<1||troops>currentUser.army)return toast('Choose whole troops from your available army','error');
  button.disabled=true;
  try{const result=await api('POST','/api/attack',{from_key:plan.source,target_key:plan.targets[0],target_keys:plan.targets,troops,tactic});if(plan.generation!==sessionGeneration)return;if(result.error)return toast(result.error,'error');cancelBattlePlan();toast('Offensive ordered · '+fmtN(troops)+' troops','success');await refreshUser();await buildOperations()}finally{if(button.isConnected)button.disabled=false}
}
const plannedMapClick=onMapClick;
onMapClick=function(event){if(!battlePlan)return plannedMapClick(event);const island=islandAt(event.latlng.lat,event.latlng.lng);appendPlanTarget(island?.properties.key||`${Math.floor(event.latlng.lat/GRID)},${Math.floor(event.latlng.lng/GRID)}`)};
const plannedIslandClick=inspectIsland;
inspectIsland=function(key){if(battlePlan)return appendPlanTarget(key);return plannedIslandClick(key)};

const progressionTerritory=buildTerritoryPanel;
buildTerritoryPanel=function(key,t,container){
  progressionTerritory(key,t,container);const el=container||document.getElementById('territory-actions');if(!el||!currentUser)return;
  if(groupTiles().includes(key))el.insertAdjacentHTML('beforeend','<button class="btn btn-primary btn-full" onclick="beginBattlePlan(\''+key+'\')">🗺 Plan offensive from here</button>');
  const land=el.querySelector('[data-pv="land"]');if(land){const note=document.createElement('p');note.className='v4-sub';land.appendChild(note);const update=()=>{const rate=gameConfig.military_travel_cost?.land,troops=Number(land.querySelector('#sl-land')?.value||1);if(rate)note.textContent='Travel per tile: '+fmtCost(Object.fromEntries(Object.entries(rate).map(([r,v])=>[r,Math.ceil(v*troops)])))+' · requires your own money and oil.'};land.querySelector('#sl-land')?.addEventListener('input',update);update()}
  const air=el.querySelector('[data-pv="air"] .atk-btn');if(air){air.dataset.airstrike='1';air.insertAdjacentHTML('beforeend',' <kbd>F</kbd>');air.title='Air assault · F hotkey';const note=document.createElement('p');note.className='v4-sub';air.parentElement.appendChild(note);const update=()=>{const rate=gameConfig.military_travel_cost?.air,source=el.querySelector('#src-air')?.value,planes=Number(el.querySelector('#sl-air')?.value||1);if(rate&&source){const distance=dist(source,key);note.textContent='Flight travel: '+fmtCost(Object.fromEntries(Object.entries(rate).map(([r,v])=>[r,Math.ceil(v*planes*distance)])))+' · paid by you before takeoff, including when the attack fails.'}};el.querySelector('#sl-air')?.addEventListener('input',update);el.querySelector('#src-air')?.addEventListener('change',update);update()}
};
function airstrikeHotkey(event){
  if(event.key.toLowerCase()!=='f'||event.repeat||event.ctrlKey||event.altKey||event.metaKey||airstrikeBusy||battlePlan||!currentUser||!selectedKey)return;
  if(event.target.closest('input,textarea,select,[contenteditable="true"]')||document.querySelector('.v6-overlay,.modal-overlay.open,#tut.open,#battle-report.open,.activity-overlay'))return;
  const button=document.querySelector('[data-airstrike="1"]');if(!button||button.disabled||!button.getClientRects().length)return;
  event.preventDefault();button.click();
}
document.addEventListener('keydown',airstrikeHotkey);
const guardedAirAttack=doAttack;
doAttack=async function(kind,key){if(kind!=='air')return guardedAirAttack(kind,key);if(airstrikeBusy)return;airstrikeBusy=true;const button=document.querySelector('[data-airstrike="1"]');if(button)button.disabled=true;try{return await guardedAirAttack(kind,key)}finally{airstrikeBusy=false;if(button?.isConnected)button.disabled=false}};

const accessibleBattleReport=showBattleReport;
showBattleReport=function(result,title){
  const previous=document.activeElement;accessibleBattleReport(result,title);
  const overlay=document.getElementById('battle-report'),box=document.getElementById('br-box'),button=box.querySelector('button');
  box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');box.setAttribute('aria-label','Battle report');
  button.onclick=()=>{overlay.classList.remove('open');if(previous?.isConnected)previous.focus({preventScroll:true})};
  overlay.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();button.click()}else if(event.key==='Tab'){event.preventDefault();button.focus({preventScroll:true})}};
  button.focus({preventScroll:true});
};

function spaceTutorial(){
  if(spaceTutorialOpen)return;spaceTutorialOpen=true;
  showTextModal('🚀 Your space program',`1. Research Spaceflight after the Manhattan Project, then build your own Space Agency.\n\n2. Buy orbital contracts for passive money. The displayed rates are per contract per minute. Income continues during expeditions, with the same two-hour offline accumulation limit as Earth.\n\n3. Choose the Moon first. Both outbound and return fees are charged before departure, so you cannot get stranded. Travel takes real time.\n\n4. Every player gets the same personal 6 × 6 planetary map. Nobody can block your access. Start a mine at the landing tile, then expand into adjacent tiles. Mines persist between visits and work while you are on the surface.\n\n5. Cargo space is limited. Return to Earth to deliver steel, uranium and gems; iridium is automatically sold for money. Cargo is credited once on arrival.\n\n6. Returning from the Moon unlocks Mars with two agency levels; returning from Mars unlocks Europa with three. Upgrade your agency and orbital businesses as your tycoon grows.`,async()=>{if(spaceSnapshot?.tutorial_required){const result=await api('POST','/api/space/tutorial/seen',{});if(result.error)throw new Error(result.error);spaceSnapshot.tutorial_required=false}spaceTutorialOpen=false},'I understand — start my space program');
}
function maybeSpaceTutorial(snapshot){if(snapshot.tutorial_required&&!spaceTutorialOpen&&!document.querySelector('.v6-overlay,.modal-overlay.open,#tut.open'))spaceTutorial()}
function formatSpaceCountdown(arrival){const seconds=Math.max(0,Math.ceil(Number(arrival)-Date.now()/1000));return `${Math.floor(seconds/60)}m ${seconds%60}s`}
function renderSpace(snapshot){
  spaceSnapshot=snapshot;const el=document.getElementById('space-content');if(!el)return;
  const program=snapshot.program,travel=program&&['outbound','returning'].includes(program.state);
  if(!snapshot.unlocked&&!program){el.innerHTML=card('🚀 Build a space empire','<p>A late-game tycoon beyond nuclear technology. Research <b>Spaceflight</b>, then build your own <b>Space Agency</b> on Earth.</p><p>Earn from orbital businesses, explore personal planetary maps, and bring valuable cargo home. Every player has equal access.</p><button class="btn btn-primary" onclick="showPanel(\'research\')">🔬 Open research</button>');return}
  const cargo=program?.cargo||{},used=Object.values(cargo).reduce((a,b)=>a+b,0),planet=snapshot.planets.find(p=>p.key===program?.planet);
  el.innerHTML=card('🚀 Space program',`<div class="space-summary"><div><span>Location</span><b>${travel?(program.state==='outbound'?'Outbound':'Returning'):program?.state==='surface'?esc(planet?.name):'Earth'}</b></div><div><span>Orbital money / min</span><b>${fmtN(snapshot.income.money||0)}</b></div><div><span>Cargo used</span><b>${fmtN(used)} / ${fmtN(snapshot.cargo_capacity)}</b></div></div>${travel?`<p class="travel-status" aria-live="polite">${program.state==='outbound'?'Arriving at '+esc(planet?.name):'Returning to Earth'} in <b id="space-countdown" data-arrival="${program.arrival}">${formatSpaceCountdown(program.arrival)}</b></p>`:''}<button class="btn btn-ghost btn-sm" onclick="spaceTutorial()">📖 Space guide</button>${program?.state==='surface'?'<button class="btn btn-primary" onclick="spaceAction(\'/api/space/return\',{})">🌍 Return to Earth · prepaid</button>':''}${!snapshot.unlocked?'<p class="v4-sub">Your agency is unavailable. Orbital income is paused; your prepaid expedition can still return.</p>':''}`)+
    card('🛰 Orbital businesses',`<p>Buy any affordable number of contracts. Each continues earning while you explore.</p><div class="space-businesses">${Object.entries(snapshot.businesses).map(([key,b])=>`<article class="space-business"><h4>${b.icon} ${esc(b.name)}</h4><p>Owned: <b>${fmtN(snapshot.holdings[key]||0)}</b></p><p class="income-highlight">${Object.entries(b.production).map(([r,v])=>'+'+fmtN(v)+' '+r+'/min').join(' · ')}</p><p>${fmtCost(b.cost)} each</p><label for="space-qty-${key}">Quantity</label><input id="space-qty-${key}" class="form-input" type="number" min="1" step="1" value="1"><div class="v4-row"><button class="btn btn-ghost btn-sm" onclick="maxSpaceBusiness('${key}')">Max affordable</button><button class="btn btn-primary btn-sm" ${snapshot.unlocked?'':'disabled'} onclick="buySpaceBusiness('${key}')">Buy contracts</button></div></article>`).join('')}</div>`)+
    card('🪐 Expeditions',`<p>Personal worlds, identical access. Both travel legs are paid on departure. Your mines stay for future visits.</p>${snapshot.planets.map(p=>`<div class="planet-choice"><div><b>${p.icon} ${esc(p.name)}</b><p class="v4-sub">${p.travel_seconds/60} min each way · ${p.yield_multiplier}× mineral output<br>Iridium: ${fmtN(p.iridium_price)} money / unit</p><p class="v4-sub">Outbound ${fmtCost(p.outbound)}<br>Return ${fmtCost(p.return)}</p>${p.lock_reason?`<p>${esc(p.lock_reason)}</p>`:''}</div><button class="btn btn-primary" ${p.available&&program?.state==='earth'?'':'disabled'} onclick="departSpace('${p.key}')">🚀 Depart</button></div>`).join('')}`)+
    (program?.planet?card(`🗺 ${esc(planet?.name)} · your personal map`,`${program.state==='surface'?'<p>Start at the landing tile, then expand to adjacent tiles. Select a tile to review its mine and cost.</p>':'<p>The surface opens on arrival. Mines produce only while you are on the surface.</p>'}<div class="planet-grid" style="--planet-size:${snapshot.grid_size}" role="group" aria-label="Personal planetary map">${snapshot.tiles.map(tile=>`<button class="planet-tile ${tile.resource} ${tile.level?'owned':''}" ${program.state==='surface'?'':'disabled'} aria-label="Tile ${tile.x+1}, ${tile.y+1}: ${tile.resource}, mine level ${tile.level}" onclick="inspectPlanetTile(${tile.x},${tile.y})"><span>${({steel:'🔩',uranium:'☢',gems:'💎',iridium:'✨'})[tile.resource]}</span><small>${tile.level?'Lv '+tile.level:tile.can_build?'＋':'·'}</small></button>`).join('')}</div><div class="cargo-list">${Object.entries(cargo).map(([r,v])=>`<span>${esc(r)} <b>${fmtN(v,1)}</b></span>`).join('')||'Cargo is empty.'}</div><p class="v4-sub">Iridium sells for ${fmtN(snapshot.iridium_price)} money per unit on Earth. Mining pauses when cargo is full.</p>`):'');
  const sections=[...el.querySelectorAll(':scope > .v4-card')];
  ['summary','businesses','travel','surface'].forEach((id,index)=>{if(sections[index])sections[index].id='space-section-'+id});
  sections[0]?.insertAdjacentHTML('beforeend',`<nav class="space-shortcuts" aria-label="Space sections"><button class="btn btn-ghost btn-sm" onclick="scrollSpaceSection('businesses')">🛰 Businesses</button><button class="btn btn-ghost btn-sm" onclick="scrollSpaceSection('travel')">🪐 Travel</button>${sections[3]?'<button class="btn btn-ghost btn-sm" onclick="scrollSpaceSection(\'surface\')">🗺 Surface</button>':''}</nav>`);
}
function scrollSpaceSection(id){document.getElementById('space-section-'+id)?.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}
buildSpace=async function(){
  const el=document.getElementById('space-content'),generation=sessionGeneration,uid=currentUser?.id;
  if(!uid){el.textContent='Log in to build your space program.';return}
  el.setAttribute('aria-busy','true');
  try{const result=await api('GET','/api/space');if(generation!==sessionGeneration||uid!==currentUser?.id)return;if(result.error){el.textContent=result.error;return}renderSpace(result);maybeSpaceTutorial(result)}finally{el.setAttribute('aria-busy','false')}
};
async function spaceAction(path,data){const r=await act(path,data);if(!r.error)await buildSpace();return r}
function maxSpaceBusiness(key){const costs=spaceSnapshot.businesses[key].cost;document.getElementById('space-qty-'+key).value=Math.max(1,Math.min(...Object.entries(costs).map(([r,v])=>Math.floor((currentUser[r]||0)/v))))}
async function buySpaceBusiness(key){const quantity=Number(document.getElementById('space-qty-'+key).value);if(!Number.isSafeInteger(quantity)||quantity<1)return toast('Choose a positive whole quantity','error');const b=spaceSnapshot.businesses[key],cost=Object.fromEntries(Object.entries(b.cost).map(([r,v])=>[r,v*quantity]));if(!confirm(`Buy ${fmtN(quantity)} ${b.name} contracts? Cost: ${fmtCost(cost)}`))return;await spaceAction('/api/space/business',{business:key,quantity})}
async function departSpace(key){const planet=spaceSnapshot.planets.find(p=>p.key===key);if(!confirm(`Depart for ${planet.name}?\nOutbound: ${fmtCost(planet.outbound)}\nReturn: ${fmtCost(planet.return)}\nBoth legs are charged now. Travel takes ${planet.travel_seconds/60} minutes each way.`))return;await spaceAction('/api/space/depart',{planet:key})}
function inspectPlanetTile(x,y){
  const snapshot=spaceSnapshot,tile=snapshot.tiles.find(t=>t.x===x&&t.y===y),full=tile.level>=snapshot.mine_max_level;
  const dialog=expansionDialog(`Planet tile ${x+1}, ${y+1}`,`<p><b>${esc(tile.resource)}</b> · ${tile.level?'Mine level '+tile.level:'Undeveloped'}</p><p>Output: ${fmtN(tile.rate,1)} / min ${tile.level?'currently':'at level 1'}. Mining runs while you are on the surface.</p><p>${full?'Highest mine tier reached.':fmtCost(tile.cost)+(tile.level?' to upgrade':' to build')}</p>${!tile.can_build?'<p>Expand from an adjacent mine, starting at the landing tile.</p>':''}<button id="planet-build" class="btn btn-primary" ${full||!tile.can_build?'disabled':''}>${tile.level?'⬆ Upgrade mine':'⛏ Build mine'}</button>`);
  dialog.querySelector('#planet-build').onclick=async e=>{e.target.disabled=true;const r=await spaceAction('/api/space/mine',{x,y});if(!r.error)dialog.remove();else e.target.disabled=false};
}
addNavigation('space','🚀 Space',buildSpace);menuItems.space={icon:'🚀',name:'Space',desc:'Orbital businesses and personal planetary expeditions'};
menuHome=function(){
  const groups=[['BUILD YOUR COUNTRY',['territory','empire','research','quests']],['ECONOMY & SPACE',['market','stocks','banks','space']],['PLAY TOGETHER',['chat','faction','social','trading','playtime']],['COMMAND & HISTORY',['operations','battles','leaderboard']]];
  if(currentUser?.is_admin||currentUser?.is_moderator)groups.push(['HOST TOOLS',['moderation',...(currentUser.is_admin?['catalog']:[])]]);
  return groups.map(([label,ids])=>`<h3 class="menu-group-title">${label}</h3><div class="more-grid">${ids.map(id=>{const item=menuItems[id];return `<button onclick="openExpansionPanel('${id}')"><span>${item.icon}</span>${esc(item.name)}<small>${esc(item.desc)}</small></button>`}).join('')}</div>`).join('');
};
document.querySelector('.sidebar-tabs').setAttribute('role','tablist');
for(const button of document.querySelectorAll('.sidebar-tabs .stab')){
  const id=button.dataset.panel,item=menuItems[id];if(!item)continue;
  button.id='nav-'+id;button.setAttribute('role','tab');button.setAttribute('aria-controls','panel-'+id);button.setAttribute('aria-selected',String(button.classList.contains('active')));
  button.innerHTML=`<span class="si" aria-hidden="true">${item.icon}</span>${esc(item.name)}<i class="dot"></i>`;button.title=item.desc;
  const panel=document.getElementById('panel-'+id);if(panel){panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',button.id)}
  decoratePanel(id);
}
const progressionShowPanel=showPanel;
showPanel=function(id){const result=progressionShowPanel(id);for(const button of document.querySelectorAll('.sidebar-tabs .stab'))button.setAttribute('aria-selected',String(button.dataset.panel===id));return result};

const progressionStop=stopPolling;
stopPolling=function(){cancelBattlePlan();clearPrivateBattles();spaceSnapshot=null;spaceTutorialOpen=false;inboxNotifications=[];inboxUser=null;updateNotificationCount();progressionStop()};
const progressionSession=startSession;
startSession=async function(user){
  cancelBattlePlan();clearPrivateBattles();spaceSnapshot=null;spaceTutorialOpen=false;
  const result=await progressionSession(user);if(result===false||!currentUser)return result;
  const generation=sessionGeneration,uid=currentUser.id;
  const poll=async()=>{
    if(document.hidden||progressionBusy||generation!==sessionGeneration||uid!==currentUser?.id)return;
    progressionBusy=true;
    try{const battles=await api('GET','/api/campaigns');if(generation!==sessionGeneration)return;if(battles.error){clearPrivateBattles();return}drawPrivateBattles(battles.campaigns);if(document.getElementById('operations-content')?.getClientRects().length)renderOperations(battles);
      const visible=document.getElementById('space-content')?.getClientRects().length,unlock=(currentUser?.building_counts?.space_agency?.count||0)>0;
      if(visible||unlock&&!spaceSnapshot){const space=await api('GET','/api/space');if(generation!==sessionGeneration||space.error)return;const changed=spaceSnapshot?.program?.state!==space.program?.state;spaceSnapshot=space;if(visible&&(changed||!document.getElementById('space-content').contains(document.activeElement)))renderSpace(space);maybeSpaceTutorial(space)}else if(spaceSnapshot)maybeSpaceTutorial(spaceSnapshot);
    }finally{progressionBusy=false}
  };
  await poll();pollHandles.push(setInterval(poll,4000));
  pollHandles.push(setInterval(()=>{const counter=document.getElementById('space-countdown');if(counter){counter.textContent=formatSpaceCountdown(counter.dataset.arrival)}},1000));
  return result;
};
startGame=startSession;startSpectatorMode=()=>startSession(null);
// Notifications remain unread until explicitly dismissed in the bell inbox.
let inboxNotifications=[],inboxUser=null;
pollNotifications=async function(){
  const uid=currentUser?.id;if(!uid){inboxNotifications=[];updateNotificationCount();return}
  const generation=sessionGeneration,list=await api('GET','/api/notifications');
  if(generation!==sessionGeneration||currentUser?.id!==uid||!Array.isArray(list))return;
  inboxUser=uid;inboxNotifications=list;updateNotificationCount();
};
function updateNotificationCount(){const count=document.getElementById('notification-count');if(count)count.textContent=currentUser?.id===inboxUser&&inboxNotifications.length?` ${inboxNotifications.length}`:''}
async function openNotificationInbox(){
  if(!currentUser)return;await pollNotifications();if(!currentUser||inboxUser!==currentUser.id)return;
  openCommunityDialog('🔔 Notifications',`<p>Unread messages stay here until dismissed.</p>${inboxNotifications.length?'<button class="btn btn-ghost" onclick="dismissInboxNotifications()">Dismiss all</button>':'<p>No unread notifications.</p>'}<div id="notification-inbox">${inboxNotifications.map(n=>`<article class="v4-card"><p>${esc(n.message)}</p><small>${esc(n.created_at||'')}</small><div class="v4-row">${n.type==='alliance_invite'&&n.data?.alliance_id?`<button class="btn btn-primary" onclick="inboxAlliance(${n.id},true)">Accept</button><button class="btn btn-ghost" onclick="inboxAlliance(${n.id},false)">Decline</button>`:(n.data?.actions||[]).map((a,i)=>`<button class="btn btn-primary" onclick="inboxAction(${n.id},${i})">${esc(a.label)}</button>`).join('')}<button class="btn btn-ghost" onclick="dismissInboxNotifications(${n.id})">Dismiss</button></div></article>`).join('')}</div>`);
}
async function dismissInboxNotifications(id){const r=await api('POST',id===undefined?'/api/notifications/dismiss_all':'/api/notifications/dismiss',id===undefined?{}:{id});if(r.error)return toast(r.error,'error');await openNotificationInbox()}
async function inboxAlliance(id,accept){const n=inboxNotifications.find(n=>n.id===id);if(!n)return;const r=await api('POST','/api/alliance/respond',{alliance_id:n.data.alliance_id,accept});if(r.error)return toast(r.error,'error');await dismissInboxNotifications(id);await refreshUser()}
async function inboxAction(id,index){const action=inboxNotifications.find(n=>n.id===id)?.data?.actions?.[index];if(!action)return;const r=await api('POST',action.path,action.body);if(r.error)return toast(r.error,'error');await dismissInboxNotifications(id);await refreshAll()}
