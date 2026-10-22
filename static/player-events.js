/* One stored event stream for the bell, presentation claims and non-blocking feedback. */
(function(w){
  const doc=w.document;let request=null,queue=[],visible=0,history=[],nextBefore=null,mode='unread',owner=null,toastEpoch=0,inboxRequest=0;
  function reset(){toastEpoch++;queue=[];visible=0;history=[];nextBefore=null;doc.getElementById('player-event-toasts')?.remove()}
  function timestamp(value){const text=String(value||'').replace(' ','T');return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/.test(text)?text:text+'Z')}
  function grouped(events){
    const groups=new Map(),result=[];
    for(const event of events){
      const groupable=event.type==='territory_lost'&&event.data?.actor_id;
      const stamp=timestamp(event.created_at),key=groupable&&Number.isFinite(stamp)?event.type+':'+event.data.actor_id+':'+Math.floor(stamp/120000):'event:'+event.id;
      if(groups.has(key)){const group=groups.get(key);group.members.push(event);if(event.is_read===0)group.is_read=0;continue}
      const item={...event,members:[event]};groups.set(key,item);result.push(item);
    }
    return result.sort((a,b)=>(a.priority||4)-(b.priority||4));
  }
  function text(event){return event.members.length>1?`${event.data.actor_name||'Another player'} captured ${event.members.length} of your territories.`:event.message}
  function pump(){
    if(!currentUser||document.hidden)return;
    let host=doc.getElementById('player-event-toasts');if(!host){host=doc.createElement('section');host.id='player-event-toasts';host.setAttribute('aria-label','Player activity');host.setAttribute('aria-live','polite');doc.body.appendChild(host)}
    const limit=w.matchMedia('(max-width:768px)').matches?1:2;
    while(visible<limit&&queue.length){const item=queue.shift(),el=doc.createElement('article');el.className='player-event-toast priority-'+item.priority;
      el.innerHTML=`<strong>${item.priority===1?'Important activity':'Country activity'}</strong><p>${esc(text(item))}</p><div><button class="btn btn-ghost btn-sm" data-event-inbox>View details</button><button class="btn btn-ghost btn-sm" aria-label="Dismiss activity toast">✕</button></div>`;
      visible++;host.appendChild(el);const epoch=toastEpoch;let removed=false;const close=()=>{if(removed||epoch!==toastEpoch)return;removed=true;el.remove();visible--;pump()};el.querySelector('[aria-label]').onclick=close;el.querySelector('[data-event-inbox]').onclick=()=>{close();w.openNotificationInbox('history')};
      const expire=()=>{if(removed)return;if(el.contains(doc.activeElement)||el.matches(':hover')){setTimeout(expire,2000);return}close()};setTimeout(expire,item.priority===1?12000:6000);
    }
  }
  pollNotifications=async function(){
    const uid=currentUser?.id;if(owner!==uid){reset();owner=uid}if(!uid){inboxNotifications=[];updateNotificationCount();return}
    if(request)return request;
    const generation=sessionGeneration;
    request=(async()=>{const list=await api('GET','/api/notifications');if(generation!==sessionGeneration||currentUser?.id!==uid||!Array.isArray(list))return;
      inboxUser=uid;inboxNotifications=list;updateNotificationCount();
      const ids=list.filter(n=>n.presented_at===0).map(n=>n.id);if(!ids.length||doc.hidden)return;
      const result=await api('POST','/api/notifications/present',{ids});if(generation!==sessionGeneration||currentUser?.id!==uid||!Array.isArray(result.events))return;
      queue.push(...grouped(result.events).filter(n=>n.priority<=2));queue.sort((a,b)=>a.priority-b.priority);queue=queue.slice(0,30);pump();
    })().finally(()=>{request=null});return request;
  };
  function renderInbox(){
    const rows=mode==='history'?history:inboxNotifications;
    return `<p>Important events appear briefly beside the map. Routine captures are grouped by actor and two-minute activity window. Dismissed messages remain in recent history; the latest 500 events are retained.</p><div class="v4-row"><button class="btn ${mode==='unread'?'btn-primary':'btn-ghost'}" data-inbox-mode="unread">Unread</button><button class="btn ${mode==='history'?'btn-primary':'btn-ghost'}" data-inbox-mode="history">Recent history</button>${inboxNotifications.length?'<button class="btn btn-ghost" data-inbox-read-all>Mark all read</button>':''}</div><div id="notification-inbox">${grouped(rows).map(n=>`<article class="v4-card event-history priority-${n.priority||4}"><small>${n.is_read?'Read':'Unread'} · ${esc(n.created_at||'')}</small><p>${esc(text(n))}</p>${n.members.length>1?`<details><summary>View ${n.members.length} individual events</summary>${n.members.map(e=>`<p>${esc(e.message)}</p>`).join('')}</details>`:''}${n.type==='away_summary'&&n.data?.summary?`<p>${Object.entries(n.data.summary.resources||{}).map(([key,value])=>esc(key)+': +'+fmtN(value,1)).join(' · ')}</p>`:''}<div class="v4-row">${n.data?.grid_key?`<button class="btn btn-ghost" data-event-tile="${esc(n.data.grid_key)}">View tile</button>`:''}${['operations','battles','faction','trading','social'].includes(n.data?.panel)?`<button class="btn btn-ghost" data-event-panel="${n.data.panel}">Open ${esc(menuItems[n.data.panel]?.name||n.data.panel)}</button>`:''}${n.type==='war_declared'?'<button class="btn btn-ghost" data-war-assessment>War assessment</button>':''}${!n.is_read&&n.type==='alliance_invite'&&n.data?.alliance_id?`<button class="btn btn-primary" onclick="inboxAlliance(${n.id},true)">Accept alliance</button><button class="btn btn-ghost" onclick="inboxAlliance(${n.id},false)">Decline</button>`:!n.is_read?(n.data?.actions||[]).map((a,index)=>`<button class="btn btn-ghost" onclick="inboxAction(${n.id},${index})">${esc(a.label)}</button>`).join(''):''}${!n.is_read?`<button class="btn btn-ghost" data-event-read="${n.members.map(e=>e.id).join(',')}">Mark read</button>`:''}</div></article>`).join('')||'<p>No messages in this view.</p>'}</div>${mode==='history'&&nextBefore?'<button class="btn btn-ghost" data-inbox-more>Load older events</button>':''}`;
  }
  w.openNotificationInbox=async function(view='unread',append=false){
    if(!currentUser)return;const serial=++inboxRequest;mode=view;await pollNotifications();if(!currentUser||serial!==inboxRequest)return;const uid=currentUser.id,generation=sessionGeneration;
    if(mode==='history'){const r=await api('GET','/api/notifications/history'+(append&&nextBefore?'?before='+nextBefore:''));if(serial!==inboxRequest||generation!==sessionGeneration||currentUser?.id!==uid)return;if(r.error)return toast(r.error,'error');history=append?history.concat(r.events):r.events;nextBefore=r.next_before}
    openCommunityDialog('Notifications & activity',renderInbox());
  };
  dismissInboxNotifications=async function(id){const r=await api('POST',id===undefined?'/api/notifications/dismiss_all':'/api/notifications/dismiss',id===undefined?{}:{id});if(r.error)return toast(r.error,'error');await w.openNotificationInbox(mode)};
  function ensureActionEvent(id){const event=inboxNotifications.find(n=>n.id===id)||history.find(n=>n.id===id);if(event&&!inboxNotifications.some(n=>n.id===id))inboxNotifications.push(event);return event}
  const alliance=inboxAlliance;inboxAlliance=async function(id,accept){if(!ensureActionEvent(id))return;return alliance(id,accept)};
  const action=inboxAction;inboxAction=async function(id,index){const entry=ensureActionEvent(id)?.data?.actions?.[index];if(!entry)return;
    if(!['/api/trade/respond','/api/loan/respond','/api/faction/rel/respond','/api/merge/respond'].includes(entry.path))return toast('This action is no longer supported. Open its game menu.','error');
    if(entry.path==='/api/merge/respond'&&entry.body?.accept&&!confirm('Merge your account into the other country? Your current login and country will be absorbed. This cannot be undone through the game.'))return;
    return action(id,index);
  };
  doc.addEventListener('click',async event=>{
    const target=event.target.closest('button');if(!target)return;
    if(target.dataset.inboxMode)return w.openNotificationInbox(target.dataset.inboxMode);
    if(target.hasAttribute('data-inbox-more'))return w.openNotificationInbox('history',true);
    if(target.hasAttribute('data-inbox-read-all'))return dismissInboxNotifications();
    if(target.dataset.eventRead){target.disabled=true;for(const id of target.dataset.eventRead.split(',').map(Number)){const r=await api('POST','/api/notifications/dismiss',{id});if(r.error){target.disabled=false;return toast(r.error,'error')}}return w.openNotificationInbox(mode)}
    if(target.dataset.eventPanel){closeCommunityDialog();return openExpansionPanel(target.dataset.eventPanel)}
    if(target.hasAttribute('data-war-assessment')){closeCommunityDialog();const result=await api('GET','/api/wars/unseen');if(result.error)return toast(result.error,'error');if(!result.wars?.length)return toast('No unreviewed active wars. Open Faction to review diplomacy.');return showWarAlert()}
    if(target.dataset.eventTile){const key=target.dataset.eventTile;if(!/^(?:-?\d+,-?\d+|island:[\w-]+)$/.test(key))return toast('Tile unavailable','error');closeCommunityDialog();flyTo(key);return inspectIsland(key)}
  });
  const stop=stopPolling;stopPolling=function(){reset();stop()};
  doc.addEventListener('visibilitychange',()=>{if(!doc.hidden)pump()});
  w.WCPlayerEvents={grouped,text};
})(window);
