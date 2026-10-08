
'use strict';
// ══════════════════════════════════════════════════
//  CONFIG (mirrors Python)
// ══════════════════════════════════════════════════
const GRID = 0.18;
const CLAIM_COST = 25; // base cost — scales with territory count
// Boats & planes are single-use with unlimited range (overseas only)
const SELL_RATES = {food:2,wood:4,metal:6,oil:10};
const BOAT_COST = 800;
const PLANE_COST = 1200;

const TERRAIN_CFG = {
  plains:    {icon:'🌾',label:'Plains',   res:'food', rate:9,  color:'#4a7c3f'},
  forest:    {icon:'🌲',label:'Forest',   res:'wood', rate:12, color:'#2d5a27'},
  mountains: {icon:'⛰', label:'Mountains',res:'metal',rate:9,  color:'#6b5b45'},
  desert:    {icon:'🏜',label:'Desert',   res:'money',rate:7,  color:'#9b7e45'},
  tundra:    {icon:'❄', label:'Tundra',   res:'metal',rate:5,  color:'#5a7a8a'},
  city:      {icon:'🏙',label:'City',     res:'money',rate:18, color:'#b8860b'},
  oil:       {icon:'🛢',label:'Oil Field',res:'oil',  rate:14, color:'#3a3a5a'},
};
const RES_CFG = {
  food: {icon:'🌾',label:'Food'}, wood:  {icon:'🌲',label:'Wood'},
  metal:{icon:'⚙', label:'Metal'},oil:   {icon:'🛢',label:'Oil'},
  money:{icon:'💰',label:'Money'},
};
const RESEARCH_TREE = {
  agri:      {name:'Agriculture',      icon:'🌾',cost:100,branch:'economy', requires:[],           desc:'+25% food & wood yield'},
  trade:     {name:'Trade Routes',     icon:'💹',cost:150,branch:'economy', requires:['agri'],     desc:'+15% money yield'},
  industry:  {name:'Industrialization',icon:'⚙',cost:250,branch:'economy', requires:['trade'],    desc:'+25% metal & oil yield'},
  iron:      {name:'Iron Weapons',     icon:'⚔',cost:100,branch:'military',requires:[],           desc:'+20% attack strength'},
  castle:    {name:'Castle Walls',     icon:'🏰',cost:100,branch:'military',requires:[],           desc:'+30% defense bonus'},
  gunpowder: {name:'Gunpowder',        icon:'💥',cost:250,branch:'military',requires:['iron'],     desc:'+30% attack, -20% troop cost'},
  shipyard:  {name:'Shipbuilding',     icon:'⚓',cost:200,branch:'naval',   requires:[],           desc:'Unlocks Boats'},
  airforce:  {name:'Air Force',        icon:'✈',cost:400,branch:'naval',   requires:['shipyard'], desc:'Unlocks Planes'},
  blitz:     {name:'Blitzkrieg',       icon:'⚡',cost:600,branch:'naval',   requires:['airforce'], desc:'Planes range +3, +20% power'},
};
const RANKS = [
  {min:0,  icon:'🪓',name:'Settler'},
  {min:3,  icon:'⚔', name:'Warrior'},
  {min:10, icon:'🛡',name:'Commander'},
  {min:25, icon:'🏰',name:'Warlord'},
  {min:60, icon:'👑',name:'Emperor'},
  {min:150,icon:'🌍',name:'Conqueror'},
];

// ══════════════════════════════════════════════════
//  STATE
// ══════════════════════════════════════════════════
let map, canvasR;
let currentUser   = null;
let territories   = {};
let tlayers       = {};
let selectedKey   = null;
let hoverRect     = null;
let landGeoJSON   = null;
let landCache     = {};
let refreshTimer  = null;
let winCheckTimer = null;
let lastSeenAnnId = 0;
let onlineCollapsed = false;
let mobileView    = 'map';
let adminUserList = [];
let spectatorTimer = null;
let myAlliances   = []; // [{id, status, ally_id, ally_name, ally_color, is_requester}]
let seenNotifIds  = new Set();

// ══════════════════════════════════════════════════
//  UTILITIES
// ══════════════════════════════════════════════════
function simpleHash(gl,gg){const s=`${gl},${gg}`;let h=0;for(const c of s)h=(h*31+c.charCodeAt(0))%10007;return h}
function getTerrainClient(gl,gg){
  const h=simpleHash(gl,gg),lat=gl*GRID;
  let opts;
  if(Math.abs(lat)>65)      opts=['tundra'];
  else if(Math.abs(lat)>55) opts=['tundra','tundra','forest','mountains','plains'];
  else if(Math.abs(lat)>40) opts=['plains','plains','forest','forest','mountains','city'];
  else if(Math.abs(lat)>20) opts=['plains','desert','desert','mountains','city','oil','forest'];
  else                       opts=['forest','forest','forest','plains','desert','city','oil'];
  return opts[h%opts.length];
}
function parseKey(k){const p=k.split(',');return[parseInt(p[0]),parseInt(p[1])]}
function gridKey(lat,lng){return`${Math.floor(lat/GRID)},${Math.floor(lng/GRID)}`}
function cellBounds(gl,gg){return[[gl*GRID,gg*GRID],[(gl+1)*GRID,(gg+1)*GRID]]}
function cellCenter(gl,gg){return[(gl+.5)*GRID,(gg+.5)*GRID]}
function adjKeys(gl,gg){const r=[];for(let dl=-1;dl<=1;dl++)for(let dg=-1;dg<=1;dg++)if(dl||dg)r.push(`${gl+dl},${gg+dg}`);return r}
function myAdjKeys(gl,gg){return adjKeys(gl,gg).filter(k=>territories[k]?.owner_id===currentUser?.id)}
function cellDist(k1,k2){const[a,b]=parseKey(k1),[c,d]=parseKey(k2);return Math.max(Math.abs(a-c),Math.abs(b-d))}
function hexRgba(hex,a){const r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);return`rgba(${r},${g},${b},${a})`}
function fmtPop(n){if(!n)return'0';if(n>=1000000)return(n/1e6).toFixed(1)+'M';if(n>=1000)return(n/1000).toFixed(0)+'K';return String(n)}
function getRank(tc){let r=RANKS[0];for(const x of RANKS)if(tc>=x.min)r=x;return r}
function isMobile(){return window.innerWidth<=768}

// ══════════════════════════════════════════════════
//  LAND CHECK
// ══════════════════════════════════════════════════
async function loadLandGeoJSON(){
  try{
    const ctrl=new AbortController();
    const tid=setTimeout(()=>ctrl.abort(),8000);
    const r=await fetch('/api/land',{signal:ctrl.signal});
    clearTimeout(tid);
    if(!r.ok)throw new Error();
    landGeoJSON=await r.json();
  }catch(e){landGeoJSON=null}
}
function isLand(gl,gg){
  const k=`${gl},${gg}`;if(k in landCache)return landCache[k];
  if(!landGeoJSON)return true;
  const[lat,lng]=cellCenter(gl,gg);
  const pt=turf.point([lng,lat]);
  const onLand=landGeoJSON.features.some(f=>{try{return turf.booleanPointInPolygon(pt,f)}catch{return false}});
  return(landCache[k]=onLand);
}

// ══════════════════════════════════════════════════
//  API
// ══════════════════════════════════════════════════
async function api(method,path,body){
  const opts={method,headers:{'Content-Type':'application/json'},credentials:'same-origin'};
  if(body)opts.body=JSON.stringify(body);
  try{const r=await fetch(path,opts);return r.json();}
  catch(e){return{error:'Network error'}}
}

// ══════════════════════════════════════════════════
//  MAP
// ══════════════════════════════════════════════════
function initMap(){
  canvasR=L.canvas({padding:.5});
  const worldBounds=L.latLngBounds(L.latLng(-85,-180),L.latLng(85,180));
  map=L.map('map',{
    zoomControl:true,attributionControl:true,preferCanvas:true,
    worldCopyJump:false,maxBoundsViscosity:1.0,
    maxBounds:worldBounds,minZoom:2
  }).setView([30,15],4);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{
    attribution:'&copy; <a href="https://carto.com/">CARTO</a>',maxZoom:14,minZoom:2,
    noWrap:true,bounds:worldBounds
  }).addTo(map);
  map.on('mousemove',onMapMove);
  map.on('click',onMapClick);
  // The active client installs one resize listener for the map and mobile sheet.
}
function onMapMove(e){
  const{lat,lng}=e.latlng;
  const gl=Math.floor(lat/GRID),gg=Math.floor(lng/GRID);
  if(hoverRect)hoverRect.setBounds(cellBounds(gl,gg));
  else hoverRect=L.rectangle(cellBounds(gl,gg),{color:'rgba(255,255,255,.45)',weight:1,fillOpacity:.05,interactive:false,renderer:canvasR}).addTo(map);
}
function onMapClick(e){
  const{lat,lng}=e.latlng;
  const gl=Math.floor(lat/GRID),gg=Math.floor(lng/GRID);
  const key=`${gl},${gg}`;
  selectTerritory(key);
  if(isMobile()){
    document.getElementById('mobile-sheet').classList.add('open');
    document.querySelectorAll('.mnav-btn').forEach(b=>b.classList.remove('active'));
    document.querySelector('.mnav-btn[data-mn="territory"]')?.classList.add('active');
  } else {
    showPanel('territory');
  }
  fetchAndBuildPanel(key);
}

// ══════════════════════════════════════════════════
//  RENDER TERRITORIES
// ══════════════════════════════════════════════════
function renderTerritories(){
  const owned=new Set(Object.keys(territories).filter(k=>territories[k].owner_id));
  for(const k of Object.keys(tlayers)){if(!owned.has(k)){map.removeLayer(tlayers[k]);delete tlayers[k]}}
  const allyIds=new Set(myAlliances.filter(a=>a.status==='active').map(a=>a.ally_id));
  for(const k of owned){
    const t=territories[k],[gl,gg]=parseKey(k);
    const color=t.color||'#888';
    const isMe=currentUser&&t.owner_id===currentUser.id;
    const isAlly=allyIds.has(t.owner_id);
    const isSel=k===selectedKey;
    const borderColor=isSel?'#f0c040':isAlly?'#2ecc71':hexRgba(color,.9);
    const borderWeight=isSel?2.5:isAlly?2:isMe?1.2:.8;
    const fillOpacity=isMe?.55:isAlly?.42:.37;
    const style={color:borderColor,weight:borderWeight,fillColor:color,fillOpacity,renderer:canvasR};
    if(tlayers[k])tlayers[k].setStyle(style);
    else{
      const cfg=TERRAIN_CFG[t.terrain]||{};
      const rect=L.rectangle(cellBounds(gl,gg),style).addTo(map);
      const units=[t.garrison&&`⚔${t.garrison}`,t.boats&&`⚓${t.boats}`,t.planes&&`✈${t.planes}`].filter(Boolean).join(' ');
      const allyLabel=isAlly?` 🤝`:'';
      rect.bindTooltip(
        `<b>${cfg.icon||''} ${cfg.label||t.terrain}${allyLabel}</b><br>${esc(t.owner||'?')}<br>👥${fmtPop(t.population)} ${units}`,
        {className:'map-tip',sticky:true,direction:'top'}
      );
      rect.on('click',()=>{selectTerritory(k);if(isMobile())openMobileSheet(k);else{showPanel('territory');fetchAndBuildPanel(k);}});
      tlayers[k]=rect;
    }
  }
}

function selectTerritory(key){
  selectedKey=key;
  renderTerritories();
  const[gl,gg]=parseKey(key);
  const terrain=territories[key]?.terrain||getTerrainClient(gl,gg);
  const cfg=TERRAIN_CFG[terrain]||{};
  const tInfoEl=document.getElementById('territory-info');
  if(tInfoEl) tInfoEl.innerHTML=`<div class="tc"><div class="tc-hdr"><span class="tc-icon">${cfg.icon||'?'}</span><div><div class="tc-title">${cfg.label||terrain}</div><div class="tc-sub">${(gl*GRID).toFixed(1)}°,${(gg*GRID).toFixed(1)}°</div></div></div><div style="color:var(--text3);font-size:11px">Loading…</div></div>`;
  const taEl=document.getElementById('territory-actions');
  if(taEl) taEl.innerHTML='';
}

// ══════════════════════════════════════════════════
//  TERRITORY PANEL BUILDER (reworked army UI)
// ══════════════════════════════════════════════════

function battleOdds(myStr, theirStr){
  // Returns a rough win% string and color
  if(theirStr===0) return {pct:99,color:'var(--green2)',label:'Undefended'};
  const ratio = myStr/(myStr+theirStr);
  const pct = Math.round(ratio*100);
  const color = pct>=65?'var(--green2)':pct>=45?'var(--accent2)':'var(--red2)';
  const label = pct>=65?'Favoured':pct>=45?'Even':'Risky';
  return {pct,color,label};
}

function buildTerritoryPanel(key,t,container){
  const[gl,gg]=parseKey(key);
  const terrain=t.terrain||getTerrainClient(gl,gg);
  const cfg=TERRAIN_CFG[terrain]||{};
  const isOwned=!!t.owner_id;
  const isMine=currentUser&&t.owner_id===currentUser.id;
  const myAdj=myAdjKeys(gl,gg);
  const myCount=Object.values(territories).filter(x=>x.owner_id===currentUser?.id).length;
  const canClaim=!isOwned&&(myAdj.length>0||myCount===0);
  const rsch=new Set(currentUser?.research||[]);

  if(landGeoJSON&&!isOwned&&!isLand(gl,gg)){
    const waterHTML='<div class="water-warn">🌊 Open Ocean — uncrossable without a navy</div>';
    if(container)container.innerHTML=waterHTML;
    else{document.getElementById('territory-info').innerHTML=waterHTML;document.getElementById('territory-actions').innerHTML='';}
    return;
  }

  // ── Header card ──
  const armyStr = t.garrison||0;
  const boatStr = t.boats||0;
  const planeStr = t.planes||0;

  const ownerLine = isOwned
    ? `<div class="tp-owner"><span class="owner-dot" style="background:${t.color}"></span> <strong style="color:${t.color}">${t.owner}</strong>${isMine?' <span style="color:var(--accent2);font-size:10px">(You)</span>':''}</div>`
    : `<div class="tp-owner" style="color:var(--text3)">Unclaimed Territory</div>`;

  const infoHTML=`<div class="tp-card">
    <div class="tp-head">
      <span class="tp-icon">${cfg.icon||'?'}</span>
      <div class="tp-head-info">
        <div class="tp-name">${cfg.label||terrain}</div>
        ${ownerLine}
      </div>
      <div class="tp-yield"><div>${RES_CFG[cfg.res]?.icon||''}+${cfg.rate}</div><div style="font-size:9px;color:var(--text3)">/min</div></div>
    </div>
    <div class="tp-stats">
      <div class="tp-stat${isMine?' tp-mine':''}">
        <div class="tp-stat-val">${armyStr}</div>
        <div class="tp-stat-label">⚔ Soldiers</div>
      </div>
      ${boatStr>0?`<div class="tp-stat"><div class="tp-stat-val">${boatStr}</div><div class="tp-stat-label">⚓ Boats</div></div>`:''}
      ${planeStr>0?`<div class="tp-stat"><div class="tp-stat-val">${planeStr}</div><div class="tp-stat-label">✈ Planes</div></div>`:''}
      <div class="tp-stat">
        <div class="tp-stat-val" style="font-size:11px">${fmtPop(t.population)}</div>
        <div class="tp-stat-label">👥 Pop</div>
      </div>
    </div>
  </div>`;

  let actHTML='';
  if(currentUser){
    if(isMine){
      const tc=troop_cost(rsch);
      // ── Recruit soldiers ──
      actHTML+=`<div class="army-section">
        <div class="army-section-title">⚔ Recruit Soldiers <span class="keybind-hint">B</span></div>
        <div class="army-recruit-row">
          <div class="army-slider-wrap">
            <input type="range" class="army-slider" id="build-slider" min="1" max="100" value="5"/>
            <div class="army-slider-labels"><span>1</span><span id="build-slider-val">5</span><span>100</span></div>
          </div>
          <div class="army-cost-badge"><span id="build-cost">${5*tc}</span>💰</div>
          <button class="btn btn-primary" onclick="buildTroops('${key}')">Recruit</button>
        </div>
        <div style="font-size:10px;color:var(--text3);margin-top:3px">${tc}💰 per soldier${rsch.has('gunpowder')?' (gunpowder discount)':''}</div>
      </div>`;

      // ── Move soldiers ──
      const adjO=adjKeys(gl,gg).filter(k=>territories[k]?.owner_id===currentUser.id&&territories[k].garrison>1);
      if(adjO.length>0||armyStr>1){
        const moveFrom=adjO.length>0;
        const moveTargets=adjO.map(k=>{const[al,ag]=parseKey(k);const at=TERRAIN_CFG[territories[k]?.terrain]||{};return`<option value="${k}">${at.icon||''} ${(al*GRID).toFixed(1)}°,${(ag*GRID).toFixed(1)}° — ${territories[k]?.garrison||0} soldiers</option>`}).join('');
        const fromAdj=adjKeys(gl,gg).filter(k=>territories[k]?.owner_id===currentUser.id);
        const fromOpts=fromAdj.map(k=>{const[al,ag]=parseKey(k);const at=TERRAIN_CFG[territories[k]?.terrain]||{};return`<option value="${k}">${at.icon||''} ${(al*GRID).toFixed(1)}°,${(ag*GRID).toFixed(1)}° — ${territories[k]?.garrison||0} soldiers</option>`}).join('');
        if(armyStr>1&&fromAdj.length>0){
          actHTML+=`<div class="army-section">
            <div class="army-section-title">🚶 Move Soldiers to Adjacent</div>
            <div class="move-row">
              <input type="number" class="input-sm" id="move-amt" value="1" min="1" max="${armyStr-1}" style="width:64px"/>
              <span style="font-size:18px;color:var(--text3)">→</span>
              <select class="input-sm" id="move-to" style="flex:1">${fromOpts}</select>
              <button class="btn btn-ghost btn-sm" onclick="moveTroops('${key}')">Move</button>
            </div>
          </div>`;
        }
      }

      // ── Build boats ──
      actHTML+=`<div class="army-section">
        <div class="army-section-title">⚓ Build Boats <span style="font-size:10px;color:var(--text3);font-weight:400">1,000💰 each · single-use overseas</span></div>
        <div class="move-row">
          <input type="number" class="input-sm" id="boat-amt" value="1" min="1" max="10" style="width:64px"/>
          <span style="font-size:11px;color:var(--text3)">= <span id="boat-build-cost">1000</span>💰</span>
          <button class="btn btn-blue btn-sm" onclick="buildBoats('${key}')">⚓ Build</button>
        </div>
      </div>`;

      // ── Build planes ──
      actHTML+=`<div class="army-section">
        <div class="army-section-title">✈ Build Planes <span style="font-size:10px;color:var(--text3);font-weight:400">1,000💰 each · single-use overseas</span></div>
        <div class="move-row">
          <input type="number" class="input-sm" id="plane-amt" value="1" min="1" max="10" style="width:64px"/>
          <span style="font-size:11px;color:var(--text3)">= <span id="plane-build-cost">1000</span>💰</span>
          <button class="btn btn-blue btn-sm" onclick="buildPlanes('${key}')">✈ Build</button>
        </div>
      </div>`;

    } else if(canClaim){
      // ── Claim ──
        const claimCost=myCount>=200?1200:myCount>=100?400:myCount>=50?150:myCount>=20?80:myCount>=8?40:25;
        actHTML+=`<div class="claim-block">
          <button class="btn btn-primary btn-full claim-btn" onclick="claimTerritory('${key}')">
            🏴 Claim Territory — ${claimCost}💰 <span class="keybind-hint">C</span>
          </button>
          <div class="claim-info">${cfg.icon} Yields ${RES_CFG[cfg.res]?.icon||''} ${cfg.rate}/min · 👥 ${fmtPop(t.population)}</div>
        </div>`;

    } else if(isOwned&&!isMine&&myAdj.length>0){
      // Check alliance status
      const allyEntry=myAlliances.find(a=>a.ally_id===t.owner_id&&a.status==='active');
      const pendingEntry=myAlliances.find(a=>a.ally_id===t.owner_id&&a.status==='pending');

      if(allyEntry){
        // ── Allied territory ──
        actHTML+=`<div class="ally-territory-label">🤝 Allied with ${t.owner}</div>`;
        // Allow troop reinforcement from adjacent own territory
        const myAdjArr=myAdj;
        const adjOpts2=myAdjArr.map(k=>{const[al,ag]=parseKey(k);const at=TERRAIN_CFG[territories[k]?.terrain]||{};const g=territories[k]?.garrison||0;return`<option value="${k}"${' selected'}>${at.icon||''} ${(al*GRID).toFixed(1)}°,${(ag*GRID).toFixed(1)}° · ${g} soldiers</option>`}).join('');
        actHTML+=`<div class="army-section">
          <div class="army-section-title">🤝 Send Troops to Ally</div>
          <div class="move-row">
            <input type="number" class="input-sm" id="ally-move-amt" value="1" min="1" style="width:64px"/>
            <span style="font-size:18px;color:var(--text3)">→</span>
            <select class="input-sm" id="ally-move-from" style="flex:1">${adjOpts2}</select>
            <button class="btn btn-success btn-sm" onclick="allyMoveTroops('${key}')">Send</button>
          </div>
        </div>
        <div style="margin-top:6px">
          <button class="btn btn-danger btn-full" onclick="breakAllianceByAllyId(${t.owner_id})">💔 Break Alliance</button>
        </div>`;
      } else {
        // ── Land attack (not allied) ──
      // Auto-pick best adjacent territory (most soldiers)
      const bestAdj=myAdj.reduce((best,k)=>(!best||(territories[k]?.garrison||0)>(territories[best]?.garrison||0))?k:best,null);
      const myAtkStr=territories[bestAdj]?.garrison||0;
      const odds=battleOdds(myAtkStr, armyStr);
      const adjOpts=myAdj.map(k=>{const[al,ag]=parseKey(k);const at=TERRAIN_CFG[territories[k]?.terrain]||{};const g=territories[k]?.garrison||0;return`<option value="${k}"${k===bestAdj?' selected':''}>${at.icon||''} ${(al*GRID).toFixed(1)}°,${(ag*GRID).toFixed(1)}° · ${g} soldiers</option>`}).join('');

      actHTML+=`<div class="army-section attack-section">
        <div class="army-section-title" style="color:var(--red2)">⚔ Land Attack</div>
        <div class="battle-preview">
          <div class="battle-side">
            <div class="battle-side-label">Your Attack</div>
            <div class="battle-side-str" id="atk-str-display">${myAtkStr}</div>
            <div class="battle-side-sub">soldiers</div>
          </div>
          <div class="battle-vs">
            <div class="battle-odds" style="color:${odds.color}">${odds.pct}%</div>
            <div class="battle-odds-label" style="color:${odds.color}">${odds.label}</div>
          </div>
          <div class="battle-side">
            <div class="battle-side-label">Their Defense</div>
            <div class="battle-side-str" style="color:var(--red2)">${armyStr}</div>
            <div class="battle-side-sub">soldiers</div>
          </div>
        </div>
        <div class="attack-controls">
          <div style="font-size:11px;color:var(--text3);margin-bottom:5px">Attack from:</div>
          <select class="input-sm" id="atk-from" style="width:100%;margin-bottom:8px" onchange="updateAtkPreview('${key}')">${adjOpts}</select>
          <div class="move-row">
            <input type="number" class="input-sm" id="atk-troops" value="${Math.max(1,Math.floor(myAtkStr*0.7))}" min="1" max="${Math.max(1,myAtkStr-1)}" style="width:70px" oninput="updateAtkPreview('${key}')"/>
            <span style="font-size:11px;color:var(--text3)">soldiers to send</span>
            <button class="btn btn-danger btn-sm" style="flex:1" onclick="attackTerritory('${key}')">⚔ Attack</button>
          </div>
        </div>
      </div>`;

      // Overseas boats/planes if any
      const myBoatSrcs=Object.keys(territories).filter(k=>territories[k]?.owner_id===currentUser.id&&territories[k]?.boats>0&&cellDist(k,key)>1);
      const myPlaneSrcs=Object.keys(territories).filter(k=>territories[k]?.owner_id===currentUser.id&&territories[k]?.planes>0&&cellDist(k,key)>1);
      if(myBoatSrcs.length>0){
        const boatOpts=myBoatSrcs.map(k=>{const[al,ag]=parseKey(k);return`<option value="${k}">${(al*GRID).toFixed(1)}°,${(ag*GRID).toFixed(1)}° · ${territories[k].boats} boats</option>`}).join('');
        actHTML+=`<div class="army-section"><div class="army-section-title" style="color:#7ab8e8">⚓ Naval Support</div>
          <select class="input-sm" id="boat-from" style="width:100%;margin-bottom:5px">${boatOpts}</select>
          <div class="move-row"><input type="number" class="input-sm" id="boat-troops" value="1" min="1" style="width:64px"/>
          <span style="font-size:11px;color:var(--text3)">boats (consumed)</span>
          <button class="btn btn-blue btn-sm" style="flex:1" onclick="navalAttack('${key}')">⚓ Launch</button></div></div>`;
      }
      if(myPlaneSrcs.length>0){
        const planeOpts=myPlaneSrcs.map(k=>{const[al,ag]=parseKey(k);return`<option value="${k}">${(al*GRID).toFixed(1)}°,${(ag*GRID).toFixed(1)}° · ${territories[k].planes} planes</option>`}).join('');
        actHTML+=`<div class="army-section"><div class="army-section-title" style="color:#aaaaff">✈ Air Support</div>
          <select class="input-sm" id="plane-from" style="width:100%;margin-bottom:5px">${planeOpts}</select>
          <div class="move-row"><input type="number" class="input-sm" id="plane-troops" value="1" min="1" style="width:64px"/>
          <span style="font-size:11px;color:var(--text3)">planes (consumed)</span>
          <button class="btn btn-sm" style="flex:1;background:#4a4a8a;color:#fff" onclick="airAttack('${key}')">✈ Strike</button></div></div>`;
      }
      // Alliance invite option
      if(t.owner_id){
        const pendingEntry2=myAlliances.find(a=>a.ally_id===t.owner_id&&a.status==='pending');
        if(pendingEntry2){
          actHTML+=`<div style="margin-top:8px;font-size:11px;color:var(--accent2);text-align:center;padding:6px;background:rgba(200,150,58,.08);border-radius:3px;border:1px solid rgba(200,150,58,.2)">⏳ Alliance invite pending with ${t.owner}</div>`;
        } else {
          actHTML+=`<div style="margin-top:8px"><button class="btn btn-ghost btn-full" style="font-size:11px" onclick="sendAllianceInviteFromPanel('${t.owner}')">🤝 Propose Alliance to ${t.owner}</button></div>`;
        }
      }
      } // end else (not ally)

      // No land adjacency — check overseas options
      const overseasBoats=Object.keys(territories).filter(k=>territories[k]?.owner_id===currentUser.id&&territories[k]?.boats>0&&cellDist(k,key)>1);
      const overseasPlanes=Object.keys(territories).filter(k=>territories[k]?.owner_id===currentUser.id&&territories[k]?.planes>0&&cellDist(k,key)>1);
      if(overseasBoats.length>0||overseasPlanes.length>0){
        actHTML+=`<div style="font-size:11px;color:var(--accent2);padding:6px 0 2px;font-weight:600">🌊 Overseas ${isOwned?'Attack':'Landing'}</div>`;
        if(overseasBoats.length>0){
          const boatOpts=overseasBoats.map(k=>{const[al,ag]=parseKey(k);return`<option value="${k}">${(al*GRID).toFixed(1)}°,${(ag*GRID).toFixed(1)}° · ${territories[k].boats} boats</option>`}).join('');
          actHTML+=`<div class="army-section"><div class="army-section-title" style="color:#7ab8e8">⚓ Naval Landing</div>
            <select class="input-sm" id="boat-from" style="width:100%;margin-bottom:5px">${boatOpts}</select>
            <div class="move-row"><input type="number" class="input-sm" id="boat-troops" value="1" min="1" style="width:64px"/>
            <span style="font-size:11px;color:var(--text3)">boats (consumed)</span>
            <button class="btn btn-blue btn-sm" style="flex:1" onclick="navalAttack('${key}')">⚓ Land</button></div></div>`;
        }
        if(overseasPlanes.length>0){
          const planeOpts=overseasPlanes.map(k=>{const[al,ag]=parseKey(k);return`<option value="${k}">${(al*GRID).toFixed(1)}°,${(ag*GRID).toFixed(1)}° · ${territories[k].planes} planes</option>`}).join('');
          actHTML+=`<div class="army-section"><div class="army-section-title" style="color:#aaaaff">✈ Air ${isOwned?'Strike':'Drop'}</div>
            <select class="input-sm" id="plane-from" style="width:100%;margin-bottom:5px">${planeOpts}</select>
            <div class="move-row"><input type="number" class="input-sm" id="plane-troops" value="1" min="1" style="width:64px"/>
            <span style="font-size:11px;color:var(--text3)">planes (consumed)</span>
            <button class="btn btn-sm" style="flex:1;background:#4a4a8a;color:#fff" onclick="airAttack('${key}')">✈ ${isOwned?'Strike':'Drop'}</button></div></div>`;
        }
      } else if(!canClaim&&!isOwned){
        actHTML+=`<div class="empty-state" style="padding:16px 8px"><div class="es-icon">🌊</div>No land route.<br>Build ⚓ Boats or ✈ Planes<br>for an overseas landing.</div>`;
      } else if(isOwned&&!isMine){
        actHTML+=`<div class="empty-state" style="padding:16px 8px"><div class="es-icon">⚔</div>Expand adjacent to attack,<br>or use ⚓ Boats / ✈ Planes.</div>`;
      }
    }
  }

  const fullHTML=infoHTML+`<div class="tp-actions">${actHTML}</div>`;
  if(container){
    container.innerHTML=fullHTML;
  } else {
    document.getElementById('territory-info').innerHTML=infoHTML;
    document.getElementById('territory-actions').innerHTML=`<div class="tp-actions">${actHTML}</div>`;
  }

  // Wire build slider
  const bs=document.getElementById('build-slider');
  const bsv=document.getElementById('build-slider-val');
  const bsc=document.getElementById('build-cost');
  if(bs){
    const tc2=troop_cost(rsch);
    bs.oninput=()=>{if(bsv)bsv.textContent=bs.value;if(bsc)bsc.textContent=parseInt(bs.value)*tc2};
  }
  const boa=document.getElementById('boat-amt');
  const boc=document.getElementById('boat-build-cost');
  if(boa&&boc){boa.oninput=()=>{boc.textContent=(parseInt(boa.value)||0)*1000}}
  const pla=document.getElementById('plane-amt');
  const plc=document.getElementById('plane-build-cost');
  if(pla&&plc){pla.oninput=()=>{plc.textContent=(parseInt(pla.value)||0)*1000}}

}

function updateAtkPreview(targetKey){
  const fromSel=document.getElementById('atk-from');
  const troopInput=document.getElementById('atk-troops');
  const strDisplay=document.getElementById('atk-str-display');
  const defStr=territories[targetKey]?.garrison||0;
  if(!fromSel||!troopInput||!strDisplay) return;
  const myStr=parseInt(troopInput.value)||0;
  const odds=battleOdds(myStr,defStr);
  strDisplay.textContent=myStr;
  const oddsEl=document.querySelector('.battle-odds');
  const oddsLbl=document.querySelector('.battle-odds-label');
  if(oddsEl){oddsEl.textContent=odds.pct+'%';oddsEl.style.color=odds.color;}
  if(oddsLbl){oddsLbl.textContent=odds.label;oddsLbl.style.color=odds.color;}
}


function troop_cost(rsch){return rsch.has('gunpowder')?6:8}

// ══════════════════════════════════════════════════
//  GAME ACTIONS
// ══════════════════════════════════════════════════
function requireLogin(){
  if(!currentUser){
    toast('Log in to play!','info');
    document.getElementById('auth-overlay').style.display='flex';
    document.getElementById('game-screen').style.display='none';
    if(spectatorTimer){clearInterval(spectatorTimer);spectatorTimer=null;}
    return false;
  }
  return true;
}

async function claimTerritory(key){
  if(!requireLogin())return;
  const[gl,gg]=parseKey(key);
  if(landGeoJSON&&!isLand(gl,gg))return toast('Cannot claim water!','error');
  const r=await api('POST','/api/territory/claim',{grid_key:key});
  if(r.error){
    return toast(r.error,'error');
  }
  toast(r.message||'Claimed!','success');
  await refreshAll();selectTerritory(key);
  await fetchAndBuildPanel(key);
}
async function buildTroops(key){
  if(!requireLogin())return;
  const slider=document.getElementById('build-slider');
  const am=parseInt(slider?.value||document.getElementById('build-amt')?.value||1);
  const r=await api('POST','/api/troops/build',{grid_key:key,amount:am});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');await refreshAll();await fetchAndBuildPanel(key);
}
async function moveTroops(key){
  const am=parseInt(document.getElementById('move-amt')?.value||1);
  const to=document.getElementById('move-to')?.value;
  if(!to)return;
  const r=await api('POST','/api/troops/move',{from_key:key,to_key:to,amount:am});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');await refreshAll();await fetchAndBuildPanel(key);
}
async function buildBoats(key){
  const am=parseInt(document.getElementById('boat-amt')?.value||1);
  const r=await api('POST','/api/boats/build',{grid_key:key,amount:am});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');await refreshAll();await fetchAndBuildPanel(key);
}
async function buildPlanes(key){
  const am=parseInt(document.getElementById('plane-amt')?.value||1);
  const r=await api('POST','/api/planes/build',{grid_key:key,amount:am});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');await refreshAll();await fetchAndBuildPanel(key);
}
async function attackTerritory(targetKey){
  if(!requireLogin())return;
  const from=document.getElementById('atk-from')?.value;
  const troops=parseInt(document.getElementById('atk-troops')?.value||1);
  if(!from)return;
  const r=await api('POST','/api/attack',{from_key:from,target_key:targetKey,troops});
  if(r.error)return toast(r.error,'error');
  toast(r.message,r.attacker_wins?'success':'error');
  await refreshAll();await fetchAndBuildPanel(targetKey);loadBattleLog();
}
async function navalAttack(targetKey){
  if(!requireLogin())return;
  const from=document.getElementById('boat-from')?.value;
  const boats=parseInt(document.getElementById('boat-troops')?.value||1);
  if(!from)return;
  const r=await api('POST','/api/boats/attack',{from_key:from,target_key:targetKey,boats});
  if(r.error)return toast(r.error,'error');
  toast(r.message,r.attacker_wins?'success':'error');
  await refreshAll();await fetchAndBuildPanel(targetKey);loadBattleLog();
}
async function airAttack(targetKey){
  if(!requireLogin())return;
  const from=document.getElementById('plane-from')?.value;
  const planes=parseInt(document.getElementById('plane-troops')?.value||1);
  if(!from)return;
  const r=await api('POST','/api/planes/attack',{from_key:from,target_key:targetKey,planes});
  if(r.error)return toast(r.error,'error');
  toast(r.message,r.attacker_wins?'success':'error');
  await refreshAll();await fetchAndBuildPanel(targetKey);loadBattleLog();
}
async function fetchAndBuildPanel(key){
  const t=await api('GET',`/api/territory/${key}`);
  if(t.error)return;
  territories[key]={...territories[key],...t};
  renderTerritories();
  if(isMobile()){
    const c=document.getElementById('mobile-sheet-content');
    if(c)buildTerritoryPanel(key,t,c);
  } else {
    buildTerritoryPanel(key,t,null);
  }
}

// ══════════════════════════════════════════════════
//  REFRESH
// ══════════════════════════════════════════════════
async function refreshUser(){
  const u=await api('GET','/api/me');
  if(u.error){if(u.error.includes('banned')||u.error.includes('authenticated')){location.reload();}return;}
  currentUser=u;
  if(Array.isArray(u.alliances)) myAlliances=u.alliances;
  updateNavbar(u);
}

async function refreshTerritories(){
  const list=await api('GET','/api/territories');
  if(!Array.isArray(list))return;
  territories={};for(const t of list)territories[t.grid_key]=t;
  renderTerritories();
}
async function refreshAll(){await Promise.all([refreshUser(),refreshTerritories()]);}
function updateNavbar(u){
  document.getElementById('player-name').textContent=u.username;
  document.getElementById('player-dot').style.background=u.color;
  const rank=getRank(u.territory_count);
  document.getElementById('rank-badge').textContent=`${rank.icon} ${rank.name}`;
  const res=['food','wood','metal','oil','money'];
  document.getElementById('resource-bar').innerHTML=res.map(r=>`<div class="res-pill">${RES_CFG[r].icon}<span class="res-val">${u[r]}</span></div>`).join('');
  if(u.is_admin)document.getElementById('admin-btn').style.display='inline-block';
}

async function refreshOnline(){
  const list=await api('GET','/api/online');
  if(!Array.isArray(list))return;
  document.getElementById('online-count').textContent=list.length;
  if(onlineCollapsed){document.getElementById('online-list').style.display='none';return;}
  document.getElementById('online-list').style.display='block';
  document.getElementById('online-list').innerHTML=list.map(u=>{
    const isMe=currentUser&&u.username===currentUser.username;
    const isSpec=u.type==='spectator';
    const dot=isSpec?`<span style="font-size:11px">${u.flag||'🌐'}</span>`:`<span class="online-dot" style="background:${u.color}"></span>`;
    const name=`<span class="online-name${isMe?' me':''}" title="${isSpec?esc(u.country||''):''}">` + esc(u.username) + `</span>`;
    const badge=u.is_admin?'<span class="online-admin">MOD</span>':'';
    const tc=isSpec?'<span class="online-tc" style="font-size:9px">watching</span>':`<span class="online-tc">🗺${u.territories}</span>`;
    return `<div class="online-row">${dot}${name}${badge}${tc}</div>`;
  }).join('');
}

async function pollAnnouncements(){
  const list=await api('GET','/api/announcements');
  if(!Array.isArray(list))return;
  const maxId=list.reduce((m,a)=>Math.max(m,a.id),0);
  if(lastSeenAnnId===0){lastSeenAnnId=maxId;return;}
  for(const a of list.filter(x=>x.id>lastSeenAnnId).reverse())showAnnPopup(a);
  lastSeenAnnId=maxId;
}

// ══════════════════════════════════════════════════
//  PANELS
// ══════════════════════════════════════════════════
function showPanel(id){
  document.querySelectorAll('.panel-content').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  document.getElementById('panel-'+id)?.classList.add('active');
  document.querySelector(`.stab[data-panel="${id}"]`)?.classList.add('active');
  if(id==='leaderboard')loadLeaderboard();
  if(id==='battles')loadBattleLog();
  if(id==='market')buildMarket();
  if(id==='research')buildResearch();
  if(id==='social')buildSocialPanel();
}

async function loadLeaderboard(){
  const list=await api('GET','/api/leaderboard');
  const el=document.getElementById('leaderboard-list');
  if(!list||list.error){el.innerHTML='<div class="empty-state">Error loading</div>';return;}
  if(!list.length){el.innerHTML='<div class="empty-state"><div class="es-icon">🏆</div>No players yet</div>';return;}
  el.innerHTML=list.map((p,i)=>{
    const rc=i===0?'top1':i===1?'top2':i===2?'top3':'';
    const me=currentUser&&p.username===currentUser.username;
    const rank=p.rank||{icon:'🪓',name:'Settler'};
    return`<div class="lb-row">
      <span class="lb-rank ${rc}">#${i+1}</span>
      <span class="lb-col" style="background:${p.color}"></span>
      <span class="lb-name${me?' me':''}">${esc(p.username)}${p.is_admin?' ⭐':''}${me?' ★':''}</span>
      <span class="lb-sub">${rank.icon} ${rank.name}</span>
      <span class="lb-sub">🗺${p.territories}</span>
    </div>`;
  }).join('');
}

async function loadBattleLog(){
  let list=await api('GET','/api/battle_log');
  if(list?.error)list=await api('GET','/api/battle_log/all');
  const el=document.getElementById('battles-list');
  if(!list||!list.length){el.innerHTML='<div class="empty-state"><div class="es-icon">⚔</div>No battles yet</div>';return;}
  const modeIcon={'land':'⚔','naval':'⚓','air':'✈'};
  el.innerHTML=list.map(b=>`<div class="be ${b.result}">
    <div class="be-title">${modeIcon[b.mode]||'⚔'} ${b.result==='victory'?'Victory':'Defeat'} — ${esc(b.attacker)} vs ${esc(b.defender)}</div>
    <div class="be-detail">${esc(b.details||'')} · ${(b.created_at||'').slice(0,16)}</div>
  </div>`).join('');
}

function buildMarket(){
  const el=document.getElementById('market-content');
  const rates=`<div class="tc" style="margin-bottom:8px">
    <div class="tc-hdr"><span class="tc-icon">💹</span><div><div class="tc-title">Resource Market</div><div class="tc-sub">Sell for money</div></div></div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px">
    ${Object.entries(SELL_RATES).map(([r,v])=>`<div style="text-align:center;padding:7px 3px;background:var(--panel3);border:1px solid var(--border);border-radius:3px">
      <div style="font-size:14px">${RES_CFG[r].icon}</div>
      <div style="font-size:10px;color:var(--text3)">${r}</div>
      <div style="font-size:11px;color:var(--accent2);font-weight:600">${v}💰</div></div>`).join('')}
    </div></div>`;
  if(!currentUser){el.innerHTML=rates+'<div class="empty-state">Login to sell</div>';return;}
  const sells=['food','wood','metal','oil'].map(r=>{
    const have=currentUser[r]||0;
    return`<div class="sell-card"><div class="sell-hdr"><span>${RES_CFG[r].icon} <strong>${RES_CFG[r].label}</strong></span><span class="sell-have">${have} stored</span></div>
    <div class="input-row"><input type="number" class="input-sm" id="sell-${r}" value="${Math.max(0,Math.floor(have/2))}" min="1" max="${have}" style="max-width:80px"/>
    <span style="font-size:11px;color:var(--text3)">→ <span id="sell-earn-${r}">${Math.floor(Math.floor(have/2)*SELL_RATES[r])}</span>💰</span>
    <button class="btn btn-primary btn-sm" onclick="doSell('${r}')">Sell</button></div></div>`;
  }).join('');
  el.innerHTML=rates+sells;
  ['food','wood','metal','oil'].forEach(r=>{
    const el2=document.getElementById(`sell-${r}`);
    if(el2)el2.oninput=()=>{const e2=document.getElementById(`sell-earn-${r}`);if(e2)e2.textContent=(parseInt(el2.value)||0)*SELL_RATES[r]};
  });
}
async function doSell(r){
  const am=parseInt(document.getElementById(`sell-${r}`)?.value||0);
  if(am<1)return toast('Enter amount > 0','error');
  const res=await api('POST','/api/resources/sell',{resource:r,amount:am});
  if(res.error)return toast(res.error,'error');
  toast(res.message,'success');await refreshUser();buildMarket();
}

function buildResearch(){
  const el=document.getElementById('research-content');
  const rsch=new Set(currentUser?.research||[]);
  const branches={economy:[],military:[],naval:[]};
  for(const[id,t] of Object.entries(RESEARCH_TREE))branches[t.branch].push([id,t]);
  const bLabel={'economy':'💹 Economy','military':'⚔ Military','naval':'🚢 Naval & Air'};
  let html='';
  for(const[b,items] of Object.entries(branches)){
    html+=`<div class="branch-label">${bLabel[b]}</div>`;
    for(const[id,t] of items){
      const done=rsch.has(id);
      const reqMet=t.requires.every(r=>rsch.has(r));
      const locked=!done&&!reqMet;
      const cls=done?'done':locked?'locked':'';
      const reqText=locked?`<div class="tech-req">Requires: ${t.requires.map(r=>RESEARCH_TREE[r]?.name||r).join(', ')}</div>`:'';
      html+=`<div class="tech-card ${cls}" ${!done&&!locked?`onclick="unlockResearch('${id}')"`:''}">
        ${done?'<span class="tech-done-mark">✓</span>':''}
        <div class="tech-hdr"><span class="tech-icon">${t.icon}</span><span class="tech-name">${t.name}</span>
        ${!done?`<span class="tech-cost">${t.cost}💰</span>`:'<span class="tech-cost" style="color:var(--green2)">Done</span>'}
        </div><div class="tech-desc">${t.desc}</div>${reqText}</div>`;
    }
  }
  const money=currentUser?.money||0;
  el.innerHTML=`<div style="color:var(--accent2);font-size:12px;margin-bottom:10px;text-align:right">💰 ${money} available</div>${html}`;el.querySelectorAll('.tech-card[onclick]').forEach(node=>{node.setAttribute('role','button');node.tabIndex=0});
}
async function unlockResearch(tech){
  const r=await api('POST','/api/research/unlock',{tech});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');await refreshUser();buildResearch();
}

// ══════════════════════════════════════════════════
//  ANNOUNCEMENT POPUP
// ══════════════════════════════════════════════════
let annQueue=[];let annShowing=false;

function showAnnPopup(ann){
  annQueue.push(ann);
  if(!annShowing)showNextAnn();
}

function showNextAnn(){
  if(!annQueue.length){annShowing=false;return;}
  annShowing=true;
  const ann=annQueue.shift();
  const c=document.getElementById('ann-container');
  // Remove any existing popup
  c.querySelectorAll('.ann-popup').forEach(el=>el.remove());
  c.classList.add('has-popup');

  const div=document.createElement('div');div.className='ann-popup';
  const imgHtml=ann.image_url?`<img class="ann-img" src="${esc(safeImageUrl(ann.image_url))}" alt="" onerror="this.remove()" loading="lazy"/>`:'';
  div.innerHTML=`
    <div class="ann-header">
      <span class="ann-header-icon">📢</span>
      <span class="ann-header-title">Announcement</span>
      <span class="ann-header-author">— ${esc(ann.author)}</span>
      <button class="ann-close" onclick="closeCurrentAnn()">✕</button>
    </div>
    ${imgHtml}
    <div class="ann-body">
      <div class="ann-text-wrap">
        <div class="ann-msg">${esc(ann.message)}</div>
      </div>
    </div>
    <div class="ann-progress"><div class="ann-fill"></div></div>`;
  c.appendChild(div);

  const autoClose=setTimeout(()=>closeCurrentAnn(),10000);
  div._autoClose=autoClose;
}

function closeCurrentAnn(){
  const c=document.getElementById('ann-container');
  const popup=c.querySelector('.ann-popup');
  if(!popup)return;
  clearTimeout(popup._autoClose);
  popup.style.animation='annOut .25s ease forwards';
  setTimeout(()=>{
    popup.remove();
    c.classList.remove('has-popup');
    // Show next in queue after a short gap
    setTimeout(showNextAnn,300);
  },240);
}

function toggleOnline(){onlineCollapsed=!onlineCollapsed;document.getElementById('online-list').style.display=onlineCollapsed?'none':'block';}

// ══════════════════════════════════════════════════
//  MOBILE
// ══════════════════════════════════════════════════
function mobileNav(tab){
  document.querySelectorAll('.mnav-btn').forEach(b=>b.classList.remove('active'));
  document.querySelector(`.mnav-btn[data-mn="${tab}"]`)?.classList.add('active');
  mobileView=tab;
  if(tab==='map'){closeMobileSheet();}
  else{openMobileSheetForPanel(tab);}
}
function openMobileSheetForPanel(id){
  const c=document.getElementById('mobile-sheet-content');
  if(id==='territory'){
    if(selectedKey&&territories[selectedKey]){buildTerritoryPanel(selectedKey,territories[selectedKey],c);}
    else{c.innerHTML='<div class="empty-state"><div class="es-icon">🗺</div>Click a territory on the map</div>';}
  }else if(id==='research'){
    c.innerHTML='<div id="research-content"></div>';buildResearch();
  }else if(id==='market'){
    c.innerHTML='<div id="market-content"></div>';buildMarket();
  }else if(id==='leaderboard'){
    c.innerHTML='<div id="leaderboard-list"></div>';loadLeaderboard();
  }else if(id==='battles'){
    c.innerHTML='<div id="battles-list"></div>';loadBattleLog();
  }else if(id==='social'){
    c.innerHTML='<div id="social-content"></div>';buildSocialPanel();
  }
  document.getElementById('mobile-sheet').classList.add('open');
}
function openMobileSheet(key){
  const c=document.getElementById('mobile-sheet-content');
  const t=territories[key];
  document.getElementById('mobile-sheet').classList.add('open');
  document.querySelectorAll('.mnav-btn').forEach(b=>b.classList.remove('active'));
  document.querySelector('.mnav-btn[data-mn="territory"]')?.classList.add('active');
  if(t){buildTerritoryPanel(key,t,c);}
  else{fetchAndBuildPanel(key);}
}
function closeMobileSheet(){document.getElementById('mobile-sheet').classList.remove('open');}

// ── Swipe-to-close mobile sheet ──
(function(){
  let startY=0,startScrollTop=0,isDragging=false;
  const getSheet=()=>document.getElementById('mobile-sheet');
  const getContent=()=>document.getElementById('mobile-sheet-content');

  document.addEventListener('touchstart',e=>{
    const sheet=getSheet();
    if(!sheet||!sheet.classList.contains('open'))return;
    const handle=document.getElementById('mobile-sheet-handle');
    // Allow drag from handle OR from top of content when scrolled to top
    const fromHandle=handle&&handle.contains(e.target);
    const content=getContent();
    const atTop=content&&content.scrollTop===0;
    if(fromHandle||(atTop&&sheet.contains(e.target))){
      startY=e.touches[0].clientY;
      startScrollTop=content?content.scrollTop:0;
      isDragging=true;
      sheet.style.transition='none';
    }
  },{passive:true});

  document.addEventListener('touchmove',e=>{
    if(!isDragging)return;
    const sheet=getSheet();
    if(!sheet)return;
    const dy=e.touches[0].clientY-startY;
    if(dy>0){
      sheet.style.transform=`translateY(${dy}px)`;
    }
  },{passive:true});

  document.addEventListener('touchend',e=>{
    if(!isDragging)return;
    isDragging=false;
    const sheet=getSheet();
    if(!sheet)return;
    sheet.style.transition='';
    const dy=e.changedTouches[0].clientY-startY;
    if(dy>80){closeMobileSheet();}
    else{sheet.style.transform='';}
  },{passive:true});
})();

// ══════════════════════════════════════════════════
//  TOAST
// ══════════════════════════════════════════════════
let toastT=null;
function toast(msg,type='info'){
  const el=document.getElementById('toast');
  el.textContent=msg;el.className=`show t-${type}`;
  clearTimeout(toastT);toastT=setTimeout(()=>el.className='',3500);
}

// ══════════════════════════════════════════════════
//  AUTH
// ══════════════════════════════════════════════════
function authTab(e,tab){
  document.querySelectorAll('.auth-tab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.auth-form').forEach(f=>f.style.display='none');
  e.target.classList.add('active');
  document.getElementById(`form-${tab}`).style.display='flex';
  document.getElementById('auth-msg').textContent='';
}
async function doLogin(){
  const un=document.getElementById('li-user').value.trim();
  const pw=document.getElementById('li-pass').value;
  const r=await api('POST','/api/login',{username:un,password:pw});
  const el=document.getElementById('auth-msg');
  if(r.error){el.textContent=r.error;el.className='msg-error';return;}
  el.textContent='Logging in…';el.className='msg-success';
  startGame(r.user);
}
async function doRegister(){
  const un=document.getElementById('rg-user').value.trim();
  const pw=document.getElementById('rg-pass').value;
  const pin=document.getElementById('rg-pin').value.trim();
  const r=await api('POST','/api/register',{username:un,password:pw,reset_pin:pin||undefined});
  const el=document.getElementById('auth-msg');
  if(r.error){el.textContent=r.error;el.className='msg-error';return;}
  el.textContent=r.message||'Account created!';el.className='msg-success';
  const lr=await api('POST','/api/login',{username:un,password:pw});
  if(lr.error){el.textContent=lr.error;el.className='msg-error';return;}
  startGame(lr.user);
}
async function doForgotPassword(){
  const un=document.getElementById('fp-user').value.trim();
  const pin=document.getElementById('fp-pin').value.trim();
  const pw=document.getElementById('fp-pass').value;
  const r=await api('POST','/api/forgot_password',{username:un,reset_pin:pin,new_password:pw});
  const el=document.getElementById('auth-msg');
  if(r.error){el.textContent=r.error;el.className='msg-error';return;}
  el.textContent=r.message;el.className='msg-success';
}
function updateNavbarGuest(){
  document.getElementById('player-name').textContent='👁 Spectating';
  document.getElementById('player-dot').style.background='#607090';
  document.getElementById('rank-badge').textContent='Guest';
  document.getElementById('resource-bar').innerHTML='<span style="color:var(--text3);font-size:11px;padding:0 6px">Log in to play</span>';
}

async function doLogout(){await api('POST','/api/logout');clearInterval(refreshTimer);clearInterval(winCheckTimer);location.reload();}

// ══════════════════════════════════════════════════
//  PROFILE
// ══════════════════════════════════════════════════
function openProfile(){
  document.getElementById('profile-modal').classList.add('open');
  const ps=document.getElementById('pin-status');
  if(currentUser?.has_pin)ps.textContent='(PIN set ✓)';else ps.textContent='';
}
function closeProfile(){document.getElementById('profile-modal').classList.remove('open');}
async function doChangeUsername(){
  const nu=document.getElementById('pu-new').value.trim();
  const pw=document.getElementById('pu-pass').value;
  const r=await api('POST','/api/profile/change_username',{new_username:nu,password:pw});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');await refreshUser();closeProfile();
}
async function doChangePassword(){
  const curr=document.getElementById('pp-curr').value;
  const nw=document.getElementById('pp-new').value;
  const r=await api('POST','/api/profile/change_password',{current_password:curr,new_password:nw});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');closeProfile();
}
async function doSetPin(){
  const pin=document.getElementById('ppin-pin').value.trim();
  const pw=document.getElementById('ppin-pass').value;
  const r=await api('POST','/api/profile/set_pin',{pin,password:pw});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');await refreshUser();closeProfile();
}

// ══════════════════════════════════════════════════
//  ADMIN
// ══════════════════════════════════════════════════
async function openAdmin(){
  document.getElementById('admin-modal').classList.add('open');
  loadAdminUsers();loadAdminAnns();
}
function closeAdmin(){document.getElementById('admin-modal').classList.remove('open');}
function adminTab(e,id){
  document.querySelectorAll('.atab').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.admin-panel').forEach(p=>p.classList.remove('active'));
  e.target.classList.add('active');document.getElementById('admin-'+id).classList.add('active');
  if(id==='tools')populateAdminSelects();
}
async function loadAdminUsers(){
  const list=await api('GET','/api/admin/users');
  if(!list||list.error)return;
  adminUserList=list;
  document.getElementById('admin-user-rows').innerHTML=list.map(u=>`<tr>
    <td><span style="color:${u.color}">●</span> <strong>${esc(u.username)}</strong>${u.is_admin?' <span class="badge badge-admin">Admin</span>':''}</td>
    <td>${u.online?'<span class="badge badge-online">Online</span>':''} ${u.is_banned?'<span class="badge badge-banned">Banned</span>':'<span class="badge badge-active">Active</span>'}</td>
    <td>${u.territory_count}</td><td>${Math.round(u.money||0)}💰</td>
    <td><div class="action-btns">
      ${u.username!=='admin'?`
        <button class="btn btn-ghost btn-sm" onclick="adminBan(${u.id},${!u.is_banned})">${u.is_banned?'Unban':'Ban'}</button>
        <button class="btn btn-ghost btn-sm" onclick="adminClear(${u.id})">🗺</button>
        <button class="btn btn-ghost btn-sm" onclick="adminPromote(${u.id},${!u.is_admin})">${u.is_admin?'Demote':'Promote'}</button>
      `:'<span style="color:var(--text3);font-size:10px">Protected</span>'}
    </div></td></tr>`).join('');
}
async function adminBan(uid,ban){
  const r=await api('POST','/api/admin/ban',{user_id:uid,ban});
  if(r.error)return toast(r.error,'error');
  toast(ban?'Player banned':'Player unbanned','success');loadAdminUsers();
}
async function adminClear(uid){
  if(!confirm('Remove all territories for this player?'))return;
  const r=await api('POST','/api/admin/remove_territories',{user_id:uid});
  if(r.error)return toast(r.error,'error');
  toast('Territories cleared','success');loadAdminUsers();await refreshTerritories();
}
async function adminPromote(uid,promote){
  const r=await api('POST','/api/admin/promote',{user_id:uid,promote});
  if(r.error)return toast(r.error,'error');
  toast(promote?'Promoted to admin':'Demoted','success');loadAdminUsers();
}
function populateAdminSelects(){
  const opts=adminUserList.filter(u=>u.username!=='admin').map(u=>`<option value="${u.id}">${esc(u.username)}</option>`).join('');
  document.getElementById('tool-uid-select').innerHTML=opts;
  document.getElementById('tool-uid-pw-select').innerHTML=opts;
  document.getElementById('tool-uid-money-select').innerHTML=opts;
}
async function adminChangeUsername(){
  const uid=document.getElementById('tool-uid-select').value;
  const nu=document.getElementById('tool-new-username').value.trim();
  if(!nu)return toast('Enter new username','error');
  const r=await api('POST','/api/admin/change_username',{user_id:uid,new_username:nu});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');loadAdminUsers();populateAdminSelects();
}
async function adminResetPassword(){
  const uid=document.getElementById('tool-uid-pw-select').value;
  const pw=document.getElementById('tool-new-pw').value;
  if(!pw)return toast('Enter new password','error');
  const r=await api('POST','/api/admin/reset_password',{user_id:uid,new_password:pw});
  if(r.error)return toast(r.error,'error');
  toast('Password reset!','success');
}
async function adminResetGame(){
  if(!confirm('Reset entire game? All territories and resources will be cleared.'))return;
  const r=await api('POST','/api/admin/reset_game',{});
  if(r.error)return toast(r.error,'error');
  toast('Game reset!','success');await refreshAll();
}
async function postAnnouncement(){
  const msg=document.getElementById('ann-text').value.trim();
  const img=document.getElementById('ann-img-url').value.trim();
  if(!msg)return toast('Enter a message','error');
  const r=await api('POST','/api/admin/announce',{message:msg,image_url:img||undefined});
  if(r.error)return toast(r.error,'error');
  toast('📢 Posted!','success');
  document.getElementById('ann-text').value='';
  document.getElementById('ann-img-url').value='';
  const ann={message:msg,image_url:img||null,author:currentUser.username,created_at:new Date().toISOString(),id:r.id||0};
  showAnnPopup(ann);lastSeenAnnId=Math.max(lastSeenAnnId,r.id||0);
  loadAdminAnns();
}
async function loadAdminAnns(){
  const list=await api('GET','/api/announcements');
  if(!list||list.error)return;
  document.getElementById('admin-ann-list').innerHTML=list.map(a=>`
    <div class="ann-entry" style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
      <div>
        <div>${esc(a.message)}</div>
        ${a.image_url?`<div style="font-size:10px;color:var(--text3)">📷 ${esc(a.image_url.slice(0,40))}…</div>`:''}
        <div style="font-size:10px;color:var(--text3);margin-top:3px">— ${esc(a.author)} · ${(a.created_at||'').slice(0,16)}</div>
      </div>
      <button class="btn btn-danger btn-sm" style="flex-shrink:0" onclick="delAnn(${a.id})">✕</button>
    </div>`).join('');
}
async function delAnn(id){
  const r=await api('POST','/api/admin/delete_announcement',{id});
  if(r.error)return toast(r.error,'error');
  toast('Deleted','success');loadAdminAnns();
}

// ══════════════════════════════════════════════════
//  NOTIFICATIONS
// ══════════════════════════════════════════════════
const NOTIF_ICONS = {
  gift:'💰', alliance_invite:'🤝', alliance_accepted:'🤝',
  alliance_declined:'❌', alliance_broken:'💔',
};
let notifPopupQueue=[];
let notifShowing=false;

async function pollNotifications(){
  const list=await api('GET','/api/notifications');
  if(!Array.isArray(list))return;
  for(const n of list){
    if(!seenNotifIds.has(n.id)){
      seenNotifIds.add(n.id);while(seenNotifIds.size>2048)seenNotifIds.delete(seenNotifIds.values().next().value);
      queueNotifPopup(n);
    }
  }
  // Refresh alliances if any alliance notifications arrived
  const hasAllianceNotif=list.some(n=>n.type.startsWith('alliance'));
  if(hasAllianceNotif)await refreshUser();
}

function queueNotifPopup(notif){
  notifPopupQueue.push(notif);
  if(!notifShowing)showNextNotif();
}

function showNextNotif(){
  if(!notifPopupQueue.length){notifShowing=false;return;}
  notifShowing=true;
  const n=notifPopupQueue.shift();
  const icon=NOTIF_ICONS[n.type]||'📬';
  const container=document.getElementById('notif-container');
  const div=document.createElement('div');
  div.className=`notif-popup type-${n.type}`;
  div.style.position='relative';
  let actionsHtml='';
  if(n.type==='alliance_invite'&&n.data?.alliance_id){
    actionsHtml=`<div class="notif-actions">
      <button class="btn btn-success btn-sm" onclick="respondAllianceNotif(${n.data.alliance_id},true,${n.id},this)">✓ Accept</button>
      <button class="btn btn-danger btn-sm" onclick="respondAllianceNotif(${n.data.alliance_id},false,${n.id},this)">✕ Decline</button>
    </div>`;
  }
  div.innerHTML=`
    <button class="notif-close" onclick="dismissNotifPopup(${n.id},this.parentElement)">✕</button>
    <div class="notif-msg">${icon} ${n.message}</div>
    <div class="notif-time">${n.created_at?n.created_at.slice(0,16):''}</div>
    ${actionsHtml}`;
  container.appendChild(div);
  // Auto dismiss non-invite after 7s, invite after 20s
  const delay=n.type==='alliance_invite'?20000:7000;
  div._timer=setTimeout(()=>dismissNotifPopup(n.id,div),delay);
  // Stagger next
  setTimeout(showNextNotif,500);
}

function dismissNotifPopup(nid,el){
  if(!el||!el.parentElement)return;
  clearTimeout(el._timer);
  el.style.animation='notifOut .25s ease forwards';
  setTimeout(()=>{el.remove();},240);
  api('POST','/api/notifications/dismiss',{id:nid});
}

async function respondAllianceNotif(allianceId,accept,notifId,btn){
  btn.disabled=true;btn.parentElement.querySelectorAll('button').forEach(b=>b.disabled=true);
  const r=await api('POST','/api/alliance/respond',{alliance_id:allianceId,accept});
  if(r.error){toast(r.error,'error');btn.disabled=false;return;}
  toast(r.message,accept?'success':'info');
  await refreshUser();
  renderTerritories();
  buildSocialPanel();
  // Dismiss popup
  const popup=btn.closest('.notif-popup');
  if(popup)dismissNotifPopup(notifId,popup);
}

// ══════════════════════════════════════════════════
//  GIFT MONEY
// ══════════════════════════════════════════════════
async function openGiftModal(){
  const list=await api('GET','/api/online');
  const allPlayers=await api('GET','/api/leaderboard');
  const combined=[...(Array.isArray(allPlayers)?allPlayers:[])].filter(p=>currentUser&&p.username!==currentUser.username);
  const sel=document.getElementById('gift-recipient');
  sel.innerHTML=combined.map(p=>`<option value="${esc(p.username)}">${esc(p.username)} (${p.territories} tiles)</option>`).join('');
  const hint=document.getElementById('gift-balance-hint');
  if(hint)hint.textContent=`— You have ${currentUser?.money||0}💰`;
  document.getElementById('gift-modal').classList.add('open');
}
function closeGiftModal(){document.getElementById('gift-modal').classList.remove('open');}
async function doGiftMoney(){
  const to=document.getElementById('gift-recipient').value;
  const amount=parseInt(document.getElementById('gift-amount').value||0);
  if(!to||amount<1)return toast('Pick a player and enter an amount','error');
  const r=await api('POST','/api/gift/send',{to_username:to,amount});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');
  closeGiftModal();
  await refreshUser();
  buildSocialPanel();
}

// ══════════════════════════════════════════════════
//  ALLIANCE FUNCTIONS
// ══════════════════════════════════════════════════
async function sendAllianceInviteFromPanel(username){
  const r=await api('POST','/api/alliance/invite',{username});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');
  await refreshUser();
  if(selectedKey)fetchAndBuildPanel(selectedKey);
}

async function respondAlliance(allianceId,accept){
  const r=await api('POST','/api/alliance/respond',{alliance_id:allianceId,accept});
  if(r.error)return toast(r.error,'error');
  toast(r.message,accept?'success':'info');
  await refreshUser();
  renderTerritories();
  buildSocialPanel();
  if(selectedKey)fetchAndBuildPanel(selectedKey);
}

async function cancelAllianceInvite(allianceId){
  const r=await api('POST','/api/alliance/cancel',{alliance_id:allianceId});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'info');
  await refreshUser();
  buildSocialPanel();
}

async function breakAllianceByAllyId(allyId){
  const entry=myAlliances.find(a=>a.ally_id===allyId&&a.status==='active');
  if(!entry)return toast('Alliance not found','error');
  if(!confirm(`Break alliance with ${entry.ally_name}? This cannot be undone.`))return;
  const r=await api('POST','/api/alliance/break',{alliance_id:entry.id});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'info');
  await refreshUser();
  renderTerritories();
  buildSocialPanel();
  if(selectedKey)fetchAndBuildPanel(selectedKey);
}

async function breakAllianceById(allianceId,allyName){
  if(!confirm(`Break alliance with ${allyName}? This cannot be undone.`))return;
  const r=await api('POST','/api/alliance/break',{alliance_id:allianceId});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'info');
  await refreshUser();
  renderTerritories();
  buildSocialPanel();
  if(selectedKey)fetchAndBuildPanel(selectedKey);
}

async function allyMoveTroops(toKey){
  const from=document.getElementById('ally-move-from')?.value;
  const am=parseInt(document.getElementById('ally-move-amt')?.value||1);
  if(!from)return;
  const r=await api('POST','/api/troops/move',{from_key:from,to_key:toKey,amount:am});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');await refreshAll();await fetchAndBuildPanel(toKey);
}

// ══════════════════════════════════════════════════
//  SOCIAL PANEL
// ══════════════════════════════════════════════════
async function buildSocialPanel(){
  const el=document.getElementById('social-content');
  if(!el)return;
  if(!currentUser){el.innerHTML='<div class="empty-state">Login to use social features</div>';return;}
  el.innerHTML='<div style="color:var(--text3);font-size:11px;padding:8px 0">Loading…</div>';

  const allies=myAlliances;
  const activeAllies=allies.filter(a=>a.status==='active');
  const pendingReceived=allies.filter(a=>a.status==='pending'&&!a.is_requester);
  const pendingSent=allies.filter(a=>a.status==='pending'&&a.is_requester);

  let html='';

  // ── Gift Money ──
  html+=`<div class="social-section">
    <div class="social-section-title">💸 Gift Money</div>
    <div style="font-size:12px;color:var(--text2);margin-bottom:8px">Your balance: <strong style="color:var(--accent2)">${currentUser.money}💰</strong></div>
    <button class="btn btn-primary btn-full" onclick="openGiftModal()">💸 Send Gift to Player</button>
  </div>`;

  // ── Pending Received ──
  if(pendingReceived.length){
    html+=`<div class="social-section">
      <div class="social-section-title">📬 Alliance Requests</div>`;
    for(const a of pendingReceived){
      html+=`<div class="ally-row">
        <span class="ally-dot" style="background:${a.ally_color||'#888'}"></span>
        <span class="ally-name">${a.ally_name}</span>
        <div class="ally-actions">
          <button class="btn btn-success btn-sm" onclick="respondAlliance(${a.id},true)">✓ Accept</button>
          <button class="btn btn-danger btn-sm" onclick="respondAlliance(${a.id},false)">✕ Decline</button>
        </div>
      </div>`;
    }
    html+=`</div>`;
  }

  // ── Active Alliances ──
  html+=`<div class="social-section">
    <div class="social-section-title">🤝 Active Alliances <span style="color:var(--text3)">(${activeAllies.length})</span></div>`;
  if(activeAllies.length){
    for(const a of activeAllies){
      html+=`<div class="ally-row">
        <span class="ally-dot" style="background:${a.ally_color||'#888'}"></span>
        <span class="ally-name">${a.ally_name}</span>
        <span class="ally-status-badge ally-active">Allied</span>
        <div class="ally-actions">
          <button class="btn btn-ghost btn-sm" onclick="breakAllianceById(${a.id},'${a.ally_name}')">Break</button>
        </div>
      </div>`;
    }
  } else {
    html+=`<div style="font-size:12px;color:var(--text3);padding:4px 0">No active alliances.</div>`;
  }

  // ── Invite new alliance ──
  const allPlayers=await api('GET','/api/leaderboard');
  const inviteable=(Array.isArray(allPlayers)?allPlayers:[])
    .filter(p=>p.username!==currentUser.username&&!allies.find(a=>a.ally_name===p.username));
  if(inviteable.length){
    html+=`<div style="margin-top:9px">
      <div class="section-label" style="margin-bottom:5px">Propose New Alliance</div>
      <div class="input-row">
        <select class="input-sm" id="alliance-invite-select">${inviteable.map(p=>`<option value="${esc(p.username)}">${esc(p.username)} (${p.territories} tiles)</option>`).join('')}</select>
        <button class="btn btn-primary btn-sm" onclick="sendAllianceInviteFromSelect()">🤝 Invite</button>
      </div>
    </div>`;
  }
  html+=`</div>`;

  // ── Pending Sent ──
  if(pendingSent.length){
    html+=`<div class="social-section">
      <div class="social-section-title">⏳ Pending Invites Sent</div>`;
    for(const a of pendingSent){
      html+=`<div class="ally-row">
        <span class="ally-dot" style="background:${a.ally_color||'#888'}"></span>
        <span class="ally-name">${a.ally_name}</span>
        <span class="ally-status-badge ally-pending">Waiting…</span>
        <div class="ally-actions">
          <button class="btn btn-ghost btn-sm" onclick="cancelAllianceInvite(${a.id})">Cancel</button>
        </div>
      </div>`;
    }
    html+=`</div>`;
  }

  el.innerHTML=html;
}

async function sendAllianceInviteFromSelect(){
  const sel=document.getElementById('alliance-invite-select');
  if(!sel||!sel.value)return;
  await sendAllianceInviteFromPanel(sel.value);
}

// ══════════════════════════════════════════════════
//  ADMIN GIVE MONEY
// ══════════════════════════════════════════════════
async function adminGiveMoney(){
  const uid=document.getElementById('tool-uid-money-select').value;
  const amount=parseInt(document.getElementById('tool-give-amount').value||0);
  if(amount<1)return toast('Enter a valid amount','error');
  const r=await api('POST','/api/admin/give_money',{user_id:uid,amount});
  if(r.error)return toast(r.error,'error');
  toast(r.message,'success');
  document.getElementById('tool-give-amount').value='';
  loadAdminUsers();
}

// ══════════════════════════════════════════════════
//  KEYBINDS
// ══════════════════════════════════════════════════
document.addEventListener('keydown',async(e)=>{
  if(e.target.matches('input,textarea,select,[contenteditable=true]')||document.querySelector('.modal-overlay.open,#v6-dialog,#tut.open'))return;
  if(!currentUser||!selectedKey)return;
  const t=territories[selectedKey];
  if(e.key.toLowerCase()==='c'){
    if(!t||!t.owner_id){await claimTerritory(selectedKey);}
  }else if(e.key.toLowerCase()==='b'){
    if(t&&t.owner_id===currentUser.id){
      const bs=document.getElementById('build-slider');
      if(bs){await buildTroops(selectedKey);}
    }
  }else if(e.key==='Escape'){
    selectedKey=null;renderTerritories();
    document.getElementById('territory-info').innerHTML='<div class="empty-state"><div class="es-icon">🗺</div>Click a territory</div>';
    document.getElementById('territory-actions').innerHTML='';
    closeMobileSheet();
  }
});

// ══════════════════════════════════════════════════
//  GAME START
// ══════════════════════════════════════════════════
async function startSpectatorMode(){
  currentUser=null;
  document.getElementById('auth-overlay').style.display='none';
  document.getElementById('game-screen').style.display='flex';
  await new Promise(r=>setTimeout(r,60));
  initMap();map.invalidateSize();
  await refreshTerritories();
  await refreshOnline();
  // Register spectator presence every 60s
  api('POST','/api/spectate',{});
  spectatorTimer=setInterval(()=>{
    refreshTerritories();refreshOnline();
    api('POST','/api/spectate',{});
    pollAnnouncements();
  },15000);
  updateNavbarGuest();
}

async function startGame(user){
  currentUser=user;
  document.getElementById('auth-overlay').style.display='none';
  document.getElementById('game-screen').style.display='flex';
  await new Promise(r=>setTimeout(r,60));
  initMap();map.invalidateSize();
  await Promise.all([refreshTerritories(),refreshUser()]);
  loadLandGeoJSON().catch(()=>{});
  await refreshOnline();
  const anns=await api('GET','/api/announcements');
  if(Array.isArray(anns)&&anns.length)lastSeenAnnId=Math.max(...anns.map(a=>a.id));
  refreshTimer=setInterval(async()=>{
    await refreshAll();
    refreshOnline();pollAnnouncements();
    if(selectedKey&&territories[selectedKey]){
      if(isMobile()){const c=document.getElementById('mobile-sheet-content');if(c&&document.getElementById('mobile-sheet').classList.contains('open'))buildTerritoryPanel(selectedKey,territories[selectedKey],c);}
      else{buildTerritoryPanel(selectedKey,territories[selectedKey],null);}
    }
    const active=document.querySelector('.stab.active')?.dataset?.panel;
    if(active==='leaderboard')loadLeaderboard();
    if(active==='battles')loadBattleLog();
    if(active==='market')buildMarket();
    if(active==='research')buildResearch();
    if(active==='social')buildSocialPanel();
    pollNotifications();
  },12000);
  // Win condition: only checked server-side when all land is claimed
}


/* ═══ v4 CLIENT ═══════════════════════════════════════════════════════ */
Object.assign(RESEARCH_TREE,{
  tactics:{name:'Tactics',icon:'🧠',cost:180,branch:'military',requires:['iron'],desc:'Morale never drops below 30; +5% attack'},
  medicine:{name:'Field Medicine',icon:'⚕',cost:200,branch:'military',requires:['castle'],desc:'-25% casualties'},
  logistics:{name:'Logistics',icon:'📦',cost:220,branch:'military',requires:['iron'],desc:'+25% army capacity'},
  espionage:{name:'Espionage',icon:'🕵',cost:260,branch:'military',requires:['tactics'],desc:'See exact enemy defense & modifiers'},
  engineering:{name:'Engineering',icon:'🏗',cost:200,branch:'economy',requires:['trade'],desc:'-20% building costs'},
  banking:{name:'Banking',icon:'🏦',cost:300,branch:'economy',requires:['trade'],desc:'-20% claim cost, +10% money'},
  navigation:{name:'Navigation',icon:'🧭',cost:260,branch:'naval',requires:['shipyard'],desc:'Boat range +2, boats carry +4 troops'},
  jets:{name:'Jet Engines',icon:'🛩',cost:500,branch:'naval',requires:['airforce'],desc:'Plane range +2'},
  radar:{name:'Radar',icon:'📡',cost:350,branch:'naval',requires:['airforce'],desc:'-30% damage from air strikes against you'},
});
RESEARCH_TREE.shipyard.desc='Unlocks Ports & Boats (amphibious landings)';
RESEARCH_TREE.airforce.desc='Unlocks Airports & Planes';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let BLD={};
const WX_ICON={clear:'☀️',rain:'🌧',fog:'🌫',snow:'🌨',storm:'⛈'};
const WX_FX={clear:'no effect',rain:'-7% attack',fog:'-5% land, -25% air',snow:'-12% attack',storm:'-18% land, -40% air'};
/* weather: deterministic per 10-min slot & region — computed locally, identical to the server's formula */
const WX_TABLE={polar:[['clear',30],['snow',40],['fog',15],['storm',15]],temperate:[['clear',45],['rain',25],['fog',12],['snow',10],['storm',8]],tropical:[['clear',40],['rain',30],['storm',20],['fog',10]]};
function weatherFor(slot,gl,gg){
  const lat=Math.abs(gl*GRID),band=lat>55?'polar':lat>25?'temperate':'tropical';
  const rx=Math.floor(gl/25),ry=Math.floor(gg/25);
  let h=((Math.imul(slot,73856093)^Math.imul(rx,19349663)^Math.imul(ry,83492791))>>>0);
  h=(h^(h>>>13))>>>0; h=Math.imul(h,1274126177)>>>0; h=((h^(h>>>16))>>>0)%100;
  let acc=0;for(const[n,w] of WX_TABLE[band]){acc+=w;if(h<acc)return n}return'clear';
}
const curSlot=()=>Math.floor(Date.now()/600000);
const nextWxMins=()=>Math.ceil((600-(Date.now()/1000%600))/60);

/* ── map: free OpenStreetMap tiles (no API key) ── */
function initMap(){
  canvasR=L.canvas({padding:.5});
  const wb=L.latLngBounds(L.latLng(-85,-180),L.latLng(85,180));
  map=L.map('map',{zoomControl:true,attributionControl:true,preferCanvas:true,worldCopyJump:false,maxBoundsViscosity:1.0,maxBounds:wb,minZoom:2,zoomSnap:.5,tap:true}).setView([30,15],4);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',maxZoom:12,minZoom:2,noWrap:true,bounds:wb,className:'dark-tiles',crossOrigin:true}).addTo(map);
  map.on('mousemove',onMapMove);map.on('click',onMapClick);
  map.on('moveend',()=>updateHud());
  // The active client installs one resize listener for the map and mobile sheet.
}

/* ── water / coast detection (client knows the land polygons; server caches what clients report) ── */
function waterMap(key){
  if(!landGeoJSON)return null;const[gl,gg]=parseKey(key),m={};
  for(const k of [key,...adjKeys(gl,gg)]){const[a,b]=parseKey(k);m[k]=!isLand(a,b)}return m;
}
async function reportWater(key){const w=waterMap(key);if(w&&currentUser)await api('POST','/api/water/report',{water:w})}

/* ── helpers ── */
const dist=(a,b)=>cellDist(a,b);
const myTiles=()=>Object.keys(territories).filter(k=>territories[k].owner_id===currentUser?.id);
const resIcon={money:'💰',wood:'🌲',metal:'⚙',oil:'🛢',food:'🌾'};
const fmtCost=c=>Object.entries(c).map(([k,v])=>v+resIcon[k]).join(' ');
function bldCost(type,lvl){let c={...(BLD[type]?.costs?.[lvl-1]||{})};if((currentUser?.research||[]).includes('engineering'))for(const k in c)c[k]=Math.floor(c[k]*.8);return c}
function chipsOf(list){return`<div class="chips">${(list||[]).map(([n,m])=>`<span class="chip ${m>1.001?'good':m<.999?'bad':''}">${esc(n)} ×${(+m).toFixed(2)}</span>`).join('')}</div>`}
function moraleLabel(m){return m>=75?'🔥 Fired up':m>=45?'🙂 Steady':m>=25?'😟 Shaky':'😱 Broken'}

/* ── HUD strip ── */
function updateHud(){
  const el=document.getElementById('hud-strip');if(!el)return;
  const u=currentUser;
  let center=[30,15];try{const c=map.getCenter();center=[c.lat,c.lng]}catch(e){}
  const wx=weatherFor(curSlot(),Math.floor(center[0]/GRID),Math.floor(center[1]/GRID));
  let h=`<span class="chip" title="Local weather — changes every 10 min (${WX_FX[wx]})">${WX_ICON[wx]} ${wx} <small>${nextWxMins()}m</small></span>`;
  if(u){
    const rs=u.research||[];
    h=`<span class="chip btnish" onclick="openPanel('territory')">⚔ ${u.army}<small>/${u.army_cap}</small></span>`+
      (rs.includes('shipyard')?`<span class="chip">⚓ ${u.boats}</span>`:'')+(rs.includes('airforce')?`<span class="chip">✈ ${u.planes}</span>`:'')+
      `<span class="chip ${u.morale>=60?'good':u.morale<30?'bad':''}" title="Morale boosts attacks. Wins raise it, losses drop it.">${moraleLabel(u.morale)} <small>${u.morale}</small></span>`+h;
    if(u.event){const m=Math.max(1,Math.round((u.event.until-Date.now()/1000)/60));h+=`<span class="chip gold btnish" onclick="openPanel('quests')" title="${esc(u.event.desc)}">${u.event.icon} ${esc(u.event.name)} <small>${m}m</small></span>`}
    if(u.daily_ready)h+=`<span class="chip good btnish" onclick="openPanel('quests')">🎁 Daily ready</span>`;
  }
  el.innerHTML=h;el.querySelectorAll('.btnish[onclick]').forEach(node=>{node.setAttribute('role','button');node.tabIndex=0});
}
const _un=updateNavbar;updateNavbar=function(u){_un(u);updateHud();setDot('quests',!!u.daily_ready)};
function setDot(panel,on){document.querySelector(`.stab[data-panel="${panel}"]`)?.classList.toggle('has-dot',on);if(panel==='chat'||panel==='quests')document.querySelector(`.mnav-btn[data-mn="${panel==='quests'?'more':panel}"]`)?.classList.toggle('has-dot',on)}

/* ── panel router (desktop sidebar / mobile sheet) ── */
const PANELS={
  territory:()=>{if(selectedKey&&territories[selectedKey]&&false){}},
  chat:{c:'chat-content',f:()=>buildChat()},faction:{c:'faction-content',f:()=>buildFaction()},quests:{c:'quests-content',f:()=>buildQuests()},
  research:{c:'research-content',f:()=>buildResearch()},market:{c:'market-content',f:()=>buildMarket()},
  leaderboard:{c:'leaderboard-list',f:()=>loadLeaderboard()},battles:{c:'battles-list',f:()=>loadBattleLog()},social:{c:'social-content',f:()=>buildSocialPanel()},
};
let sheetPanel=null;
function openPanel(id){
  if(!isMobile()){showPanel(id);return}
  mobileNav(id==='territory'?'territory':['chat','faction'].includes(id)?id:'more',id);
}
function showPanel(id){
  document.querySelectorAll('.panel-content').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('active'));
  document.getElementById('panel-'+id)?.classList.add('active');
  document.querySelector(`.stab[data-panel="${id}"]`)?.classList.add('active');
  if(PANELS[id]?.f)PANELS[id].f();
}
function setMnav(tab){document.querySelectorAll('.mnav-btn').forEach(b=>b.classList.toggle('active',b.dataset.mn===tab))}
function mobileNav(tab,panel){
  if(tab==='map'){closeMobileSheet();return}
  setMnav(tab);mobileView=tab;
  const c=document.getElementById('mobile-sheet-content'),sh=document.getElementById('mobile-sheet');
  sheetPanel=panel||tab;sh.classList.toggle('tall',['chat'].includes(sheetPanel));
  if(tab==='more'&&!panel){
    c.innerHTML=`<div class="more-grid">${[['quests','🎁','Quests'],['research','🔬','Research'],['market','💹','Market'],['leaderboard','🏆','Ranks'],['battles','⚔','Battles'],['social','🤝','Social']].map(([id,i,n])=>`<button onclick="mobileNav('more','${id}')"><span>${i}</span>${n}</button>`).join('')}</div>`;
  }else if(sheetPanel==='territory'){
    if(selectedKey)fetchAndBuildPanel(selectedKey);else c.innerHTML='<div class="empty-state"><div class="es-icon">🗺</div>Tap a territory on the map</div>';
  }else{
    const p=PANELS[sheetPanel];c.innerHTML=`<div id="${p.c}"></div>`;p.f();
  }
  sh.classList.add('open');document.body.classList.add('sheet-open');
}
function openMobileSheetForPanel(id){mobileNav(id==='territory'?'territory':['chat','faction'].includes(id)?id:'more',id)}
function openMobileSheet(key){setMnav('territory');sheetPanel='territory';document.getElementById('mobile-sheet').classList.remove('tall');document.getElementById('mobile-sheet').classList.add('open');document.body.classList.add('sheet-open');fetchAndBuildPanel(key)}
function closeMobileSheet(){document.getElementById('mobile-sheet').classList.remove('open');document.body.classList.remove('sheet-open');sheetPanel=null;setMnav('map')}
function onMapClick(e){
  const{lat,lng}=e.latlng,gl=Math.floor(lat/GRID),gg=Math.floor(lng/GRID),key=`${gl},${gg}`;
  selectTerritory(key);
  if(isMobile())openMobileSheet(key);else{showPanel('territory');fetchAndBuildPanel(key)}
}
async function fetchAndBuildPanel(key){
  const generation=sessionGeneration;
  await reportWater(key);
  const t=await api('GET',`/api/territory/${key}`);if(generation!==sessionGeneration||key!==selectedKey)return;
  if(t.error){const el=isMobile()?document.getElementById('mobile-sheet-content'):document.getElementById('territory-actions');if(el)el.textContent=t.error;return;}
  territories[key]={...(territories[key]||{}),...t};renderTerritories();
  window.__force=true;
  if(isMobile()){const c=document.getElementById('mobile-sheet-content');if(sheetPanel==='territory'&&c)buildTerritoryPanel(key,t,c)}
  else buildTerritoryPanel(key,t,null);
}

/* keep scouting info (coast, weather) when the periodic refresh replaces the territory list */
const _rt=refreshTerritories;
refreshTerritories=async function(){const o=selectedKey&&territories[selectedKey];const ex=o?{coastal:o.coastal,water:o.water,weather:o.weather}:null;await _rt();if(ex&&territories[selectedKey])Object.assign(territories[selectedKey],ex)};
/* ── TERRITORY PANEL ── */
function buildTerritoryPanel(key,t,container){
  if(container&&sheetPanel!=='territory')return;   // sheet is showing another panel
  const host=container||document.getElementById('territory-actions');
  const ae=document.activeElement;
  if(!window.__force&&host&&ae&&host.contains(ae)&&/INPUT|SELECT/.test(ae.tagName))return;   // don't wipe a field the player is using
  window.__force=false;
  const[gl,gg]=parseKey(key),terrain=t.terrain||getTerrainClient(gl,gg),cfg=TERRAIN_CFG[terrain]||{};
  const isOwned=!!t.owner_id,isMine=currentUser&&t.owner_id===currentUser.id;
  const u=currentUser,rs=new Set(u?.research||[]);
  const put=(info,act)=>{if(container)container.innerHTML=info+act;else{document.getElementById('territory-info').innerHTML=info;document.getElementById('territory-actions').innerHTML=act}};
  if((t.water||(landGeoJSON&&!isOwned&&!isLand(gl,gg)))){put('<div class="water-warn">🌊 Open ocean — nothing to claim here. Cross it with ⚓ boats from a Port or ✈ planes from an Airport.</div>','');return}
  const wx=t.weather||weatherFor(curSlot(),gl,gg);
  const myAdj=u?myAdjKeys(gl,gg):[];
  const tagTxt=t.tag?`<span style="color:var(--text3)">[${esc(t.tag)}]</span> `:'';
  const bInfo=t.building&&BLD[t.building]?`${BLD[t.building].icon} ${BLD[t.building].name} Lv${t.blevel}`:'';
  const info=`<div class="tp-card"><div class="tp-head"><span class="tp-icon">${cfg.icon||'?'}</span><div class="tp-head-info">
    <div class="tp-name">${cfg.label||terrain}</div>
    ${isOwned?`<div class="tp-owner"><span class="owner-dot" style="background:${t.color}"></span> ${tagTxt}<strong style="color:${t.color}">${esc(t.owner)}</strong>${isMine?' <span style="color:var(--accent2);font-size:11px">(You)</span>':''}</div>`:'<div class="tp-owner" style="color:var(--text3)">Unclaimed</div>'}
    </div><div class="tp-yield"><div>${RES_CFG[cfg.res]?.icon||''}+${cfg.rate}</div><div style="font-size:9px;color:var(--text3)">/min</div></div></div>
    <div class="tp-stats"><div class="tp-stat"><div class="tp-stat-val">${t.garrison||0}</div><div class="tp-stat-label">🛡 Defense</div></div>
    <div class="tp-stat"><div class="tp-stat-val" style="font-size:12px">${fmtPop(t.population)}</div><div class="tp-stat-label">👥 Pop</div></div>
    ${bInfo?`<div class="tp-stat"><div class="tp-stat-val" style="font-size:12px">${bInfo.split(' ')[0]}</div><div class="tp-stat-label">${bInfo.split(' ').slice(1).join(' ')}</div></div>`:''}</div>
    <div class="chips" style="padding:0 12px 10px"><span class="chip">${WX_ICON[wx]} ${wx} <small>${WX_FX[wx]}</small></span>${t.coastal?'<span class="chip">🌊 Coastal</span>':''}${terrain==='mountains'?'<span class="chip good">⛰ +35% defense</span>':terrain==='forest'?'<span class="chip good">🌲 +20% defense</span>':terrain==='city'?'<span class="chip good">🏙 +25% defense</span>':''}</div></div>`;
  let a='';
  if(!u){a='<div class="empty-state" style="padding:16px">Log in to claim land and fight.</div>';put(info,`<div class="tp-actions">${a}</div>`);return}
  if(isMine){
    // Army / recruit
    const room=Math.max(0,u.army_cap-u.army),maxR=Math.max(1,Math.min(150,room)),def=Math.min(10,maxR);
    a+=`<div class="army-section"><div class="army-section-title">⚔ National Army <span class="v4-sub">${u.army}/${u.army_cap}</span></div>
      <div class="v4-bar"><i style="width:${Math.min(100,100*u.army/u.army_cap)}%"></i></div>
      <div class="v4-sub" style="margin-bottom:6px">One army defends and attacks for your whole realm. Cap grows with land, Barracks & Logistics.</div>
      <input type="range" id="build-slider" min="1" max="${maxR}" value="${def}" ${room<1?'disabled':''}/>
      <div class="v4-row"><span class="grow"><b id="build-slider-val">${def}</b> troops · <b id="build-cost">${def*u.troop_cost}</b>💰 <span class="v4-sub">(${u.troop_cost}💰 each)</span></span>
      <button class="btn btn-primary" ${room<1?'disabled':''} onclick="buildTroops('${key}')">Recruit</button></div></div>`;
    // Building
    const cur=t.building?BLD[t.building]:null;
    if(cur){
      const nl=t.blevel+1,canUp=nl<=3,cost=canUp?bldCost(t.building,nl):null;
      a+=`<div class="army-section"><div class="army-section-title">${cur.icon} ${cur.name} <span class="v4-sub">Lv${t.blevel}/3</span></div><div class="v4-sub" style="margin-bottom:8px">${cur.desc}</div>
        <div class="v4-row">${canUp?`<button class="btn btn-primary btn-sm grow" onclick="bldAct('${key}','${t.building}')">⬆ Upgrade · ${fmtCost(cost)}</button>`:'<span class="grow v4-sub">Max level</span>'}
        <button class="btn btn-ghost btn-sm" onclick="bldDemolish('${key}')">Demolish</button></div></div>`;
    }else{
      a+=`<div class="army-section"><div class="army-section-title">🏗 Build</div><div class="bld-grid">${Object.entries(BLD).map(([id,b])=>{
        const need=b.needs&&!rs.has(b.needs)?`🔒 ${RESEARCH_TREE[b.needs]?.name}`:(b.coastal&&!t.coastal?'🔒 Coast only':'');
        return`<button class="bld-opt" ${need?'disabled':''} onclick="bldAct('${key}','${id}')"><b>${b.icon} ${b.name}</b><span>${need||fmtCost(bldCost(id,1))}</span><span style="display:block;margin-top:2px">${b.desc}</span></button>`}).join('')}</div></div>`;
    }
    // Fleet
    const ports=myTiles().filter(k=>territories[k].building==='port').length,ap=myTiles().filter(k=>territories[k].building==='airport').length;
    if(rs.has('shipyard')){
      a+=`<div class="army-section"><div class="army-section-title" style="color:#7ab8e8">⚓ Fleet <span class="v4-sub">${u.boats} boats · range ${u.boat_range}</span></div>
      ${ports?`<div class="v4-row"><input type="number" class="input-sm" id="boat-amt" value="1" min="1" max="20" style="width:70px"/><span class="grow v4-sub">${fmtCost(gameConfig.prices.boat)} each · carries ${12+(rs.has('navigation')?4:0)} troops</span><button class="btn btn-blue btn-sm" onclick="buildBoats('${key}')">Build</button></div>`:'<div class="v4-sub">Build a ⚓ Port on a coastal tile to construct and launch boats.</div>'}</div>`;
    }
    if(rs.has('airforce')){
      a+=`<div class="army-section"><div class="army-section-title" style="color:#aaaaff">✈ Air Wing <span class="v4-sub">${u.planes} planes · range ${u.plane_range}</span></div>
      ${ap?`<div class="v4-row"><input type="number" class="input-sm" id="plane-amt" value="1" min="1" max="10" style="width:70px"/><span class="grow v4-sub">${fmtCost(gameConfig.prices.plane)} each · carries 5 paratroops</span><button class="btn btn-blue btn-sm" onclick="buildPlanes('${key}')">Build</button></div>`:'<div class="v4-sub">Build an 🛫 Airport anywhere to construct and launch planes.</div>'}</div>`;
    }
  }else{
    const allyE=myAlliances.find(x=>x.ally_id===t.owner_id&&x.status==='active');
    const sameFac=u.faction&&t.tag&&u.faction.tag===t.tag;
    const canClaim=!isOwned&&(myAdj.length>0||myTiles().length===0);
    if(canClaim){
      a+=`<div class="claim-block"><button class="btn btn-primary btn-full claim-btn" onclick="claimTerritory('${key}')">🏴 Claim — ${u.claim_cost}💰 <span class="keybind-hint">C</span></button>
      <div class="claim-info">${cfg.icon} ${RES_CFG[cfg.res]?.icon||''} ${cfg.rate}/min · 👥 ${fmtPop(t.population)}</div></div>`;
    }
    if(allyE||sameFac){
      a+=`<div class="ally-territory-label">🤝 ${sameFac?'Faction mate':'Allied'} — ${esc(t.owner)}</div>`;
      if(allyE)a+=`<button class="btn btn-danger btn-full" onclick="breakAllianceByAllyId(${t.owner_id})">💔 Break Alliance</button>`;
    }else{
      // attack options: land / sea / air
      if(myAdj.length&&(isOwned||!canClaim)){
        a+=atkBlock('land',key,{from:myAdj[0],max:u.army,def:Math.max(1,Math.floor(u.army*.6)),label:'⚔ Land Assault',unit:'troops',color:'var(--red2)',btn:'⚔ Attack'});
      }
      const boatSrc=myTiles().filter(k=>territories[k].building==='port'&&dist(k,key)>1&&dist(k,key)<=u.boat_range+(territories[k].blevel-1));
      const planeSrc=myTiles().filter(k=>territories[k].building==='airport'&&dist(k,key)>1&&dist(k,key)<=u.plane_range+(territories[k].blevel-1));
      if(rs.has('shipyard')){
        if(boatSrc.length&&t.coastal&&u.boats>0)a+=atkBlock('naval',key,{from:boatSrc[0],srcs:boatSrc,max:u.boats,def:1,label:'⚓ Naval Landing',unit:'boats',color:'#7ab8e8',btn:'⚓ Land'});
        else a+=`<div class="v4-card"><h4 style="color:#7ab8e8">⚓ Naval Landing</h4><div class="v4-sub">${!t.coastal?'Target is not on a coast.':!boatSrc.length?`Needs a Port within ${u.boat_range} cells of here.`:'You have no boats — build some at a Port.'}</div></div>`;
      }
      if(rs.has('airforce')){
        if(planeSrc.length&&u.planes>0)a+=atkBlock('air',key,{from:planeSrc[0],srcs:planeSrc,max:u.planes,def:1,label:'✈ Air Strike',unit:'planes',color:'#aaaaff',btn:'✈ Strike'});
        else a+=`<div class="v4-card"><h4 style="color:#aaaaff">✈ Air Strike</h4><div class="v4-sub">${!planeSrc.length?`Needs an Airport within ${u.plane_range} cells.`:'You have no planes — build some.'}</div></div>`;
      }
      if(!myAdj.length&&!rs.has('shipyard')&&!rs.has('airforce'))a+=`<div class="empty-state" style="padding:14px 8px"><div class="es-icon">🌊</div>No land route. Research ⚓ Shipbuilding or ✈ Air Force.</div>`;
      if(isOwned){
        const pend=myAlliances.find(x=>x.ally_id===t.owner_id&&x.status==='pending');
        a+=pend?`<div class="v4-sub" style="text-align:center;margin-top:6px">⏳ Alliance invite pending</div>`:`<button class="btn btn-ghost btn-full" style="margin-top:6px" onclick="sendAllianceInviteFromPanel('${esc(t.owner)}')">🤝 Propose Alliance</button>`;
      }
    }
  }
  put(info,`<div class="tp-actions">${a}</div>`);
  const bs=document.getElementById('build-slider');
  if(bs)bs.oninput=()=>{document.getElementById('build-slider-val').textContent=bs.value;document.getElementById('build-cost').textContent=bs.value*u.troop_cost};
  document.querySelectorAll('[data-pv]').forEach(el=>{
    const kind=el.dataset.pv,sl=document.getElementById('sl-'+kind),sel=document.getElementById('src-'+kind);
    const go=()=>previewBattle(kind,key);
    if(sl)sl.oninput=()=>{document.getElementById('sv-'+kind).textContent=sl.value;clearTimeout(sl._t);sl._t=setTimeout(go,200)};
    if(sel)sel.onchange=go;go();
  });
}
function atkBlock(kind,key,o){
  const opts=o.srcs&&o.srcs.length>1?`<select class="input-sm" id="src-${kind}" style="width:100%;margin-bottom:6px">${o.srcs.map(k=>{const[a,b]=parseKey(k);return`<option value="${k}">${(a*GRID).toFixed(1)}°, ${(b*GRID).toFixed(1)}° · ${dist(k,key)} cells</option>`}).join('')}</select>`:`<input type="hidden" id="src-${kind}" value="${o.from}"/>`;
  return`<div class="v4-card" data-pv="${kind}"><h4 style="color:${o.color}">${o.label}</h4>${opts}
    <input type="range" id="sl-${kind}" min="1" max="${Math.max(1,o.max)}" value="${Math.max(1,Math.min(o.max,o.def))}"/>
    <div class="v4-row"><span class="grow"><b id="sv-${kind}">${Math.max(1,Math.min(o.max,o.def))}</b> ${o.unit} <span class="v4-sub">of ${o.max}</span></span></div>
    <div id="pv-${kind}" style="margin:8px 0"><div class="v4-sub">Scouting…</div></div>
    <button class="btn btn-danger btn-full" onclick="doAttack('${kind}','${key}')">${o.btn}</button></div>`;
}
async function previewBattle(kind,key){
  const sl=document.getElementById('sl-'+kind),src=document.getElementById('src-'+kind),el=document.getElementById('pv-'+kind);if(!sl||!el)return;
  const p=await api('POST','/api/combat/preview',{target_key:key,from_key:src?.value,amount:+sl.value,kind});
  if(p.error){el.innerHTML=`<div class="v4-sub">${esc(p.error)}</div>`;return}
  const pct=p.odds!=null?p.odds:null;
  const col=pct==null?'var(--text2)':pct>=62?'var(--green2)':pct>=42?'var(--accent2)':'var(--red2)';
  el.innerHTML=`<div class="pv-odds" style="color:${col}">${pct!=null?pct+'%':`${p.odds_est[0]}–${p.odds_est[1]}%`}</div>
    <div class="v4-bar"><i style="width:${pct??((p.odds_est[0]+p.odds_est[1])/2)}%"></i></div>
    <div class="pv-nums"><span>Your force <b>${p.attack}</b></span><span>${p.defense!=null?`Enemy <b>${p.defense}</b>`:`Enemy ≈ <b>${p.defense_est[0]}–${p.defense_est[1]}</b>`}</span></div>
    ${chipsOf(p.atk_mods)}${p.def_mods?`<div class="v4-sub" style="margin-top:6px">Defender</div>${chipsOf(p.def_mods.map(([n,m])=>[n,1/m]))}`:'<div class="v4-sub" style="margin-top:6px">🕵 Research Espionage for exact enemy numbers.</div>'}`;
}
function showBattleReport(r,title){
  const b=r.breakdown||{},win=r.attacker_wins;
  const list=(a,cls)=>(a||[]).map(([n,m])=>`<div class="mod ${m>1.001?'up':m<.999?'dn':''}"><span>${esc(n)}</span><b>×${(+m).toFixed(2)}</b></div>`).join('')||'<div class="v4-sub">—</div>';
  document.getElementById('br-box').innerHTML=`<h2 class="${win?'win':'lose'}">${win?'VICTORY':'DEFEAT'}</h2>
    <div style="text-align:center;margin:6px 0 2px;color:var(--text2)">${esc(r.message)}</div>
    <div class="br-cols"><div><h5>Your force</h5><div class="br-big">${b.attack}</div>${list(b.atk_mods)}</div><div><h5>Defense</h5><div class="br-big">${b.defense}</div>${list((b.def_mods||[]).map(([n,m])=>[n,1/m]))}</div></div>
    <div class="v4-sub" style="text-align:center;margin-bottom:10px">${WX_ICON[b.weather]||''} ${b.weather} · both sides roll ±8% luck${r.boats_back!=null?` · ${r.boats_back} boats returned`:''}${r.planes_back!=null?` · ${r.planes_back} planes returned`:''}</div>
    <button class="btn btn-primary btn-full" onclick="document.getElementById('battle-report').classList.remove('open')">Continue</button>`;
  document.getElementById('battle-report').classList.add('open');
}
function achToast(r){(r.achievements||[]).forEach((a,i)=>setTimeout(()=>toast(`🏅 ${a.name}! +${a.reward}💰`,'success'),600+i*1800))}
async function doAttack(kind,key){
  if(!requireLogin())return;
  const sl=document.getElementById('sl-'+kind),src=document.getElementById('src-'+kind)?.value;if(!sl||!src)return;
  const n=+sl.value,water=waterMap(src);let w2=waterMap(key);const water2={...(water||{}),...(w2||{})};
  const [path,body]=kind==='land'?['/api/attack',{from_key:src,target_key:key,troops:n}]:kind==='naval'?['/api/boats/attack',{from_key:src,target_key:key,boats:n,water:water2}]:['/api/planes/attack',{from_key:src,target_key:key,planes:n,water:water2}];
  const r=await api('POST',path,body);
  if(r.error)return toast(r.error,'error');
  showBattleReport(r);achToast(r);
  await refreshAll();window.__force=true;await fetchAndBuildPanel(key);loadBattleLog();
}
function attackTerritory(k){return doAttack("land",k)}
async function afterAct(r,key){if(r.error)return toast(r.error,'error');toast(r.message,'success');achToast(r);await refreshAll();window.__force=true;await fetchAndBuildPanel(key)}
async function claimTerritory(key){
  if(!requireLogin())return;const[gl,gg]=parseKey(key);
  if(landGeoJSON&&!isLand(gl,gg))return toast('Cannot claim open water!','error');
  const r=await api('POST','/api/territory/claim',{grid_key:key,water:waterMap(key)});
  if(r.error)return toast(r.error,'error');selectTerritory(key);afterAct(r,key);
}
async function buildTroops(key){if(!requireLogin())return;afterAct(await api('POST','/api/troops/build',{grid_key:key,amount:+document.getElementById('build-slider')?.value||1}),key)}
async function buildBoats(key){afterAct(await api('POST','/api/boats/build',{grid_key:key,amount:+document.getElementById('boat-amt')?.value||1}),key)}
async function buildPlanes(key){afterAct(await api('POST','/api/planes/build',{grid_key:key,amount:+document.getElementById('plane-amt')?.value||1}),key)}
async function bldAct(key,type){afterAct(await api('POST','/api/building/build',{grid_key:key,type,water:waterMap(key)}),key)}
async function bldDemolish(key){if(!confirm('Demolish this building? (no refund)'))return;afterAct(await api('POST','/api/building/demolish',{grid_key:key}),key)}

/* ── leaderboard (faction tags) ── */
async function loadLeaderboard(){
  const el=document.getElementById('leaderboard-list');if(!el)return;
  const list=await api('GET','/api/leaderboard');
  if(!list||list.error){el.innerHTML='<div class="empty-state">Error loading</div>';return}
  el.innerHTML=list.map((p,i)=>{const me=currentUser&&p.username===currentUser.username;const rank=p.rank||{icon:'🪓',name:'Settler'};
    return`<div class="lb-row"><span class="lb-rank ${i<3?'top'+(i+1):''}">#${i+1}</span><span class="lb-col" style="background:${p.color}"></span>
    <span class="lb-name${me?' me':''}">${p.tag?`<span style="color:var(--text3)">[${esc(p.tag)}]</span> `:''}${esc(p.username)}${p.is_admin?' ⭐':''}</span>
    <span class="lb-sub">${rank.icon}</span><span class="lb-sub">🗺${p.territories}</span><span class="lb-sub">🏅${p.wins||0}</span></div>`}).join('')||'<div class="empty-state">No players yet</div>';
}

/* ── CHAT ── */
let chatCh='global',chatLastId={global:0,faction:0},chatUnseen=0;
function chatVisible(){return isMobile()?sheetPanel==='chat':document.getElementById('panel-chat')?.classList.contains('active')}
function buildChat(){
  const el=document.getElementById('chat-content');if(!el)return;
  if(!currentUser){el.innerHTML='<div class="empty-state">Log in to chat</div>';return}
  el.innerHTML=`<div class="chat-tabs"><button class="btn btn-sm ${chatCh==='global'?'btn-primary':'btn-ghost'}" onclick="setChat('global')">🌍 Global</button>
    <button class="btn btn-sm ${chatCh==='faction'?'btn-primary':'btn-ghost'}" onclick="setChat('faction')">🚩 Faction${currentUser.faction?` [${esc(currentUser.faction.tag)}]`:''}</button></div>
    <div id="chat-msgs"></div><div class="chat-in"><input class="form-input" id="chat-input" maxlength="200" placeholder="Say something…" onkeydown="if(event.key==='Enter')sendChat()"/><button class="btn btn-primary" onclick="sendChat()">Send</button></div>`;
  chatLastId[chatCh]=0;chatUnseen=0;setDot('chat',false);pollChat(true);
}
function setChat(c){chatCh=c;buildChat()}
function chatLine(m){const t=new Date(m.ts*1000);const hh=String(t.getHours()).padStart(2,'0')+':'+String(t.getMinutes()).padStart(2,'0');
  return`<div class="cm"><b style="color:${m.color||'#ccc'}">${esc(m.user)}</b>${esc(m.text)}<time>${hh}</time>${currentUser?.is_admin?`<span class="del" onclick="adminDelMsg(${m.id})">✕</span>`:''}</div>`}
async function pollChat(first){
  if(!currentUser)return;
  const box=document.getElementById('chat-msgs');
  if(!box){ // background: only unread dot for global
    const r=await api('GET','/api/chat?channel=global&since='+(chatLastId.global||0));
    if(r.messages?.length){if(chatLastId.global)setDot('chat',true);chatLastId.global=r.last_id}return}
  const channel=chatCh,generation=sessionGeneration,faction=currentUser?.faction?.id;
  const r=await api('GET',`/api/chat?channel=${channel}&since=${chatLastId[channel]||0}`);
  if(generation!==sessionGeneration||channel!==chatCh||box!==document.getElementById('chat-msgs')||(channel==='faction'&&faction!==currentUser?.faction?.id))return;
  if(r.error&&chatCh==='faction'){box.innerHTML='<div class="v4-sub" style="margin:auto;text-align:center">Join or found a faction to unlock private chat 🚩</div>';return}
  if(!r.messages)return;
  const atBottom=box.scrollTop+box.clientHeight>=box.scrollHeight-40;
  if(r.messages.length){box.insertAdjacentHTML('beforeend',r.messages.map(chatLine).join(''));chatLastId[channel]=r.last_id;while(box.querySelectorAll('.cm').length>200)box.querySelector('.cm').remove();if(first||atBottom)box.scrollTop=box.scrollHeight;if(!first&&!chatVisible()&&r.messages.some(m=>m.uid!==currentUser.id))setDot('chat',true)}
  else if(first)box.innerHTML='<div class="v4-sub" style="margin:auto">No messages yet — say hi!</div>';
}
async function sendChat(){
  const inp=document.getElementById('chat-input'),m=inp?.value.trim();if(!m)return;inp.value='';
  const r=await api('POST','/api/chat/send',{channel:chatCh,message:m});
  if(r.error)return toast(r.error,'error');achToast(r);pollChat();
}
async function adminDelMsg(id){await api('POST','/api/admin/chat_delete',{id});buildChat()}

/* ── QUESTS / EVENTS / ACHIEVEMENTS ── */
async function buildQuests(){
  const el=document.getElementById('quests-content');if(!el)return;
  if(!currentUser){el.innerHTML='<div class="empty-state">Log in to play</div>';return}
  const ach=await api('GET','/api/achievements');const u=currentUser;
  let center=[30,15];try{const c=map.getCenter();center=[c.lat,c.lng]}catch(e){}
  const wx=weatherFor(curSlot(),Math.floor(center[0]/GRID),Math.floor(center[1]/GRID));
  el.innerHTML=`<div class="v4-card"><h4>🎁 Daily Reward <span class="chip">🔥 streak ${u.daily_streak||0}</span></h4>
    <button class="btn ${u.daily_ready?'btn-primary':'btn-ghost'} btn-full" ${u.daily_ready?'':'disabled'} onclick="claimDaily()">${u.daily_ready?'Claim today\'s reward':'Come back tomorrow'}</button>
    <div class="v4-sub" style="margin-top:6px">Rewards grow for 7 days in a row: money, supplies and free troops.</div></div>
    <div class="v4-card"><h4>🌍 World Event</h4>${u.event?`<div style="font-size:18px">${u.event.icon} <b>${esc(u.event.name)}</b></div><div class="v4-sub">${esc(u.event.desc)} · ${Math.max(1,Math.round((u.event.until-Date.now()/1000)/60))} min left</div>`:'<div class="v4-sub">Quiet times… a new event will start soon.</div>'}</div>
    <div class="v4-card"><h4>${WX_ICON[wx]} Local Weather <span class="v4-sub">changes in ${nextWxMins()} min</span></h4><div class="v4-sub">At the map centre: <b>${wx}</b> — ${WX_FX[wx]} for attackers. Computed on your device; no server polling.</div></div>
    <div class="v4-card"><h4>🏅 Achievements <span class="v4-sub">${Array.isArray(ach)?ach.filter(a=>a.done).length+'/'+ach.length:''}</span></h4><div class="quest-grid">${(Array.isArray(ach)?ach:[]).map(a=>`<div class="ach ${a.done?'done':''}"><b>${a.icon} ${esc(a.name)}</b>${esc(a.desc)}<div style="color:var(--gold)">+${a.reward}💰</div></div>`).join('')}</div></div>`;
}
async function claimDaily(){const r=await api('POST','/api/daily/claim');if(r.error)return toast(r.error,'error');toast(r.message,'success');achToast(r);await refreshUser();buildQuests()}

/* ── ADMIN additions ── */
function injectAdmin(){
  const tabs=document.querySelector('.admin-tabs');if(!tabs||document.getElementById('admin-world'))return;
  tabs.insertAdjacentHTML('beforeend','<button class="atab" onclick="adminTab(event,\'world\')">World</button><button class="atab" onclick="adminTab(event,\'social\')">Factions & Chat</button>');
  const box=tabs.parentElement;
  box.insertAdjacentHTML('beforeend',`<div id="admin-world" class="admin-panel"><div style="display:flex;flex-direction:column;gap:10px">
    <div class="tc"><div class="section-label">Server stats</div><div id="adm-stats" class="v4-sub" style="margin-top:6px">…</div></div>
    <div class="tc"><div class="section-label">World event</div><div class="input-row" style="margin-top:6px"><select class="input-sm" id="adm-ev"><option value="gold_rush">🪙 Gold Rush</option><option value="harvest">🌾 Harvest</option><option value="mining">⛏ Mining Boom</option><option value="conscription">📯 Conscription</option><option value="war_fever">🔥 War Fever</option><option value="cold_snap">🧊 Cold Snap</option></select><input class="input-sm" id="adm-ev-min" type="number" value="30" style="max-width:70px"/><button class="btn btn-primary btn-sm" onclick="admEvent(document.getElementById('adm-ev').value)">Start</button><button class="btn btn-ghost btn-sm" onclick="admEvent('none')">End</button></div>
      <label class="v4-sub" style="display:block;margin-top:6px"><input type="checkbox" id="adm-ev-auto" onchange="admSet('events_enabled',this.checked?'1':'0')"/> random events enabled</label></div>
    <div class="tc"><div class="section-label">Global multipliers</div><div class="input-row" style="margin-top:6px"><span class="v4-sub">Income ×</span><input class="input-sm" id="adm-inc" type="number" step=".1" style="max-width:80px"/><button class="btn btn-ghost btn-sm" onclick="admSet('income_mult',document.getElementById('adm-inc').value)">Set</button><span class="v4-sub">Troop cost ×</span><input class="input-sm" id="adm-tc" type="number" step=".1" style="max-width:80px"/><button class="btn btn-ghost btn-sm" onclick="admSet('troop_cost_mult',document.getElementById('adm-tc').value)">Set</button></div></div>
    <div class="tc"><div class="section-label">Give resource / units</div><div class="input-row" style="margin-top:6px"><select class="input-sm" id="adm-gu"></select><select class="input-sm" id="adm-gr"><option>money</option><option>food</option><option>wood</option><option>metal</option><option>oil</option><option>army</option><option>boats</option><option>planes</option></select><input class="input-sm" id="adm-ga" type="number" value="100" style="max-width:80px"/><button class="btn btn-success btn-sm" onclick="admGive()">Give</button></div></div>
    <div class="tc"><div class="section-label">Give territory</div><div class="input-row" style="margin-top:6px"><select class="input-sm" id="adm-tu"></select><input class="input-sm" id="adm-tk" placeholder="grid key e.g. 120,40"/><button class="btn btn-primary btn-sm" onclick="admTerr()">Assign</button></div></div></div></div>
    <div id="admin-social" class="admin-panel"><div class="tc"><div class="section-label">Mute player</div><div class="input-row" style="margin-top:6px"><select class="input-sm" id="adm-mu"></select><input class="input-sm" id="adm-mm" type="number" value="10" style="max-width:70px"/><span class="v4-sub">min</span><button class="btn btn-danger btn-sm" onclick="admMute()">Mute</button><button class="btn btn-ghost btn-sm" onclick="admMute(0)">Unmute</button></div>
      <button class="btn btn-danger btn-sm" style="margin-top:8px" onclick="if(confirm('Delete ALL chat messages?'))api('POST','/api/admin/chat_delete',{all:true}).then(()=>toast('Chat cleared','success'))">🗑 Clear all chat</button></div>
      <div class="tc" style="margin-top:10px"><div class="section-label">Factions</div><div id="adm-facs" style="margin-top:6px"></div></div></div>`);
}
const _at=adminTab;adminTab=function(e,id){_at(e,id);if(id==='world')loadAdmWorld();if(id==='social')loadAdmSocial()};
function admUsersOpts(){return adminUserList.filter(u=>u.username!=='admin').map(u=>`<option value="${u.id}">${esc(u.username)}</option>`).join('')}
async function loadAdmWorld(){
  const s=await api('GET','/api/admin/stats');if(s.error)return;
  document.getElementById('adm-stats').innerHTML=`👥 ${s.users} players · 🗺 ${s.territories} tiles · ⚔ ${s.battles} battles · 🏗 ${s.buildings} buildings · 🚩 ${s.factions} factions · 💬 ${s.chat_msgs} msgs · 🪖 ${s.total_army} total troops${s.event?` · event: ${s.event.icon} ${s.event.name}`:''}`;
  document.getElementById('adm-inc').value=s.settings.income_mult;document.getElementById('adm-tc').value=s.settings.troop_cost_mult;document.getElementById('adm-ev-auto').checked=s.settings.events_enabled==='1';
  ['adm-gu','adm-tu'].forEach(i=>document.getElementById(i).innerHTML=admUsersOpts());
}
async function loadAdmSocial(){
  document.getElementById('adm-mu').innerHTML=admUsersOpts();
  const f=await api('GET','/api/admin/factions');
  document.getElementById('adm-facs').innerHTML=(Array.isArray(f)&&f.length)?f.map(x=>`<div class="v4-row" style="margin-bottom:5px"><span class="grow"><b>[${esc(x.tag)}]</b> ${esc(x.name)} <span class="v4-sub">👥${x.members.length} 🗺${x.territories} 🏦${x.treasury}</span></span><button class="btn btn-danger btn-sm" onclick="admDisband(${x.id})">Disband</button></div>`).join(''):'<div class="v4-sub">None</div>';
}
async function admRun(path,body,reload){const r=await api('POST',path,body);if(r.error)return toast(r.error,'error');toast(r.message||'Done','success');reload&&reload();refreshAll()}
const admEvent=t=>admRun('/api/admin/event',{type:t,minutes:+document.getElementById('adm-ev-min').value},loadAdmWorld);
const admSet=(k,v)=>admRun('/api/admin/set_setting',{key:k,value:v},loadAdmWorld);
const admGive=()=>admRun('/api/admin/give_resource',{user_id:+document.getElementById('adm-gu').value,resource:document.getElementById('adm-gr').value,amount:+document.getElementById('adm-ga').value});
const admTerr=()=>admRun('/api/admin/give_territory',{user_id:+document.getElementById('adm-tu').value,grid_key:document.getElementById('adm-tk').value.trim()});
const admMute=(m)=>admRun('/api/admin/mute',{user_id:+document.getElementById('adm-mu').value,minutes:m===0?0:+document.getElementById('adm-mm').value});
const admDisband=id=>confirm('Disband this faction?')&&admRun('/api/admin/disband_faction',{faction_id:id},loadAdmSocial);

/* ── bootstrap ── */
const _sg=startGame;
startGame=async function(user){
  api('GET','/api/buildings').then(b=>{if(b&&!b.error)BLD=b});
  await _sg(user);
  injectAdmin();updateHud();
  if(isMobile()&&!onlineCollapsed)toggleOnline();
  setInterval(()=>{pollChat();updateHud()},5000);
  setInterval(()=>{if(!document.hidden&&document.getElementById('quests-content'))buildQuests()},60000);
};
const _ss=startSpectatorMode;
startSpectatorMode=async function(){await _ss();updateHud();setInterval(updateHud,30000)};
document.addEventListener('keydown',e=>{if(e.target.matches('input,textarea,select'))return;if(e.key==='c'&&selectedKey&&currentUser&&!territories[selectedKey]?.owner_id)claimTerritory(selectedKey)});

/* ═══ v5 ═══════════════════════════════════════════════════════════════ */
Object.assign(SELL_RATES,{steel:12,uranium:40,gems:60});
Object.assign(RES_CFG,{steel:{icon:'🔩',label:'Steel'},uranium:{icon:'☢',label:'Uranium'},gems:{icon:'💎',label:'Gems'}});
Object.assign(NOTIF_ICONS,{loan_request:'🚢',trade_request:'⚖',merge_request:'🧬',faction_ally:'🤝'});
Object.assign(resIcon,{steel:'🔩',uranium:'☢',gems:'💎'});
function fmtN(n){n=+n||0;const a=Math.abs(n);if(a>=1e9)return(n/1e9).toFixed(2)+'B';if(a>=1e6)return(n/1e6).toFixed(2)+'M';if(a>=1e4)return(n/1e3).toFixed(1)+'k';return String(Math.round(n))}
const groupTiles=()=>Object.keys(territories).filter(k=>{const t=territories[k];return t.owner_id===currentUser?.id||(currentUser?.faction&&t.tag&&t.tag===currentUser.faction.tag)});
const groupAdj=(gl,gg)=>{const s=new Set(groupTiles());return adjKeys(gl,gg).filter(k=>s.has(k))};

/* ── accurate land/water: sample the real map tiles the player is looking at ── */
const tilePx={},tileOrder=[],landMem={};
function loadTile(z,x,y){
  const k=`${z}/${x}/${y}`;if(tilePx[k])return tilePx[k];
  tileOrder.push(k);if(tileOrder.length>48)delete tilePx[tileOrder.shift()];
  return tilePx[k]=new Promise(res=>{const im=new Image();im.crossOrigin='anonymous';
    im.onload=()=>{try{const c=document.createElement('canvas');c.width=c.height=256;const g=c.getContext('2d',{willReadFrequently:true});g.drawImage(im,0,0);res(g.getImageData(0,0,256,256).data)}catch(e){res(null)}};
    im.onerror=()=>res(null);im.src=`https://tile.openstreetmap.org/${k}.png`});
}
async function sampleLand(gl,gg){
  const key=`${gl},${gg}`;if(key in landMem)return landMem[key];
  const Z=7,N=(2**Z)*256;let land=0,fail=false;
  for(let i=0;i<3&&!fail;i++)for(let j=0;j<3;j++){
    const lat=Math.max(-84.9,Math.min(84.9,(gl+(i+.5)/3)*GRID)),lng=(gg+(j+.5)/3)*GRID;
    const px=(lng+180)/360*N,s=Math.sin(lat*Math.PI/180),py=(0.5-Math.log((1+s)/(1-s))/(4*Math.PI))*N;
    const d=await loadTile(Z,Math.floor(px/256),Math.floor(py/256));if(!d){fail=true;break}
    const o=((Math.floor(py)%256)*256+(Math.floor(px)%256))*4;
    const water=Math.abs(d[o]-170)<=14&&Math.abs(d[o+1]-211)<=14&&Math.abs(d[o+2]-223)<=14;if(!water)land++;
  }
  const res=fail?(landGeoJSON?isLand(gl,gg):true):land>=3;landMem[key]=res;return res;
}
async function waterMapAsync(key){
  const[gl,gg]=parseKey(key),cells=[key,...adjKeys(gl,gg)],m={};
  await Promise.all(cells.map(async k=>{const[a,b]=parseKey(k);m[k]=!(await sampleLand(a,b))}));return m;
}
async function reportWater(key){if(currentUser){const w=await waterMapAsync(key);await api('POST','/api/water/report',{water:w})}}

/* ── hover / tap coordinates ── */
let hoverT=null;
function hoverInfo(ll){
  let el=document.getElementById('hover-info');if(!el){el=document.createElement('div');el.id='hover-info';document.getElementById('map').parentElement.appendChild(el)}
  const gl=Math.floor(ll.lat/GRID),gg=Math.floor(ll.lng/GRID),key=`${gl},${gg}`,t=territories[key];
  const kind=key in landMem?(landMem[key]?'🏝 land':'🌊 water'):'…';
  el.innerHTML=`📍 <b>${ll.lat.toFixed(3)}°, ${ll.lng.toFixed(3)}°</b> · cell ${key} · ${kind}${t?` · <span style="color:${t.color}">${esc(t.owner)}</span>${t.capital?' ⭐':''}`:''}`;
  clearTimeout(hoverT);hoverT=setTimeout(async()=>{if(!(key in landMem)){await sampleLand(gl,gg);hoverInfo(ll)}},180);
}
const _omm=onMapMove;onMapMove=function(e){_omm(e);if(!isMobile())hoverInfo(e.latlng)};
const _omc=onMapClick;onMapClick=function(e){hoverInfo(e.latlng);_omc(e)};

/* ── capital stars + fallout overlay ── */
let capLayer=null,foLayer=null;
function drawCaps(){
  if(!map)return;if(capLayer)map.removeLayer(capLayer);capLayer=L.layerGroup();
  for(const[k,t] of Object.entries(territories))if(t.capital){const[gl,gg]=parseKey(k);
    const island=typeof pacificIslands!=='undefined'&&pacificIslands[k];
    L.marker(island?[island.properties.lat,island.properties.lng]:[(gl+.5)*GRID,(gg+.5)*GRID],{icon:L.divIcon({className:'cap-star',html:'⭐',iconSize:[24,24]}),interactive:false,keyboard:false}).addTo(capLayer)}
  capLayer.addTo(map);
}
const _rtr=renderTerritories;renderTerritories=function(){_rtr();drawCaps()};
async function drawFallout(){
  const list=await api('GET','/api/fallout');if(!Array.isArray(list)||!map)return;
  if(foLayer)map.removeLayer(foLayer);foLayer=L.layerGroup();
  for(const k of list){const island=pacificIslands[k];if(island){L.geoJSON(island,{style:{renderer:canvasR,color:'#b6ff00',weight:1,fillColor:'#201f00',fillOpacity:.6},interactive:false}).addTo(foLayer);continue}const[gl,gg]=parseKey(k);L.rectangle([[gl*GRID,gg*GRID],[(gl+1)*GRID,(gg+1)*GRID]],{renderer:canvasR,color:'#b6ff00',weight:1,fillColor:'#201f00',fillOpacity:.6,interactive:false}).addTo(foLayer)}
  foLayer.addTo(map);
}

/* ── HUD ── */
function updateHud(){
  const el=document.getElementById('hud-strip');if(!el)return;const u=currentUser;
  let c=[30,15];try{const m=map.getCenter();c=[m.lat,m.lng]}catch(e){}
  const wx=weatherFor(curSlot(),Math.floor(c[0]/GRID),Math.floor(c[1]/GRID));
  let h=`<span class="chip" title="Local weather — changes every 10 min (${WX_FX[wx]})">${WX_ICON[wx]} ${wx} <small>${nextWxMins()}m</small></span>`;
  if(u){const rs=u.research||[];
    h=`<span class="chip btnish" onclick="openPanel('territory')" title="${u.faction?'Shared faction army':'Your army — no cap!'}">⚔ ${fmtN(u.army)}${u.faction?' <small>shared</small>':''}</span>`+
      (rs.includes('shipyard')?`<span class="chip">⚓ ${fmtN(u.boats)}</span>`:'')+(rs.includes('airforce')?`<span class="chip">✈ ${fmtN(u.planes)}</span>`:'')+(u.nukes?`<span class="chip bad">☢ ${u.nukes}</span>`:'')+
      `<span class="chip ${u.morale>=60?'good':u.morale<30?'bad':''}">${moraleLabel(u.morale)} <small>${u.morale}</small></span><span class="chip" title="Your total population">👥 ${fmtPop(u.population)}</span>`+h;
    if(u.event){const m=Math.max(1,Math.round((u.event.until-Date.now()/1000)/60));h+=`<span class="chip gold btnish" onclick="openPanel('quests')" title="${esc(u.event.desc)}">${u.event.icon} ${esc(u.event.name)} <small>${m}m</small></span>`}
    if(u.daily_ready)h+=`<span class="chip good btnish" onclick="openPanel('quests')">🎁 Daily</span>`;}
  h+=`<span class="chip btnish" onclick="showTutorial(0)">❓ Help</span>`;el.innerHTML=h;
}
const _un2=updateNavbar;updateNavbar=function(u){_un2(u);
  const base=['food','wood','metal','oil','money'],extra=['steel','uranium','gems'].filter(r=>u[r]>0);
  document.getElementById('resource-bar').innerHTML=[...base,...extra].map(r=>`<div class="res-pill">${RES_CFG[r].icon}<span class="res-val">${fmtN(u[r])}</span></div>`).join('');
  if(u.color)document.getElementById('player-dot').style.background=u.color;
};

/* ── panel router additions ── */
PANELS.empire={c:'empire-content',f:()=>buildEmpire()};
function mobileNav(tab,panel){
  if(tab==='map'){closeMobileSheet();return}
  setMnav(tab);mobileView=tab;
  const c=document.getElementById('mobile-sheet-content'),sh=document.getElementById('mobile-sheet');
  sheetPanel=panel||tab;sh.classList.toggle('tall',['chat'].includes(sheetPanel));
  if(tab==='more'&&!panel){
    c.innerHTML=`<div class="more-grid">${[['quests','🎁','Quests'],['empire','👑','Empire'],['research','🔬','Research'],['market','💹','Market'],['leaderboard','🏆','Ranks'],['battles','⚔','Battles'],['social','🤝','Social']].map(([id,i,n])=>`<button onclick="mobileNav('more','${id}')"><span>${i}</span>${n}</button>`).join('')}</div>`;
  }else if(sheetPanel==='territory'){
    if(selectedKey)fetchAndBuildPanel(selectedKey);else c.innerHTML='<div class="empty-state"><div class="es-icon">🗺</div>Tap a territory on the map</div>';
  }else{const p=PANELS[sheetPanel];c.innerHTML=`<div id="${p.c}"></div>`;p.f()}
  sh.classList.add('open');document.body.classList.add('sheet-open');
}

/* ── TERRITORY PANEL (v5) ── */
function buildTerritoryPanel(key,t,container){
  if(container&&sheetPanel!=='territory')return;
  const host=container||document.getElementById('territory-actions'),ae=document.activeElement;
  if(!window.__force&&host&&ae&&host.contains(ae)&&/INPUT|SELECT/.test(ae.tagName))return;
  window.__force=false;
  const[gl,gg]=parseKey(key),terrain=t.terrain||getTerrainClient(gl,gg),cfg=TERRAIN_CFG[terrain]||{};
  const isOwned=!!t.owner_id,u=currentUser,isMine=u&&t.owner_id===u.id,rs=new Set(u?.research||[]);
  const put=(i,a)=>{if(container)container.innerHTML=i+a;else{document.getElementById('territory-info').innerHTML=i;document.getElementById('territory-actions').innerHTML=a}};
  if(t.water){put('<div class="water-warn">🌊 Open water — nothing to claim. Cross it with ⚓ boats from a Port (they can sail any distance, but every cell costs resources) or ✈ planes from an Airport.</div>','');return}
  if(t.fallout){put('<div class="water-warn">�role Irradiated land — uninhabitable.</div>'.replace('�role','☢'),'');return}
  const wx=t.weather||weatherFor(curSlot(),gl,gg),adj=u?groupAdj(gl,gg):[];
  const tag=t.tag?`<span style="color:var(--text3)">[${esc(t.tag)}]</span> `:'',bInfo=t.building&&BLD[t.building]?BLD[t.building]:null;
  const info=`<div class="tp-card"><div class="tp-head"><span class="tp-icon">${cfg.icon||'?'}</span><div class="tp-head-info"><div class="tp-name">${t.capital?'⭐ ':''}${cfg.label||terrain}${t.capital?' <span class="v4-sub">Capital</span>':''}</div>
    ${isOwned?`<div class="tp-owner"><span class="owner-dot" style="background:${t.color}"></span> ${tag}<strong style="color:${t.color}">${esc(t.owner)}</strong>${isMine?' <span style="color:var(--accent2);font-size:11px">(You)</span>':''}</div>`:'<div class="tp-owner" style="color:var(--text3)">Unclaimed</div>'}</div>
    <div class="tp-yield"><div>${RES_CFG[cfg.res]?.icon||''}+${cfg.rate}</div><div style="font-size:9px;color:var(--text3)">/min</div></div></div>
    <div class="tp-stats"><div class="tp-stat"><div class="tp-stat-val">${fmtN(t.garrison||0)}</div><div class="tp-stat-label">🛡 Defense</div></div><div class="tp-stat"><div class="tp-stat-val" style="font-size:12px">${fmtPop(t.population)}</div><div class="tp-stat-label">👥 Pop</div></div>
    ${bInfo?`<div class="tp-stat"><div class="tp-stat-val" style="font-size:13px">${bInfo.icon}</div><div class="tp-stat-label">${bInfo.name} L${t.blevel}</div></div>`:''}</div>
    <div class="chips" style="padding:0 12px 10px"><span class="chip">${WX_ICON[wx]} ${wx} <small>${WX_FX[wx]}</small></span>${t.coastal?'<span class="chip">🌊 Coastal</span>':''}<span class="chip">📍 ${(gl*GRID).toFixed(2)}°, ${(gg*GRID).toFixed(2)}°</span>${terrain==='mountains'?'<span class="chip good">⛰ +35% def</span>':terrain==='forest'?'<span class="chip good">🌲 +20% def</span>':terrain==='city'?'<span class="chip good">🏙 +25% def</span>':''}</div></div>`;
  if(!u){put(info,'<div class="tp-actions"><div class="empty-state" style="padding:16px">Log in to claim land and fight.</div></div>');return}
  let a='';
  if(isMine){
    const def=Math.min(10,Math.max(1,Math.floor(u.money/u.troop_cost)));
    a+=`<div class="army-section"><div class="army-section-title">⚔ ${u.faction?'Faction':'National'} Army <span class="v4-sub">${fmtN(u.army)} · no cap</span></div>
      <div class="v4-sub" style="margin-bottom:8px">${u.faction?`Shared with all [${esc(u.faction.tag)}] members — they defend and attack for each other.`:'One army defends and attacks for your whole realm.'} Barracks add free troops.</div>
      <div class="v4-row"><input type="number" id="build-n" class="input-sm" min="1" value="${def}" style="width:96px"/>${[10,100,1000].map(n=>`<button class="btn btn-ghost btn-sm" onclick="setBuildN(${n})">${n}</button>`).join('')}<button class="btn btn-ghost btn-sm" onclick="setBuildN(Math.floor(currentUser.money/currentUser.troop_cost))">Max</button></div>
      <div class="v4-row" style="margin-top:8px"><span class="grow"><b id="build-cost">${def*u.troop_cost}</b>💰 <span class="v4-sub">(${u.troop_cost}💰 each)</span></span><button class="btn btn-primary" onclick="buildTroops('${key}')">Recruit</button></div></div>`;
    a+=`<div class="v4-row" style="margin-bottom:10px">${t.capital?'<span class="chip gold grow" style="justify-content:center">⭐ This is your capital</span>':`<button class="btn btn-ghost btn-sm grow" onclick="setCapital('${key}')">⭐ Make capital</button>`}<button class="btn btn-ghost btn-sm grow" onclick="sellTile('${key}',${Math.floor((t.invested||0)*.5)})">💰 Sell tile (+${fmtN((t.invested||0)*.5)})</button></div>`;
    const cur=t.building?BLD[t.building]:null;
    if(cur){const nl=t.blevel+1,cost=nl<=3?bldCost(t.building,nl):null;
      a+=`<div class="army-section"><div class="army-section-title">${cur.icon} ${cur.name} <span class="v4-sub">Lv${t.blevel}/3</span></div><div class="v4-sub" style="margin-bottom:8px">${cur.desc}</div><div class="v4-row">${cost?`<button class="btn btn-primary btn-sm grow" onclick="bldAct('${key}','${t.building}')">⬆ Upgrade · ${fmtCost(cost)}</button>`:'<span class="grow v4-sub">Max level</span>'}<button class="btn btn-ghost btn-sm" onclick="bldDemolish('${key}')">Demolish</button></div></div>`}
    else a+=`<div class="army-section"><div class="army-section-title">🏗 Build</div><div class="bld-grid">${Object.entries(BLD).map(([id,b])=>{
      const need=b.needs&&!rs.has(b.needs)?`🔒 ${RESEARCH_TREE[b.needs]?.name||b.needs}`:(b.coastal&&!t.coastal?'🔒 Coast only':(b.terrain&&!b.terrain.includes(terrain)?`🔒 ${b.terrain.join('/')} only`:''));
      return`<button class="bld-opt" ${need?'disabled':''} onclick="bldAct('${key}','${id}')"><b>${b.icon} ${b.name}</b><span>${need||fmtCost(bldCost(id,1))}</span><span style="display:block;margin-top:2px">${b.desc}</span></button>`}).join('')}</div></div>`;
    const gt=groupTiles(),ports=gt.filter(k=>territories[k].building==='port').length,ap=gt.filter(k=>territories[k].building==='airport').length;
    if(rs.has('shipyard'))a+=`<div class="army-section"><div class="army-section-title" style="color:#7ab8e8">⚓ Fleet <span class="v4-sub">${fmtN(u.boats)} boats · unlimited range</span></div>${ports?`<div class="v4-row"><input type="number" class="input-sm" id="boat-amt" value="1" min="1" style="width:80px"/><span class="grow v4-sub">${fmtCost(gameConfig.prices.boat)} each · carries ${12+(rs.has('navigation')?4:0)} troops. Voyages cost ${gameConfig.prices.voyage_money}💰 ${gameConfig.prices.voyage_wood}🌲 per boat per cell.</span><button class="btn btn-blue btn-sm" onclick="buildBoats('${key}')">Build</button></div>`:'<div class="v4-sub">Build a ⚓ Port on the coast to build and launch boats.</div>'}</div>`;
    if(rs.has('airforce'))a+=`<div class="army-section"><div class="army-section-title" style="color:#aaaaff">✈ Air Wing <span class="v4-sub">${fmtN(u.planes)} planes · range ${u.plane_range}</span></div>${ap?`<div class="v4-row"><input type="number" class="input-sm" id="plane-amt" value="1" min="1" style="width:80px"/><span class="grow v4-sub">${fmtCost(gameConfig.prices.plane)} · carries 5 paratroops</span><button class="btn btn-blue btn-sm" onclick="buildPlanes('${key}')">Build</button></div>`:'<div class="v4-sub">Build an 🛫 Airport to build and launch planes.</div>'}</div>`;
  }else{
    const sameFac=u.faction&&t.tag&&u.faction.tag===t.tag,allyE=myAlliances.find(x=>x.ally_id===t.owner_id&&x.status==='active');
    const claim=t.claim||{money:u.claim_cost},canClaim=!isOwned&&(adj.length>0||myTiles().length===0);
    if(canClaim)a+=`<div class="claim-block"><button class="btn btn-primary btn-full claim-btn" onclick="claimTerritory('${key}')">🏴 Claim — ${fmtCost(claim)} <span class="keybind-hint">C</span></button><div class="claim-info">${cfg.icon} ${RES_CFG[cfg.res]?.icon||''} ${cfg.rate}/min · 👥 ${fmtPop(t.population)} · price scales with your income</div></div>`;
    if(sameFac||allyE)a+=`<div class="ally-territory-label">🤝 ${sameFac?'Faction mate':'Allied'} — ${esc(t.owner)}</div>`;
    else{
      const gt=groupTiles();let firstAtk=true;
      if(adj.length&&(isOwned||!canClaim)){a+=atkBlock('land',key,{from:adj[0],max:u.army,def:Math.max(1,Math.floor(u.army*.6)),label:'⚔ Land Assault',unit:'troops',color:'var(--red2)',btn:'⚔ Attack',hk:firstAtk});firstAtk=false}
      const boatSrc=gt.filter(k=>territories[k].building==='port'&&dist(k,key)>1),planeSrc=gt.filter(k=>territories[k].building==='airport'&&dist(k,key)>1&&dist(k,key)<=u.plane_range+(territories[k].blevel-1));
      if(rs.has('shipyard')){
        if(boatSrc.length&&t.coastal&&u.boats>0){a+=atkBlock('naval',key,{from:boatSrc.sort((x,y)=>dist(x,key)-dist(y,key))[0],srcs:boatSrc,max:u.boats,def:1,label:'⚓ Naval Landing',unit:'boats',color:'#7ab8e8',btn:'⚓ Land',hk:firstAtk});firstAtk=false}
        else a+=`<div class="v4-card"><h4 style="color:#7ab8e8">⚓ Naval Landing</h4><div class="v4-sub">${!t.coastal?'Target is not on a coast (no port needed there, but it must touch water).':!boatSrc.length?'You (or a faction mate) need a coastal Port.':'You have no boats — build some at a Port.'}</div></div>`}
      if(rs.has('airforce')){
        if(planeSrc.length&&u.planes>0){a+=atkBlock('air',key,{from:planeSrc[0],srcs:planeSrc,max:u.planes,def:1,label:'✈ Air Strike',unit:'planes',color:'#aaaaff',btn:'✈ Strike',hk:firstAtk});firstAtk=false}
        else a+=`<div class="v4-card"><h4 style="color:#aaaaff">✈ Air Strike</h4><div class="v4-sub">${!planeSrc.length?`Needs an Airport within ${u.plane_range} cells.`:'You have no planes — build some.'}</div></div>`}
      const silos=gt.filter(k=>territories[k].building==='silo'&&dist(k,key)<=40);
      if(u.nukes>0&&silos.length)a+=`<div class="v4-card" style="border-color:var(--red2)"><h4 style="color:var(--red2)">☢ Nuclear Strike</h4><div class="v4-sub" style="margin-bottom:8px">Random blast radius 3–10 cells. Erases ownership of EVERYONE inside it (even you), leaves fallout for 6h, and cripples every country hit.</div><button class="btn btn-danger btn-full" onclick="launchNuke('${silos[0]}','${key}')">☢ LAUNCH (${u.nukes} warhead${u.nukes>1?'s':''})</button></div>`;
      if(!adj.length&&!rs.has('shipyard')&&!rs.has('airforce'))a+=`<div class="empty-state" style="padding:14px 8px"><div class="es-icon">🌊</div>No land route. Research ⚓ Shipbuilding or ✈ Air Force.</div>`;
      if(isOwned&&u.faction?.is_leader)a+=`<div class="v4-card"><h4>🏛 Diplomacy</h4><div class="v4-sub">Factions replace alliances: declare war or propose a faction alliance from the Faction tab.</div></div>`;
    }
  }
  put(info,`<div class="tp-actions">${a}</div>`);
  const bn=document.getElementById('build-n');if(bn)bn.oninput=()=>{document.getElementById('build-cost').textContent=(Math.max(1,+bn.value||1))*u.troop_cost};
  document.querySelectorAll('[data-pv]').forEach(el=>{const kind=el.dataset.pv,sl=document.getElementById('sl-'+kind),sel=document.getElementById('src-'+kind),go=()=>previewBattle(kind,key);
    if(sl)sl.oninput=()=>{document.getElementById('sv-'+kind).textContent=sl.value;clearTimeout(sl._t);sl._t=setTimeout(go,200)};if(sel)sel.onchange=go;go()});
}
const setBuildN=n=>{const e=document.getElementById('build-n');if(e){e.value=Math.max(1,n);e.oninput&&e.oninput()}};
function atkBlock(kind,key,o){
  const opts=o.srcs&&o.srcs.length>1?`<select class="input-sm" id="src-${kind}" style="width:100%;margin-bottom:6px">${o.srcs.map(k=>{const[a,b]=parseKey(k);return`<option value="${k}">${(a*GRID).toFixed(1)}°, ${(b*GRID).toFixed(1)}° · ${dist(k,key)} cells${territories[k]?.owner_id!==currentUser.id?' · '+esc(territories[k].owner):''}</option>`}).join('')}</select>`:`<input type="hidden" id="src-${kind}" value="${o.from}"/>`;
  const d0=Math.max(1,Math.min(o.max,o.def));
  return`<div class="v4-card" data-pv="${kind}"><h4 style="color:${o.color}">${o.label}</h4>${opts}<input type="range" id="sl-${kind}" min="1" max="${Math.max(1,o.max)}" value="${d0}"/>
    <div class="v4-row"><span class="grow"><b id="sv-${kind}">${d0}</b> ${o.unit} <span class="v4-sub">of ${fmtN(o.max)}</span></span></div><div id="pv-${kind}" style="margin:8px 0"><div class="v4-sub">Scouting…</div></div>
    <button class="btn btn-danger btn-full atk-btn" ${o.hk?'data-hk="1"':''} onclick="doAttack('${kind}','${key}')">${o.btn}${o.hk?' <span class="keybind-hint">A</span>':''}</button></div>`;
}
async function previewBattle(kind,key){
  const sl=document.getElementById('sl-'+kind),src=document.getElementById('src-'+kind),el=document.getElementById('pv-'+kind);if(!sl||!el)return;
  const p=await api('POST','/api/combat/preview',{target_key:key,from_key:src?.value,amount:+sl.value,kind});
  if(p.error){el.innerHTML=`<div class="v4-sub">${esc(p.error)}</div>`;return}
  const pct=p.odds,col=pct==null?'var(--text2)':pct>=62?'var(--green2)':pct>=42?'var(--accent2)':'var(--red2)';
  el.innerHTML=`<div class="pv-odds" style="color:${col}">${pct!=null?pct+'%':`${p.odds_est[0]}–${p.odds_est[1]}%`}</div><div class="v4-bar"><i style="width:${pct??((p.odds_est[0]+p.odds_est[1])/2)}%"></i></div>
    <div class="pv-nums"><span>Your force <b>${p.attack}</b></span><span>${p.defense!=null?`Enemy <b>${p.defense}</b>`:`Enemy ≈ <b>${p.defense_est[0]}–${p.defense_est[1]}</b>`}</span></div>
    ${p.blocked?`<div class="v4-sub" style="color:var(--red2);margin-top:4px">${esc(p.blocked)}</div>`:''}${p.voyage?`<div class="v4-sub" style="margin-top:4px">⛵ Voyage of ${p.voyage.cells} cells costs <b>${p.voyage.money}💰 ${p.voyage.wood}🌲</b></div>`:''}
    ${chipsOf(p.atk_mods)}${p.def_mods?`<div class="v4-sub" style="margin-top:6px">Defender</div>${chipsOf(p.def_mods.map(([n,m])=>[n,1/m]))}`:'<div class="v4-sub" style="margin-top:6px">🕵 Espionage (or a faction with Intel Sharing) shows exact enemy numbers.</div>'}`;
}
async function doAttack(kind,key){
  if(!requireLogin())return;
  const sl=document.getElementById('sl-'+kind),src=document.getElementById('src-'+kind)?.value;if(!sl||!src)return;
  const n=+sl.value;let body,path;
  if(kind==='land'){path='/api/attack';body={from_key:src,target_key:key,troops:n}}
  else{const w={...await waterMapAsync(src),...await waterMapAsync(key)};
    if(kind==='naval'){path='/api/boats/attack';body={from_key:src,target_key:key,boats:n,water:w}}else{path='/api/planes/attack';body={from_key:src,target_key:key,planes:n,water:w}}}
  const r=await api('POST',path,body);if(r.error)return toast(r.error,'error');
  showBattleReport(r);achToast(r);await refreshAll();window.__force=true;await fetchAndBuildPanel(key);loadBattleLog();
}
async function claimTerritory(key){
  if(!requireLogin())return;
  const r=await api('POST','/api/territory/claim',{grid_key:key,water:await waterMapAsync(key)});
  if(r.error)return toast(r.error,'error');selectTerritory(key);afterAct(r,key);
}
async function buildTroops(key){if(!requireLogin())return;afterAct(await api('POST','/api/troops/build',{grid_key:key,amount:Math.max(1,+document.getElementById('build-n')?.value||1)}),key)}
async function bldAct(key,type){afterAct(await api('POST','/api/building/build',{grid_key:key,type,water:await waterMapAsync(key)}),key)}
async function setCapital(key){afterAct(await api('POST','/api/capital/set',{grid_key:key}),key)}
async function sellTile(key,v){if(!confirm(`Sell this tile for ${v}💰? You lose it and any building on it.`))return;afterAct(await api('POST','/api/territory/sell',{grid_key:key}),key)}
async function launchNuke(fk,tk){
  if(!confirm('☢ Launch a nuclear missile? The blast radius is random (3–10 cells) and may hit your own land.'))return;
  if(!confirm('Are you absolutely sure? This cannot be undone.'))return;
  const r=await api('POST','/api/nuke/launch',{from_key:fk,target_key:tk});if(r.error)return toast(r.error,'error');
  toast(r.message,'success');achToast(r);await refreshAll();drawFallout();window.__force=true;fetchAndBuildPanel(tk);
}
document.addEventListener('keydown',e=>{
  if(e.target.matches('input,textarea,select')||e.ctrlKey||e.metaKey||e.altKey)return;
  if(e.key==='a'||e.key==='A'){const b=document.querySelector('.atk-btn[data-hk="1"]')||document.querySelector('.atk-btn');if(b){e.preventDefault();b.click()}}
});

/* ── MARKET + income menu ── */
function buildMarket(){
  const el=document.getElementById('market-content');if(!el)return;
  if(!currentUser){el.innerHTML='<div class="empty-state">Login to sell</div>';return}
  const u=currentUser,all=['food','wood','metal','oil','steel','uranium','gems'];
  el.innerHTML=`<div class="v4-card"><h4>💹 Market <button class="btn btn-primary btn-sm" onclick="sellEverything()">💰 Sell ALL</button></h4>
    <div class="v4-sub">Total stock value: <b>${fmtN(all.reduce((s,r)=>s+(u[r]||0)*SELL_RATES[r],0))}💰</b></div></div>`+
    all.filter(r=>(u[r]||0)>0||['food','wood','metal','oil'].includes(r)).map(r=>{const have=u[r]||0;
      return`<div class="sell-card"><div class="sell-hdr"><span>${RES_CFG[r].icon} <strong>${RES_CFG[r].label}</strong> <span class="v4-sub">${SELL_RATES[r]}💰 each</span></span><span class="sell-have">${fmtN(have)} stored</span></div>
      <div class="input-row"><input type="number" class="input-sm" id="sell-${r}" value="${Math.floor(have/2)}" min="1" style="max-width:90px"/><span style="font-size:11px;color:var(--text3)">→ <span id="sell-earn-${r}">${Math.floor(have/2)*SELL_RATES[r]}</span>💰</span>
      <button class="btn btn-primary btn-sm" onclick="doSell('${r}')">Sell</button><button class="btn btn-ghost btn-sm" onclick="sellAll('${r}')">All</button></div></div>`}).join('')+
    `<div class="v4-card"><h4>📈 Income <span class="v4-sub" id="inc-sub"></span></h4><div class="v4-row" style="margin-bottom:8px">${[[10,'10 min'],[60,'1 hour'],[360,'6 hours'],[1440,'24 hours'],[10080,'7 days']].map(([m,l])=>`<button class="btn btn-ghost btn-sm" onclick="loadIncome(${m})">${l}</button>`).join('')}</div><div id="inc-body"><div class="v4-sub">Loading…</div></div></div>`;
  all.forEach(r=>{const i=document.getElementById('sell-'+r);if(i)i.oninput=()=>{document.getElementById('sell-earn-'+r).textContent=(parseInt(i.value)||0)*SELL_RATES[r]}});
  loadIncome(window.__incMin||60);
}
async function loadIncome(m){
  window.__incMin=m;const d=await api('GET','/api/income?minutes='+m),b=document.getElementById('inc-body');if(!b||d.error)return;
  const rows=Object.entries(d.totals).filter(([k,v])=>v>0);
  document.getElementById('inc-sub').textContent=`${d.tiles} tiles · ≈${fmtN(d.value_per_min)}💰-value/min`;
  b.innerHTML=(rows.length?`<div class="quest-grid">${rows.map(([k,v])=>`<div class="ach done"><b>${RES_CFG[k]?.icon||''} +${fmtN(v)}</b>${k} <span class="v4-sub">(${d.rates[k]}/min)</span></div>`).join('')}</div>`:'<div class="v4-sub">No income yet — claim some land!</div>')+
    (d.troops_per_min?`<div class="v4-sub" style="margin-top:6px">🏕 +${fmtN(d.troops_per_min*m)} troops from barracks</div>`:'')+(d.mults.length?chipsOf(d.mults):'')+`<div class="v4-sub" style="margin-top:6px">Tile prices are based on this income, so rich empires pay more per tile.</div>`;
}
async function sellAll(r){const x=await api('POST','/api/resources/sell_all',{resource:r});if(x.error)return toast(x.error,'error');toast(x.message,'success');await refreshUser();buildMarket()}
async function sellEverything(){if(!confirm('Sell ALL resources (food, wood, metal, oil, steel, uranium, gems)?'))return;const x=await api('POST','/api/resources/sell_all',{});if(x.error)return toast(x.error,'error');toast(x.message,'success');achToast(x);await refreshUser();buildMarket()}

/* ── leaderboard with population ── */
async function loadLeaderboard(){
  const el=document.getElementById('leaderboard-list');if(!el)return;
  const[list,w]=await Promise.all([api('GET','/api/leaderboard'),api('GET','/api/world')]);
  if(!list||list.error){el.innerHTML='<div class="empty-state">Error loading</div>';return}
  window.__players=list;
  el.innerHTML=`<div class="v4-sub" style="margin-bottom:8px">🌍 World: ${fmtPop(w.population)} people on ${w.territories} claimed tiles</div>`+list.map((p,i)=>{const me=currentUser&&p.username===currentUser.username;
    return`<div class="lb-row"><span class="lb-rank ${i<3?'top'+(i+1):''}">#${i+1}</span><span class="lb-col" style="background:${p.color}"></span><span class="lb-name${me?' me':''}">${p.tag?`<span style="color:var(--text3)">[${esc(p.tag)}]</span> `:''}${esc(p.username)}${p.is_admin?' ⭐':''}</span>
    <span class="lb-sub">🗺${p.territories}</span><span class="lb-sub">👥${fmtPop(p.total_pop)}</span><span class="lb-sub">🏅${p.wins||0}</span></div>`}).join('')||'<div class="empty-state">No players yet</div>';
}

/* ── notifications with action buttons ── */
const NOTIF_ACTS={};
function showNextNotif(){
  if(!notifPopupQueue.length){notifShowing=false;return}
  notifShowing=true;const n=notifPopupQueue.shift(),icon=NOTIF_ICONS[n.type]||'📬',container=document.getElementById('notif-container'),div=document.createElement('div');
  div.className=`notif-popup type-${n.type}`;div.style.position='relative';let acts='';const A=n.data?.actions;
  if(n.type==='alliance_invite'&&n.data?.alliance_id)acts=`<div class="notif-actions"><button class="btn btn-success btn-sm" onclick="respondAllianceNotif(${n.data.alliance_id},true,${n.id},this)">✓ Accept</button><button class="btn btn-danger btn-sm" onclick="respondAllianceNotif(${n.data.alliance_id},false,${n.id},this)">✕ Decline</button></div>`;
  else if(A){NOTIF_ACTS[n.id]=A;acts=`<div class="notif-actions">${A.map((a,i)=>`<button class="btn ${a.cls||'btn-primary'} btn-sm" onclick="notifAct(${n.id},${i},this)">${esc(a.label)}</button>`).join('')}</div>`}
  div.innerHTML=`<button class="notif-close" onclick="dismissNotifPopup(${n.id},this.parentElement)">✕</button><div class="notif-msg">${icon} ${esc(n.message)}</div><div class="notif-time">${n.created_at?n.created_at.slice(0,16):''}</div>${acts}`;
  container.appendChild(div);div._timer=setTimeout(()=>dismissNotifPopup(n.id,div),(A||n.type==='alliance_invite')?45000:7000);setTimeout(showNextNotif,500);
}
async function notifAct(id,i,btn){const a=NOTIF_ACTS[id][i];const r=await api('POST',a.path,a.body);toast(r.error||r.message||'Done',r.error?'error':'success');dismissNotifPopup(id,btn.closest('.notif-popup'));refreshAll()}

/* ── CHAT (admin edit / send-as, konami) ── */
let admUsers=[];
function chatLine(m){const t=new Date(m.ts*1000),hh=String(t.getHours()).padStart(2,'0')+':'+String(t.getMinutes()).padStart(2,'0');
  return`<div class="cm"><b style="color:${m.color||'#ccc'}">${esc(m.user)}</b><span id="cm-${m.id}">${esc(m.text)}</span>${m.edited?'<small class="v4-sub"> (edited)</small>':''}<time>${hh}</time>${currentUser?.is_admin?`<span class="del" onclick="adminEditMsg(${m.id})">✎</span><span class="del" onclick="adminDelMsg(${m.id})">✕</span>`:''}</div>`}
async function adminEditMsg(id){const cur=document.getElementById('cm-'+id)?.textContent||'';const t=prompt('Edit message:',cur);if(t===null)return;const r=await api('POST','/api/admin/chat_edit',{id,text:t});if(r.error)return toast(r.error,'error');buildChat()}
const _bc=buildChat;buildChat=async function(){
  _bc();
  if(currentUser?.is_admin){const inr=document.querySelector('.chat-in');if(inr&&!document.getElementById('chat-as')){
    if(!admUsers.length){const l=await api('GET','/api/admin/users');admUsers=Array.isArray(l)?l:(l.users||[])}
    inr.insertAdjacentHTML('beforebegin',`<select class="input-sm" id="chat-as" style="margin-top:6px;width:100%"><option value="">💬 Send as myself</option>${admUsers.map(u=>`<option value="${u.id}">🎭 as ${esc(u.username)}</option>`).join('')}</select>`)}}
};
const KONAMI='uuddlrlrba';
async function sendChat(){
  const inp=document.getElementById('chat-input'),m=inp?.value.trim();if(!m)return;inp.value='';
  const norm=m.toLowerCase().replace(/↑/g,'u').replace(/↓/g,'d').replace(/←/g,'l').replace(/→/g,'r').replace(/\b(up)\b/g,'u').replace(/\b(down)\b/g,'d').replace(/\b(left)\b/g,'l').replace(/\b(right)\b/g,'r').replace(/[^a-z]/g,'');
  if(norm===KONAMI){await api('POST','/api/konami');toast('🎮 Secret unlocked! Look in the Faction menu…','success');await refreshUser();return}
  const as=document.getElementById('chat-as')?.value;
  const r=as?await api('POST','/api/admin/chat_as',{user_id:+as,channel:chatCh,message:m}):await api('POST','/api/chat/send',{channel:chatCh,message:m});
  if(r.error)return toast(r.error,'error');achToast(r);pollChat();
}

/* ── FACTION (v5) ── */
async function buildFaction(){
  const el=document.getElementById('faction-content');if(!el)return;
  if(!currentUser){el.innerHTML='<div class="empty-state">Log in to join a faction</div>';return}
  const[inf,list]=await Promise.all([api('GET','/api/faction/info'),api('GET','/api/faction/list')]);const f=inf.faction;if(inf.error||!Array.isArray(list)){el.textContent=inf.error||list.error||'Unable to load factions';return;}
  const merge=inf.konami?`<div class="v4-card" style="border-color:#b46bff"><h4 style="color:#b46bff">🧬 Country Merge <span class="v4-sub">secret</span></h4><div class="v4-sub" style="margin-bottom:6px">Fuse two accounts into one. The player you invite is absorbed into YOUR country (land, resources, research, wonders…) and their account disappears.</div><div class="v4-row"><input class="form-input grow" id="mg-name" placeholder="Username to merge with"/><button class="btn btn-primary" onclick="mergeReq()">Propose</button></div></div>`:'';
  if(!f){
    el.innerHTML=`<div class="v4-card"><h4>🚩 Found a Faction <span class="v4-sub">500💰</span></h4><input class="form-input" id="fc-name" placeholder="Faction name (3–24)" style="margin-bottom:6px"/><div class="v4-row"><input class="form-input grow" id="fc-tag" placeholder="TAG" maxlength="4"/><button class="btn btn-primary" onclick="factionCreate()">Found</button></div>
      <div class="v4-sub" style="margin-top:6px">Factions share ONE army, optional fleets, ports & airports, a colour and a treasury. Members can't fight each other; factions fight via declared wars.</div></div>
      <div class="v4-card"><h4>Join a faction</h4>${(Array.isArray(list)&&list.length)?list.map(x=>`<div class="v4-row" style="margin-bottom:8px"><span class="owner-dot" style="background:${x.color}"></span><span class="grow"><b>[${esc(x.tag)}]</b> ${esc(x.name)} <span class="chip" style="font-size:10px">${x.mode==='open'?'🟢 open':x.mode==='invite'?'✉ invite':'🔒 closed'}</span><div class="v4-sub">👥 ${x.members} · 🗺 ${x.territories}${x.descr?' · '+esc(x.descr):''}</div></span>${x.mode==='closed'?'':`<button class="btn btn-ghost btn-sm" onclick="factionJoin(${x.id},'${x.mode}')">${x.mode==='invite'?'Request':'Join'}</button>`}</div>`).join(''):'<div class="v4-sub">No factions yet — be the first!</div>'}</div>`+merge;return}
  const lead=f.leader_id===currentUser.id,others=(Array.isArray(list)?list:[]).filter(x=>x.id!==f.id);
  const relBlock=f.rels.map(r=>`<div class="v4-row" style="margin-bottom:6px"><span class="chip ${r.kind==='war'?'bad':'good'}">${r.kind==='war'?'⚔ WAR':'🤝 ALLY'}${r.status==='pending'?' (pending)':''}</span><span class="grow"><b>[${esc(r.tag)}]</b> ${esc(r.other)}${r.kind==='war'?` <span class="v4-sub">${r.mine}–${r.theirs} (first to 25 wins)</span>`:''}</span>${lead?(r.kind==='war'?`<button class="btn btn-ghost btn-sm" onclick="facDo('/api/faction/war/end',{rel_id:${r.id}})">End</button>`:r.incoming?`<button class="btn btn-success btn-sm" onclick="facDo('/api/faction/rel/respond',{rel_id:${r.id},accept:true})">Accept</button>`:`<button class="btn btn-ghost btn-sm" onclick="facDo('/api/faction/rel/break',{rel_id:${r.id}})">Break</button>`):''}</div>`).join('')||'<div class="v4-sub">At peace with everyone.</div>';
  el.innerHTML=`<div class="v4-card" style="border-color:${f.color}"><h4><span>[${esc(f.tag)}] ${esc(f.name)}</span><span class="chip good">+${f.bonus_pct}% yield</span></h4>${f.descr?`<div class="v4-sub" style="margin-bottom:6px">${esc(f.descr)}</div>`:''}
    <div class="v4-row"><span class="chip">👥 ${f.members.length}/12</span><span class="chip">🗺 ${f.territories}</span><span class="chip">🧑 ${fmtPop(f.population)}</span><span class="chip gold">🏦 ${fmtN(f.treasury)}</span></div>
    <div class="v4-row" style="margin-top:6px"><span class="chip">⚔ ${fmtN(f.army)} shared</span><span class="chip">⚓ ${fmtN(f.boats)}</span><span class="chip">✈ ${fmtN(f.planes)}</span></div></div>
    <div class="v4-card"><h4>🏦 Treasury <span class="v4-sub">pays ${f.rate}% to members / 10 min</span></h4><div class="v4-row"><input type="number" class="input-sm grow" id="fd-amt" min="1" placeholder="Donate amount"/><button class="btn btn-success btn-sm" onclick="factionDonate()">Donate</button></div>
      ${lead?`<button class="btn btn-primary btn-full" style="margin-top:8px" onclick="factionRally()">📯 Rally — 1500💰 (morale → 100)${f.rally_ready_in?` · ${Math.ceil(f.rally_ready_in/60)}m`:''}</button>`:''}</div>
    <div class="v4-card"><h4>🔬 Faction Research <span class="v4-sub">paid from treasury</span></h4>${Object.entries(f.catalog).map(([id,t])=>{const own=f.techs.includes(id);return`<div class="v4-row" style="margin-bottom:6px"><span style="font-size:20px">${t.icon}</span><span class="grow"><b>${t.name}</b><div class="v4-sub">${t.desc}</div></span>${own?'<span class="chip good">✓</span>':lead?`<button class="btn btn-ghost btn-sm" onclick="facDo('/api/faction/research',{tech:'${id}'})">${fmtN(t.cost)}💰</button>`:`<span class="v4-sub">${fmtN(t.cost)}💰</span>`}</div>`}).join('')}</div>
    <div class="v4-card"><h4>⚔ Diplomacy</h4>${relBlock}${lead&&others.length?`<div class="v4-row" style="margin-top:8px"><select class="input-sm grow" id="dip-target">${others.map(x=>`<option value="${x.id}">[${esc(x.tag)}] ${esc(x.name)}</option>`).join('')}</select><button class="btn btn-danger btn-sm" onclick="dipDo('war')">War</button><button class="btn btn-success btn-sm" onclick="dipDo('ally')">Ally</button></div>`:''}</div>
    ${lead?`<div class="v4-card"><h4>⚙ Settings</h4><select class="input-sm" id="fs-mode" style="width:100%;margin-bottom:6px"><option value="open" ${f.mode==='open'?'selected':''}>🟢 Open — anyone can join</option><option value="invite" ${f.mode==='invite'?'selected':''}>✉ Invite only — join requests</option><option value="closed" ${f.mode==='closed'?'selected':''}>🔒 Closed — nobody can join</option></select>
      <input class="form-input" id="fs-desc" maxlength="140" placeholder="Description" value="${esc(f.descr)}" style="margin-bottom:6px"/><div class="v4-row"><span class="v4-sub">Faction colour</span><input type="color" id="fs-col" value="${f.color}" style="width:50px;height:34px;border:none;background:none"/><button class="btn btn-primary btn-sm grow" onclick="factionSettings()">Save</button></div></div>
      ${(f.requests||[]).length?`<div class="v4-card"><h4>✉ Join requests</h4>${f.requests.map(r=>`<div class="v4-row" style="margin-bottom:6px"><span class="grow"><b>${esc(r.username)}</b><div class="v4-sub">${esc(r.message||'')}</div></span><button class="btn btn-success btn-sm" onclick="facDo('/api/faction/request_respond',{request_id:${r.id},accept:true})">✓</button><button class="btn btn-danger btn-sm" onclick="facDo('/api/faction/request_respond',{request_id:${r.id},accept:false})">✕</button></div>`).join('')}</div>`:''}`:''}
    <div class="v4-card"><h4>Members</h4>${f.members.map(m=>`<div class="v4-row" style="margin-bottom:5px"><span class="owner-dot" style="background:${m.color}"></span><span class="grow">${esc(m.username)}${m.id===f.leader_id?' 👑':''}<span class="v4-sub"> · 🗺 ${m.territories} · 👥 ${fmtPop(m.pop)}</span></span>${lead&&m.id!==currentUser.id?`<button class="btn btn-ghost btn-sm" onclick="factionKick(${m.id})">Kick</button>`:''}</div>`).join('')}</div>${merge}
    <button class="btn btn-ghost btn-full" onclick="factionLeave()">Leave faction</button>`;
}
async function facDo(path,body){const r=await api('POST',path,body||{});if(r.error)return toast(r.error,'error');toast(r.message,'success');achToast(r);await refreshUser();await refreshAll();buildFaction()}
const factionCreate=()=>facDo('/api/faction/create',{name:document.getElementById('fc-name').value,tag:document.getElementById('fc-tag').value});
const factionLeave=()=>confirm('Leave your faction? You take your share of the army and fleet.')&&facDo('/api/faction/leave');
const factionKick=id=>confirm('Kick this member? They cannot rejoin until tomorrow.')&&facDo('/api/faction/kick',{user_id:id});
const factionDonate=()=>facDo('/api/faction/donate',{amount:+document.getElementById('fd-amt').value});
const factionRally=()=>facDo('/api/faction/rally');
const factionJoin=(id,mode)=>facDo('/api/faction/join',{faction_id:id,message:mode==='invite'?(prompt('Message to the leader (optional):')||''):''});
const factionSettings=()=>facDo('/api/faction/settings',{mode:document.getElementById('fs-mode').value,descr:document.getElementById('fs-desc').value,color:document.getElementById('fs-col').value});
const dipDo=k=>{const id=+document.getElementById('dip-target').value;if(k==='war'&&!confirm('Declare WAR? Both factions will be notified.'))return;facDo(k==='war'?'/api/faction/war/declare':'/api/faction/ally/propose',{faction_id:id})};
const mergeReq=()=>facDo('/api/merge/request',{username:document.getElementById('mg-name').value});

/* ── EMPIRE panel ── */
async function buildEmpire(){
  const el=document.getElementById('empire-content');if(!el)return;
  if(!currentUser){el.innerHTML='<div class="empty-state">Log in to rule an empire</div>';return}
  const u=currentUser;
  const[w,emb,lb,research]=await Promise.all([api('GET','/api/wonders'),api('GET','/api/embassy/list'),api('GET','/api/leaderboard'),Promise.resolve(0)]);
  if(!Array.isArray(w)||emb.error){el.textContent=w.error||emb.error||'Unable to load country information';return;}
  const players=(Array.isArray(lb)?lb:[]).filter(p=>p.id!==u.id&&!p.is_admin);window.__players=players;
  const opts=players.map(p=>`<option value="${p.id}">${esc(p.username)}</option>`).join('');
  const partners=[...new Set([...(emb.owned||[]).map(x=>x.host_id),...(emb.hosted||[]).map(x=>x.owner_id)])].map(id=>players.find(p=>p.id===id)).filter(Boolean);
  const popts=(u.faction?players.filter(p=>p.tag===u.faction.tag):[]).concat(partners).filter((p,i,a)=>a.findIndex(q=>q.id===p.id)===i).map(p=>`<option value="${p.id}">${esc(p.username)}</option>`).join('');
  const resOpts=['money','food','wood','metal','oil','steel','uranium','gems'].map(r=>`<option value="${r}">${resIcon[r]||RES_CFG[r]?.icon||''} ${r}</option>`).join('');
  const rs=new Set(u.research||[]);
  el.innerHTML=`<div class="v4-card"><h4>🎨 Country colour</h4><div class="v4-row"><input type="color" id="pc-col" value="${u.base_color||u.color}" style="width:54px;height:38px;border:none;background:none"/><span class="grow v4-sub">${u.faction?'While in a faction you use the faction colour; this one returns when you leave.':'Pick any colour you like.'}</span><button class="btn btn-primary btn-sm" onclick="saveColor()">Save</button></div></div>
  <div class="v4-card"><h4>🚩 Ideology <span class="v4-sub">${u.ideology?'change: 2000💰, once/24h':'first pick is free'}</span></h4>${Object.entries(IDEO).map(([id,i])=>`<div class="v4-row" style="margin-bottom:6px"><span style="font-size:22px">${i.icon}</span><span class="grow"><b>${i.name}</b><div class="v4-sub">${i.desc}</div></span>${u.ideology===id?'<span class="chip good">Active</span>':`<button class="btn btn-ghost btn-sm" onclick="empAct('/api/ideology/set',{id:'${id}'})">Adopt</button>`}</div>`).join('')}</div>
  <div class="v4-card"><h4>⭐ Capital</h4><div class="v4-sub">${u.capital_key?`Your capital is at cell ${u.capital_key}. Embassies of other countries gather there.`:'Select one of your tiles and press “Make capital”.'}</div>${u.capital_key?`<button class="btn btn-ghost btn-sm" style="margin-top:6px" onclick="flyTo('${u.capital_key}')">📍 Show on map</button>`:''}</div>
  <div class="v4-card"><h4>🗿 Wonders <span class="v4-sub">money sinks for the rich</span></h4>${w.map(x=>`<div class="v4-row" style="margin-bottom:8px"><span style="font-size:24px">${x.icon}</span><span class="grow"><b>${x.name}</b><div class="v4-sub">${x.desc} · ${fmtCost(x.cost)}</div></span>${x.owner?`<span class="chip gold">${esc(x.owner)}</span>`:`<button class="btn btn-primary btn-sm" onclick="empAct('/api/wonders/buy',{key:'${x.key}'})">Build</button>`}</div>`).join('')}</div>
  <div class="v4-card"><h4>🏳 Embassies ${rs.has('diplomacy')?'':'<span class="v4-sub">needs Diplomacy tech</span>'}</h4>
    <div class="v4-sub">Yours: ${(emb.owned||[]).map(x=>esc(x.name)).join(', ')||'none'}<br>In your capital: ${(emb.hosted||[]).map(x=>esc(x.name)).join(', ')||'none'}</div>
    ${rs.has('diplomacy')?`<div class="v4-row" style="margin-top:8px"><select class="input-sm grow" id="emb-t">${opts}</select><button class="btn btn-primary btn-sm" onclick="empAct('/api/embassy/build',{host_id:+document.getElementById('emb-t').value})">Open · 400💰</button></div>`:''}</div>
  <div class="v4-card"><h4>⚖ Trade deals</h4>${(emb.trades||[]).map(t=>`<div class="v4-row" style="margin-bottom:6px"><span class="grow v4-sub"><b>${esc(t.from_name)}</b> gives ${fmtN(t.give_amt)}${resIcon[t.give_res]||RES_CFG[t.give_res]?.icon} ⇄ <b>${esc(t.to_name)}</b> gives ${fmtN(t.get_amt)}${resIcon[t.get_res]||RES_CFG[t.get_res]?.icon} / 10 min ${t.status==='pending'?'(pending)':''}</span><button class="btn btn-ghost btn-sm" onclick="empAct('/api/trade/cancel',{trade_id:${t.id}})">✕</button></div>`).join('')||'<div class="v4-sub">No deals yet.</div>'}
    ${popts?`<div class="v4-sub" style="margin-top:8px">Propose a standing deal — you send, they send back:</div><select class="input-sm" id="tr-to" style="width:100%;margin:4px 0">${popts}</select><div class="v4-row"><input type="number" class="input-sm" id="tr-ga" value="50" style="width:78px"/><select class="input-sm" id="tr-gr">${resOpts}</select></div><div class="v4-row" style="margin-top:4px"><span class="v4-sub">they send</span><input type="number" class="input-sm" id="tr-ta" value="50" style="width:78px"/><select class="input-sm" id="tr-tr">${resOpts.replace('value="money"','value="money"').replace(/selected/,'')}</select></div><button class="btn btn-primary btn-full" style="margin-top:6px" onclick="proposeTrade()">Propose</button>`:'<div class="v4-sub" style="margin-top:6px">Trade needs an embassy (either way) or a shared faction.</div>'}</div>
  <div class="v4-card"><h4>🚢 Borrow boats / planes</h4>${(emb.loans||[]).map(l=>`<div class="v4-row" style="margin-bottom:6px"><span class="grow v4-sub">${esc(l.lender)} → ${esc(l.borrower)}: ${l.amount} ${l.unit} (${l.status})</span>${l.status==='active'?`<button class="btn btn-ghost btn-sm" onclick="empAct('/api/loan/return',{loan_id:${l.id}})">Return</button>`:''}</div>`).join('')}
    <select class="input-sm" id="ln-to" style="width:100%;margin:4px 0">${opts}</select><div class="v4-row"><select class="input-sm" id="ln-u"><option value="boats">⚓ boats</option><option value="planes">✈ planes</option></select><input type="number" class="input-sm" id="ln-a" value="1" min="1" style="width:70px"/></div><input class="form-input" id="ln-m" maxlength="200" placeholder="Custom message (optional)" style="margin:6px 0"/><button class="btn btn-primary btn-full" onclick="empAct('/api/loan/request',{to_id:+document.getElementById('ln-to').value,unit:document.getElementById('ln-u').value,amount:+document.getElementById('ln-a').value,message:document.getElementById('ln-m').value})">Ask to borrow</button><div class="v4-sub" style="margin-top:4px">Fleet sharing is optional in Settings and off by default.</div></div>
  <div class="v4-card" style="border-color:var(--red2)"><h4 style="color:var(--red2)">☢ Nuclear programme</h4>${nukeChecklist(u,rs)}</div>
  <div class="v4-card" style="border-color:var(--red2)"><h4 style="color:var(--red2)">⚠ Danger zone</h4><div class="v4-sub" style="margin-bottom:8px">Moving to a new place? Abandon every territory (no refund; you keep resources & army).</div><button class="btn btn-danger btn-full" onclick="abandonAll()">Abandon ALL my territories</button></div>`;
}
const IDEO={capitalism:{name:'Capitalism',icon:'🏦',desc:'+12% money, claims -10% price, troops +10% cost'},communism:{name:'Communism',icon:'☭',desc:'+6% all yields, troops -15% cost, money -8%'},militarism:{name:'Militarism',icon:'🎖',desc:'+10% attack, troops -10% cost, yields -5%'},democracy:{name:'Democracy',icon:'🗳',desc:'Research -15% cost, +5% defense, -3% attack'},theocracy:{name:'Theocracy',icon:'⛪',desc:'+10% defense, morale floor 35, casualties -10%, money -5%'}};
function nukeChecklist(u,rs){
  const gt=groupTiles(),has=b=>gt.some(k=>territories[k].building===b),row=(ok,t)=>`<div class="v4-sub">${ok?'✅':'⬜'} ${t}</div>`;
  const ready=['nuclear_physics','rocketry','manhattan'].every(t=>rs.has(t))&&['uranium_mine','enrichment','nuclear_plant'].every(has);
  return row(rs.has('nuclear_physics'),'Nuclear Physics')+row(rs.has('rocketry'),'Rocketry')+row(rs.has('manhattan'),'Manhattan Project')+row(has('uranium_mine'),'Uranium Mine')+row(has('enrichment'),'Enrichment Plant')+row(has('nuclear_plant'),'Nuclear Plant ⚛ (tiny meltdown risk — a meltdown permanently ruins its surroundings!)')+row(has('silo'),'Missile Silo (to launch)')+
    `<div class="v4-sub" style="margin:6px 0">Warhead: <b>${fmtN(u.nuke_cost)}💰</b> + 300☢ + 3000🔩 · you hold <b>${u.nukes}</b></div><button class="btn btn-danger btn-full" ${ready?'':'disabled'} onclick="empAct('/api/nuke/build',{})">☢ Build warhead</button>${u.faction?.is_leader?`<button class="btn btn-ghost btn-full" style="margin-top:6px" ${ready?'':'disabled'} onclick="empAct('/api/nuke/build',{from_treasury:true})">…paid from faction treasury</button>`:''}`;
}
async function empAct(path,body){const r=await api('POST',path,body);if(r.error)return toast(r.error,'error');toast(r.message||'Done','success');achToast(r);await refreshUser();await refreshAll();buildEmpire()}
async function saveColor(){const r=await api('POST','/api/profile/color',{color:document.getElementById('pc-col').value});if(r.error)return toast(r.error,'error');toast(r.message,'success');await refreshUser();await refreshAll();buildEmpire()}
const proposeTrade=()=>empAct('/api/trade/propose',{to_id:+document.getElementById('tr-to').value,give_res:document.getElementById('tr-gr').value,give_amt:+document.getElementById('tr-ga').value,get_res:document.getElementById('tr-tr').value,get_amt:+document.getElementById('tr-ta').value});
function flyTo(key){const[gl,gg]=parseKey(key);map.setView([(gl+.5)*GRID,(gg+.5)*GRID],7);if(isMobile())closeMobileSheet()}
async function abandonAll(){
  if(!confirm('Abandon ALL your territories?'))return;
  if(!confirm('Really? Every tile and building you own will become wilderness. This cannot be undone.'))return;
  if(prompt('Type your username to continue:')!==currentUser.username)return toast('Username did not match','error');
  const pw=prompt('Enter your password:');if(pw===null)return;
  if(prompt('Final step — type DELETE ALL MY TERRITORIES')!=='DELETE ALL MY TERRITORIES')return toast('Cancelled','error');
  const r=await api('POST','/api/territory/abandon_all',{password:pw,confirm:'DELETE ALL MY TERRITORIES'});if(r.error)return toast(r.error,'error');toast(r.message,'success');await refreshAll();buildEmpire();
}

/* ── TUTORIAL ── */
const TUT=[
 ['🌍 Welcome to World Conquest!','The map is divided into small cells. Tap or click any cell to inspect it. Hover (or tap) shows exact coordinates and whether it is land or water.'],
 ['🏴 Claim your first tile','Pick a land tile and press <b>Claim</b> (hotkey <b>C</b>). Your first tile is cheap. Later tiles cost money <i>and</i> resources, scaled to how much you earn — rich empires pay more.'],
 ['💰 Resources & income','Every tile produces a resource per minute. The Market tab shows exactly how much you make per 10 min / hour / day, and lets you sell everything with one button.'],
 ['⚔ Your army','Recruit troops on any tile you own — there is <b>no cap</b>. One army defends all your land and is what you attack with. Mountains, forests, weather, morale, Fortresses and your capital all change the odds. Press <b>A</b> to attack the selected tile.'],
 ['🏗 Buildings','Barracks make free troops, Markets money, Workshops boost a tile, Mines make Steel, Uranium and Gems. Fortresses and Hospitals keep you alive. Research unlocks more.'],
 ['⚓ Boats & ✈ planes','Ports (coast only) launch boats that can cross any distance — each cell sailed costs resources — and land on any coast. Airports launch planes within a limited range.'],
 ['🚩 Factions','Found or join a faction: shared army, optional fleets, ports, colour and treasury (1% is paid out to members every 10 min). Spend the treasury on faction research. Declare war on other factions to fight them — or ally with them.'],
 ['👑 Your empire','Choose an ideology, set a capital ⭐, open embassies to trade, build wonders with spare cash, and in the endgame… ☢ the Manhattan Project.'],
 ['💬 Have fun!','Chat with everyone, grab your daily reward in Quests, collect achievements. You can reopen this tutorial any time via ❓ Help.'],
];
function showTutorial(i){
  let ov=document.getElementById('tut');if(!ov){ov=document.createElement('div');ov.id='tut';document.body.appendChild(ov)}
  if(i>=TUT.length){ov.classList.remove('open');localStorage.setItem('wc_tut','1');return}
  const[t,b]=TUT[i];ov.classList.add('open');
  ov.innerHTML=`<div class="tut-box"><div class="v4-sub">Step ${i+1} / ${TUT.length}</div><h2>${t}</h2><p>${b}</p><div class="v4-row" style="margin-top:14px"><button class="btn btn-ghost" onclick="showTutorial(${TUT.length})">Skip</button><span class="grow"></span>${i?`<button class="btn btn-ghost" onclick="showTutorial(${i-1})">Back</button>`:''}<button class="btn btn-primary" onclick="showTutorial(${i+1})">${i===TUT.length-1?'Let\'s play!':'Next'}</button></div></div>`;
}

/* ── admin extras ── */
function injectAdmin2(){
  const gr=document.getElementById('adm-gr');if(gr&&!gr.dataset.v5){gr.dataset.v5=1;['steel','uranium','gems','nukes'].forEach(r=>gr.insertAdjacentHTML('beforeend',`<option>${r}</option>`))}
  const w=document.getElementById('admin-world');if(w&&!document.getElementById('adm-nuke')){
    w.firstElementChild.insertAdjacentHTML('beforeend',`<div class="tc"><div class="section-label">☢ Nukes & fallout</div><div class="input-row" style="margin-top:6px"><span class="v4-sub">Warhead cost</span><input class="input-sm" id="adm-nuke" type="number" style="max-width:130px"/><button class="btn btn-ghost btn-sm" onclick="admSet('nuke_cost',document.getElementById('adm-nuke').value)">Set</button><button class="btn btn-danger btn-sm" onclick="if(confirm('Clear ALL fallout, including permanent?'))admRun('/api/admin/clear_fallout',{},()=>drawFallout())">Clear all fallout</button></div></div>`)}
}
const _lw=loadAdmWorld;loadAdmWorld=async function(){await _lw();injectAdmin2();const s=await api('GET','/api/admin/stats');const n=document.getElementById('adm-nuke');if(n)n.value=s.settings?.nuke_cost??100000000};

/* ── bootstrap v5 ── */
const _sg2=startGame;
startGame=async function(user){
  await _sg2(user);
  api('GET','/api/research').then(r=>{if(r&&r.tree)Object.assign(RESEARCH_TREE,r.tree)});
  api('GET','/api/buildings').then(b=>{if(b&&!b.error)BLD=b});
  drawFallout();setInterval(drawFallout,60000);
  const pc=document.querySelector('.stab[data-panel="empire"]');
  if(!localStorage.getItem('wc_tut')&&(currentUser?.territory_count||0)===0)setTimeout(()=>showTutorial(0),900);
};

