/* Only deliberate human input renews production. Polling only reports presence. */
let activityDirty=false,activityBusy=false,activityTimer=null,activityDeadline=0,activityOffset=0,activityReturnFocus=null;
const activityInert=new Map();
function showActivityPause(){
  if(!currentUser||document.getElementById('activity-paused'))return;
  activityReturnFocus=document.activeElement;
  const overlay=document.createElement('div');overlay.id='activity-paused';overlay.className='activity-overlay';
  overlay.innerHTML='<section class="v6-dialog" role="dialog" aria-modal="true" aria-labelledby="activity-title"><h2 id="activity-title">Still playing?</h2><p>You have been inactive for 30 minutes. Food, wood, money, troops and space production are paused.</p><p>The paused time earns no resources. Your country is still here.</p><button class="btn btn-primary btn-full" id="activity-resume">Keep playing</button><p id="activity-error" role="alert"></p></section>';
  for(const child of document.body.children){activityInert.set(child,child.inert);child.inert=true}
  document.body.appendChild(overlay);const button=overlay.querySelector('button');button.focus();
  overlay.onkeydown=e=>{if(e.key==='Tab'){e.preventDefault();button.focus()}};
  button.onclick=async()=>{button.disabled=true;const r=await api('POST','/api/activity/resume',{});if(r.error){overlay.querySelector('#activity-error').textContent=r.error;button.disabled=false;return}setActivityState(r);clearActivityPause();activityDirty=false;await refreshUser();await api('GET','/api/income')};
}
function clearActivityPause(){document.getElementById('activity-paused')?.remove();for(const [node,value] of activityInert)if(node.isConnected)node.inert=value;activityInert.clear();activityReturnFocus?.focus?.({preventScroll:true});activityReturnFocus=null}
function setActivityState(r){if(!r||r.error)return;if(r.server_time){activityOffset=r.server_time*1000-Date.now();activityDeadline=r.deadline*1000}if(r.inactive)showActivityPause()}
async function checkActivity(){
  if(!currentUser||document.hidden||activityBusy)return;activityBusy=true;const generation=sessionGeneration,dirty=activityDirty;activityDirty=false;
  try{const r=await api('POST','/api/activity',{active:dirty});if(generation===sessionGeneration){setActivityState(r);if(r.error)activityDirty=activityDirty||dirty}}finally{activityBusy=false}
}
for(const event of ['pointerdown','keydown','wheel','touchstart'])document.addEventListener(event,e=>{if(!e.isTrusted||!currentUser||document.hidden||document.getElementById('activity-paused'))return;if(activityDeadline&&Date.now()+activityOffset>=activityDeadline){showActivityPause();return}activityDirty=true},{passive:true});
const activityApi=api;
api=async function(method,url,data){const r=await activityApi(method,url,data);if(r.inactive)showActivityPause();return r};
const activityStart=startSession;
startSession=async function(user){await activityStart(user);if(!currentUser)return;setActivityState(await api('GET','/api/activity'));activityTimer=setInterval(checkActivity,30000)};
startGame=startSession;startSpectatorMode=()=>startSession(null);
const activityStop=stopPolling;
stopPolling=function(){clearInterval(activityTimer);activityTimer=null;activityDeadline=0;activityDirty=false;clearActivityPause();activityStop()};
const activitySettings=buildSettings;
buildSettings=function(){activitySettings();document.getElementById('settings-content')?.insertAdjacentHTML('beforeend',card('Rules and privacy','<p>Production pauses after 30 minutes without interaction. Recently logged-in players must be online for a new war declaration.</p><p><a href="/terms" target="_blank" rel="noopener">Terms and conditions</a> · <a href="/privacy" target="_blank" rel="noopener">Privacy policy</a></p>'))};
// Live claim quotes must follow changes in current ownership and production.
const activityRefreshUser=refreshUser;
refreshUser=async function(){const previous=currentUser?`${currentUser.territory_count}:${currentUser.claim_cost}`:'';await activityRefreshUser();if(currentUser&&previous!==`${currentUser.territory_count}:${currentUser.claim_cost}`&&selectedKey&&(isMobile()?sheetPanel==='territory'&&document.getElementById('mobile-sheet').classList.contains('open'):document.getElementById('panel-territory')?.classList.contains('active')))await fetchAndBuildPanel(selectedKey)};
document.addEventListener('visibilitychange',()=>{if(!document.hidden){if(activityDeadline&&Date.now()+activityOffset>=activityDeadline)showActivityPause();checkActivity()}});
document.addEventListener('focusin',event=>{const overlay=document.getElementById('activity-paused');if(overlay&&!overlay.contains(event.target))overlay.querySelector('button').focus()});
