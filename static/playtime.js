let playtimeBase=0,playtimeAt=Date.now(),playtimePage=1,playtimeTick=null;
function formatPlaytime(seconds){seconds=Math.max(0,Math.floor(Number(seconds)||0));const hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60);return `${hours.toLocaleString('en-US')}h ${String(minutes).padStart(2,'0')}m ${String(seconds%60).padStart(2,'0')}s`}
function setPlaytime(seconds){playtimeBase=seconds;playtimeAt=Date.now();renderMyPlaytime()}
function renderMyPlaytime(){if(!currentUser)return;const seconds=playtimeBase+(!document.hidden?(Date.now()-playtimeAt)/1000:0);for(const id of ['my-playtime','my-playtime-panel']){const node=document.getElementById(id);if(node)node.textContent='⏱ '+formatPlaytime(seconds)}}
async function buildPlaytime(page=1){
  const generation=sessionGeneration,el=document.getElementById('playtime-content');if(!el)return;
  const r=await api('GET','/api/playtime?page='+page);if(generation!==sessionGeneration||!el.isConnected)return;if(r.error){el.textContent=r.error;return}
  playtimePage=r.page;setPlaytime(r.mine);
  el.innerHTML=card('⏱ Your playtime',`<b id="my-playtime-panel">${formatPlaytime(r.mine)}</b><p class="v4-sub">Counts from this update while the game is open in a visible tab. Hidden or closed tabs do not count. Multiple tabs never multiply your total. The inactivity production pause is separate.</p>`)+card('Player playtime',`<div class="v4-row"><button class="btn btn-ghost" onclick="buildPlaytime(${r.page})">Refresh</button><span>${r.page} / ${r.pages}</span></div><div class="playtime-list">${r.players.map(u=>`<div><span>${esc(u.username)}${u.id===currentUser?.id?' · you':''}</span><b>${formatPlaytime(u.seconds)}</b></div>`).join('')||'<p>No players yet.</p>'}</div><div class="v4-row">${r.page>1?`<button class="btn btn-ghost" onclick="buildPlaytime(${r.page-1})">← Previous</button>`:''}${r.page<r.pages?`<button class="btn btn-ghost" onclick="buildPlaytime(${r.page+1})">Next →</button>`:''}</div>`);renderMyPlaytime();
}
menuItems.playtime={name:'Playtime',icon:'⏱',desc:'See your time and other players’ totals'};
addNavigation('playtime','⏱ Playtime',buildPlaytime);
const playtimeBadge=document.createElement('span');playtimeBadge.id='my-playtime';playtimeBadge.title='Time with the game visible';playtimeBadge.textContent='⏱ 0h 00m 00s';document.querySelector('.player-info')?.appendChild(playtimeBadge);
const playtimeStart=startSession;
startSession=async function(user){await playtimeStart(user);if(currentUser){playtimeTick=setInterval(renderMyPlaytime,1000)}};startGame=startSession;startSpectatorMode=()=>startSession(null);
const playtimeStop=stopPolling;
stopPolling=function(){clearInterval(playtimeTick);playtimeTick=null;playtimeBase=0;playtimeAt=Date.now();playtimeStop()};
function closePlaytimePresence(){if(!currentUser)return;fetch('/api/activity',{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json','X-WC-CSRF':csrf},body:JSON.stringify({active:false,visible:false})}).catch(()=>{})}
window.addEventListener('pagehide',closePlaytimePresence);
document.addEventListener('visibilitychange',()=>{if(document.hidden){playtimeBase+=Math.max(0,(Date.now()-playtimeAt)/1000);playtimeAt=Date.now();closePlaytimePresence()}else{playtimeAt=Date.now();checkActivity()}});
