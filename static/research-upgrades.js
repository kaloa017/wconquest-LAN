/* Keep the larger focus tree searchable without changing saved project IDs. */
const expandedResearchPanel=buildResearch;
buildResearch=async function(){
  await expandedResearchPanel();
  const el=document.getElementById('research-content');if(!el?.querySelector('.research-branch'))return;
  const owned=new Set(currentUser?.research||[]),total=Object.keys(RESEARCH_TREE).length;
  const controls=document.createElement('section');controls.className='v4-card';controls.id='research-filters';
  controls.innerHTML=`<h3>${owned.size} / ${total} technologies completed</h3><p>Specialize in industry, economy, combat and space. Modern, Advanced, Frontier and Stellar focuses extend into the late game.</p><label>Search research<input type="search" class="form-input" id="research-search" data-ui-filter></label><label>Show<select class="form-input" id="research-status-filter" data-ui-filter><option value="all">All technologies</option><option value="available">Available</option><option value="locked">Locked</option><option value="done">Completed</option></select></label><label>Era<select class="form-input" id="research-era-filter" data-ui-filter><option value="all">All eras</option><option value="Legacy">Foundations</option>${['Modern','Advanced','Frontier','Stellar'].map(era=>`<option>${era}</option>`).join('')}</select></label><p id="research-result-count" role="status"></p>`;
  el.querySelector('.research-branch').before(controls);
  for(const node of el.querySelectorAll('.focus-node')){
    const tech=RESEARCH_TREE[node.id.slice(6)];node.dataset.era=tech?.era||'Legacy';
    if(tech?.era){const badge=document.createElement('span');badge.className='chip';badge.textContent=tech.era;node.prepend(badge);}
  }
  const search=controls.querySelector('input'),status=controls.querySelector('#research-status-filter'),era=controls.querySelector('#research-era-filter');
  search.value=el.dataset.researchQuery||'';status.value=el.dataset.researchStatus||'all';era.value=el.dataset.researchEra||'all';
  function filter(){
    el.dataset.researchQuery=search.value;el.dataset.researchStatus=status.value;el.dataset.researchEra=era.value;
    let count=0;
    for(const node of el.querySelectorAll('.focus-node')){
      node.hidden=!(node.textContent.toLowerCase().includes(search.value.toLowerCase())&&(status.value==='all'||node.classList.contains(status.value))&&(era.value==='all'||node.dataset.era===era.value));
      if(!node.hidden&&!node.closest('.research-branch').hidden)count++;
    }
    for(const stage of el.querySelectorAll('.focus-stage'))stage.hidden=![...stage.querySelectorAll('.focus-node')].some(node=>!node.hidden);
    controls.querySelector('#research-result-count').textContent=count+' technologies shown';
  }
  search.oninput=filter;status.onchange=filter;era.onchange=filter;
  const path=document.getElementById('research-path'),oldChange=path.onchange;path.onchange=()=>{oldChange();filter();};filter();
};
PANELS.research.f=buildResearch;
const expandedJump=jumpToResearch;
jumpToResearch=function(key){
  const el=document.getElementById('research-content');
  for(const id of ['research-search','research-status-filter','research-era-filter']){const field=document.getElementById(id);if(field){field.value=id==='research-search'?'':'all';field.dispatchEvent(new Event(id==='research-search'?'input':'change'));}}
  if(el)el.dataset.researchQuery='';expandedJump(key);
};
