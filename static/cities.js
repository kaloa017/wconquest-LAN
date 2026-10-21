/* Offline city directory, bounded canvas markers and live capital district controls. */
(function(w){
  const doc=w.document;let cityData=null,cityPromise=null,byTile=new Map(),cityLayer=null;
  async function loadCities(){
    if(cityData)return cityData;
    if(!cityPromise)cityPromise=fetch('/api/cities?v='+encodeURIComponent(gameConfig.version||'')).then(r=>{if(!r.ok)throw new Error('City directory unavailable');return r.json()}).then(data=>{cityData=data;byTile=new Map();for(const c of data.cities){if(!c.playable)continue;if(!byTile.has(c.grid_key))byTile.set(c.grid_key,[]);byTile.get(c.grid_key).push(c)}return data}).catch(error=>{cityPromise=null;throw error});
    return cityPromise;
  }
  function drawCities(){
    if(!map||!cityData)return;if(cityLayer)map.removeLayer(cityLayer);cityLayer=L.layerGroup().addTo(map);
    const zoom=map.getZoom();if(zoom<3)return;const bounds=map.getBounds(),seen=new Set();let count=0;
    for(const c of cityData.cities){if(!c.playable||seen.has(c.grid_key)||!bounds.contains([c.tile_lat,c.tile_lng]))continue;
      if(zoom<5&&!c.national_capital&&c.population<3000000)continue;
      seen.add(c.grid_key);L.circleMarker([c.tile_lat,c.tile_lng],{renderer:canvasR,radius:zoom<5?3:5,color:'#ffe0a4',weight:1,fillColor:'#a7d6ff',fillOpacity:.8,interactive:false}).addTo(cityLayer);if(++count>=(zoom<5?40:120))break;
    }
  }
  const init=initMap;initMap=function(){init();map.on('moveend',drawCities);loadCities().then(drawCities).catch(error=>console.warn(error.message))};
  const move=onMapMove;onMapMove=function(event){move(event);if(!cityData)return;const island=islandAt(event.latlng.lat,event.latlng.lng),key=island?.properties.key||`${Math.floor(event.latlng.lat/GRID)},${Math.floor(event.latlng.lng/GRID)}`,cities=byTile.get(key),info=doc.getElementById('hover-info');if(cities&&info)info.textContent+=' · 🏙 '+cities.map(c=>c.name).join(', ')+' · 1.5× production/recruitment · 1.25× defense'};

  w.showCityDirectory=async function(){
    try{const data=await loadCities();openCommunityDialog('Major cities',`<p>${data.cities.length.toLocaleString()} cities · population estimate ≥250,000 or a national capital. Cities sharing a tile grant one bonus. Gold/blue dots mark nearby cities on the map.</p><label>Find a city, country or tile<input id="city-search" class="form-input" placeholder="Oslo, Japan, 332,59…" autocomplete="off"></label><label><input type="checkbox" id="city-owned"> Only my city tiles</label><p>Every city tile: 1.5× local production and recruitment, 1.25× defense. Capital bonuses multiply with these.</p><p id="city-result-count" role="status"></p><div id="city-results"></div><p class="v4-sub">Natural Earth estimates are historical. Coastal points are mapped to nearby playable land; the registry records both coordinates. <a href="/api/cities" target="_blank" rel="noopener noreferrer">Download JSON registry</a> · <a href="/api/cities.csv">Download CSV</a></p>`);
      const search=doc.getElementById('city-search'),owned=doc.getElementById('city-owned'),results=doc.getElementById('city-results');
      function render(){const q=search.value.trim().toLocaleLowerCase(),matches=data.cities.filter(c=>(!owned.checked||currentUser&&territories[c.grid_key]?.owner_id===currentUser.id)&&(!q||[c.name,c.country,c.grid_key].join(' ').toLocaleLowerCase().includes(q)));doc.getElementById('city-result-count').textContent=`${matches.length} matching cities · showing up to 60`;results.innerHTML=matches.slice(0,60).map(c=>`<article class="v4-card"><h3>🏙 ${esc(c.name)}${c.national_capital?' · national capital':''}</h3><p>${esc(c.country)} · estimated population ${fmtN(c.population)}<br>Tile <code>${esc(c.grid_key)}</code>${c.relocated?' · mapped to nearby playable land':''}${territories[c.grid_key]?.owner?' · '+esc(territories[c.grid_key].owner):' · unclaimed'}</p><button class="btn btn-primary" data-city-find="${esc(c.grid_key)}">Find on map</button></article>`).join('')||'<p>No matching cities. Try another name or country.</p>'}
      search.oninput=render;owned.onchange=render;render();
    }catch(error){toast(error.message,'error')}
  };
  doc.addEventListener('click',async event=>{
    const city=event.target.closest('[data-city-find]');if(city){closeCommunityDialog();flyTo(city.dataset.cityFind);await inspectIsland(city.dataset.cityFind)}
    const button=event.target.closest('[data-capital-upgrade]');if(button){button.disabled=true;try{const result=await api('POST','/api/capital/district',{type:button.dataset.capitalUpgrade,grid_key:button.dataset.capitalTile});if(result.error)return toast(result.error,'error');toast(result.message,'success');await refreshUser();await buildEmpire();await refreshTerritories()}finally{if(button.isConnected)button.disabled=false}}
    if(event.target.closest('[data-open-city-directory]'))w.showCityDirectory();
  });
  const empire=buildEmpire;buildEmpire=async function(){
    await empire();if(!currentUser)return;const user=currentUser.id,el=doc.getElementById('empire-content');if(!el)return;
    const data=await api('GET','/api/capital');if(!el.isConnected||currentUser?.id!==user)return;el.querySelector('#capital-development')?.remove();
    const section=doc.createElement('section');section.id='capital-development';section.className='v4-card';
    if(data.error){section.innerHTML='<h3>Capital development</h3><p>'+esc(data.error)+'</p>';el.prepend(section);return}
    const b=data.bonuses;section.innerHTML=`<h3>⭐ Capital stronghold</h3><p>${data.grid_key?'Tile '+esc(data.grid_key)+(data.cities.length?' · '+data.cities.map(c=>esc(c.name)).join(', '):''):'Choose an owned tile and press Make capital to unlock development.'}</p><p>${data.owned_cities} major cities on ${data.owned_city_tiles} owned city tiles.</p><button class="btn btn-ghost" data-open-city-directory>Browse major cities</button>${data.grid_key?`<p><strong>${fmtN(b.production,2)}× local production · ${fmtN(b.recruitment,2)}× recruitment · ${fmtN(b.defense,2)}× defense</strong><br>12 base troops/min before multipliers, plus buildings and districts.</p><p>Six additional building slots, separate from the normal tile building. Up to level ${data.max_level} each. Effects apply only while this tile is your capital. Moving costs no money and has a 24-hour cooldown. Districts stay on the tile; capture transfers them dormant, while abandonment or destruction removes them.</p><details><summary>Develop capital · 6 district buildings</summary>${data.districts.map(d=>`<article class="capital-district"><h4>${esc(d.icon)} ${esc(d.name)} · Lv ${d.level}/${data.max_level}</h4><p>${esc(d.desc)}</p>${d.next_cost?`<p>${fmtCost(d.next_cost)}</p><button class="btn btn-primary" data-capital-upgrade="${esc(d.key)}" data-capital-tile="${esc(data.grid_key)}">${d.level?'Upgrade':'Construct'} · level ${d.level+1}</button>`:'<p>Maximum level reached.</p>'}</article>`).join('')}</details>`:''}`;
    el.prepend(section);
  };PANELS.empire.f=()=>buildEmpire();
  const panel=buildTerritoryPanel;buildTerritoryPanel=function(key,t,container){panel(key,t,container);const el=container||doc.getElementById('territory-actions');if(!el)return;el.querySelector('.city-tile-summary')?.remove();if(!t.cities?.length&&!t.capital&&!t.capital_districts?.length)return;const b=t.urban_bonuses;if(!b)return;const section=doc.createElement('section');section.className='v4-card city-tile-summary';section.innerHTML=`<h3>${t.capital?'⭐ Capital':t.cities?.length?'🏙 Major city':'🏛 Former capital districts'}${t.cities?.length?' · '+t.cities.map(c=>esc(c.name)).join(', '):''}</h3><p>${fmtN(b.production,2)}× local production · ${fmtN(b.recruitment,2)}× recruitment · ${fmtN(b.defense,2)}× defense${t.owner_id?'':' when owned'}. All bonuses stack with research and existing buildings.</p>${(t.capital_districts||[]).map(d=>`<p>${esc(d.name)} · Lv ${d.level}${d.active?'':' · dormant until this tile becomes your capital'}</p>`).join('')}${t.capital&&currentUser?.id===t.owner_id?'<button class="btn btn-primary" data-open-capital>Develop capital in Country</button>':''}`;el.prepend(section)};
  doc.addEventListener('click',event=>{if(event.target.closest('[data-open-capital]')){if(isMobile())openExpansionPanel('empire');else showPanel('empire')}});
  w.WCCities={load:loadCities,draw:drawCities};
})(window);
