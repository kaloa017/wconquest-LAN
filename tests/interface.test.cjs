/* In-memory DOM checks. No server, browser connection, remote script or map requests. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const ui = require('../static/interface.js');
const source = fs.readFileSync(path.join(__dirname, '../static/interface.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '../static/interface.css'), 'utf8');
const mapModel=require('../static/map-performance.js');
const polish=require('../static/game-polish.js');
const pause = () => new Promise(resolve => setTimeout(resolve, 15));
function productionDOM(t,options={}) {
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const dom=new JSDOM(html,{runScripts:'outside-only',url:'https://offline.invalid/'});t.after(()=>dom.window.close());const w=dom.window;
  w.fetch=options.fetch||(()=>new Promise(()=>{}));w.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});w.Audio=function(){this.play=async()=>{};this.pause=()=>{};this.load=()=>{};this.removeAttribute=()=>{}};w.confirm=()=>false;
  if(options.canvas){
    w.CanvasRenderingContext2D=function(){};
    w.HTMLCanvasElement.prototype.getContext=function(){return new Proxy({canvas:this,measureText:()=>({width:80}),getLineDash:()=>[]},{get:(target,key)=>key in target?target[key]:()=>{}})};
    Object.defineProperty(w.HTMLElement.prototype,'clientWidth',{configurable:true,get(){return this.id==='map'?1000:800}});
    Object.defineProperty(w.HTMLElement.prototype,'clientHeight',{configurable:true,get(){return 600}});
    w.requestAnimationFrame=cb=>w.setTimeout(()=>cb(Date.now()),1);w.cancelAnimationFrame=id=>w.clearTimeout(id);
  }
  for(const script of w.document.querySelectorAll('script[src]')){
    const file=path.join(__dirname,'..',script.getAttribute('src'));
    vm.runInContext(fs.readFileSync(file,'utf8'),dom.getInternalVMContext(),{filename:file});
  }
  return {w,dom};
}

function fixture(t, options={}) {
  const ids=Object.keys(ui.routes);
  const dom=new JSDOM(`<!doctype html><html><head><style>${css}</style></head><body>
    <div id="sidebar"><div class="scroll-controls"><button>←</button><div class="sidebar-tabs">${ids.map(id=>`<button class="stab ${id==='territory'?'active':''}" id="nav-${id}" data-panel="${id}">${id}</button>`).join('')}</div><button>→</button></div>
    ${ids.map(id=>`<section class="panel-content ${id==='territory'?'active':''}" id="panel-${id}"><div id="${id}-content"></div></section>`).join('')}</div>
    <div id="mobile-sheet"><h2 id="sheet-title">Menu</h2><div id="mobile-sheet-content"></div></div>
    <div id="profile-modal" class="modal-overlay"><div class="modal-box"><h2>Settings</h2><div class="modal-body"><div id="settings-content"></div><details class="account-details"><summary>Account</summary><input id="password" type="password"></details></div></div></div>
    </body></html>`, {runScripts:'outside-only',url:'https://offline.invalid/'});
  t.after(()=>dom.window.close());
  const w=dom.window;w.currentUser=options.user===undefined?{id:1,is_admin:1}:options.user;w.sessionGeneration=1;
  w.menuItems=Object.fromEntries(ids.map(id=>[id,{icon:'•',name:id,desc:id}]));
  w.PANELS=Object.fromEntries(ids.map(id=>[id,{f:()=>{}}]));
  w.showPanel=id=>{for(const p of w.document.querySelectorAll('.panel-content'))p.classList.toggle('active',p.id==='panel-'+id);w.PANELS[id]?.f()};
  w.mobileNav=(tab,panel)=>{const sheet=w.document.getElementById('mobile-sheet');sheet.classList.toggle('open',tab!=='map');if(tab==='more'&&!panel)w.document.getElementById('mobile-sheet-content').innerHTML=w.menuHome()};
  w.openExpansionPanel=id=>w.showPanel(id);w.refreshUser=async()=>{};w.stopPolling=()=>{};w.toast=()=>{};
  w.api=options.api|| (async()=>({success:true,message:'Saved'}));
  w.buildSettings=()=>{w.document.getElementById('settings-content').innerHTML='<section><h3>Map & faction sharing</h3><input id="sharing"></section><section><h3>Shared music</h3><input id="volume"></section><section><h3>Account recovery</h3><input id="recovery"></section><section><h3>Two-factor authentication</h3><button>Manage security</button></section>'};
  for(const button of w.document.querySelectorAll('[data-panel]'))button.onclick=()=>w.showPanel(button.dataset.panel);
  w.eval(source);return w;
}

test('one complete route inventory with explicit role restrictions',()=>{
  assert.equal(Object.keys(ui.routes).length,19);
  assert.equal(new Set(ui.groups.flatMap(g=>g.routes)).size,19);
  assert.equal(ui.canVisit('catalog',{is_moderator:1}),false);
  assert.equal(ui.canVisit('moderation',{is_moderator:1}),true);
  assert.equal(ui.canVisit('catalog',{is_admin:1}),true);
  assert.equal(ui.canVisit('trading',null),false);
  assert.equal(ui.canVisit('territory',null),true);
  assert.equal(ui.visibleGroups(null).some(g=>g.id==='host'),false);
  assert.deepEqual(ui.visibleGroups({id:1},undefined,'loan').flatMap(g=>g.routes),['banks']);
});

test('ownership canvas merges same-owner cells while keeping borders and viewport boundaries',()=>{
  const tiles={};for(let a=0;a<100;a++)for(let b=0;b<100;b++)tiles[`${a},${b}`]={grid_key:`${a},${b}`,owner_id:1,color:'#abcdef'};
  tiles['island:test']={grid_key:'island:test',owner_id:1};
  const runs=mapModel.runs(tiles);assert.equal(runs.length,100);
  assert.equal(runs.reduce((count,row)=>count+row.end-row.b+1,0),10000);
  assert.equal(mapModel.visible(runs[0],{north:2,south:0,east:2,west:0},.18),true);
  assert.equal(mapModel.visible(runs[0],{north:20,south:19,east:2,west:0},.18),false);
  tiles['0,50'].owner_id=2;assert.equal(mapModel.runs(tiles).length,102);
});

test('all fields have visible associated labels without duplicates',t=>{
  const w=fixture(t),doc=w.document,scope=doc.getElementById('catalog-content');
  scope.innerHTML='<input id="amount" type="number" placeholder="Amount"><label>Reason<textarea id="reason"></textarea></label><select id="choice" aria-label="Choose a player"><option>A</option></select>';
  w.WCInterface.runtime.enhance();w.WCInterface.runtime.enhance();
  for(const input of scope.querySelectorAll('input,textarea,select'))assert.equal(input.labels.length,1,input.id);
  assert.equal(scope.querySelectorAll('label[for="amount"]').length,1);
});

test('map animation mutations do not schedule a whole-interface scan',async t=>{
  const w=fixture(t),map=w.document.createElement('div');map.id='map';w.document.body.appendChild(map);await pause();await pause();
  assert.equal(w.WCInterface.runtime.state.queued,false);
  map.className='leaflet-zoom-anim';map.appendChild(w.document.createElement('canvas'));
  await Promise.resolve();await Promise.resolve();
  assert.equal(w.WCInterface.runtime.state.queued,false);
  const input=w.document.createElement('input');input.id='normal-form-field';w.document.getElementById('catalog-content').appendChild(input);
  await pause();assert.equal(input.labels.length,1);
});

test('desktop direct menus, search and roving keyboard focus',t=>{
  const w=fixture(t),doc=w.document;
  assert.equal(doc.querySelector('.scroll-controls'),null);
  assert.equal(doc.getElementById('ui-menu-picker'),null);
  assert.equal(doc.getElementById('ui-nav-group'),null);
  const visible=[...doc.querySelectorAll('.stab')].filter(b=>!b.hidden);
  assert.deepEqual(visible.map(b=>b.dataset.panel),Object.keys(ui.routes));
  visible[0].focus();visible[0].dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert.equal(doc.activeElement,visible[1]);
  const search=doc.getElementById('ui-nav-search');search.value='loan';search.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.deepEqual([...doc.querySelectorAll('.stab')].filter(b=>!b.hidden).map(b=>b.dataset.panel),['banks']);
});

test('email sign-in challenge stays inside the form and never starts an unverified session',async t=>{
  const {w}=productionDOM(t);
  assert.ok(w.document.querySelector('#form-login #li-email-code'));
  assert.ok(w.document.querySelector('#form-register #rg-email'));
  let started=0,calls=[];w.startGame=async()=>started++;
  w.api=async(method,path,data)=>{calls.push({path,data});return {email_required:true,message:'Code queued',retry_after:60}};
  w.document.getElementById('li-user').value='Example';w.document.getElementById('li-pass').value='disposable-password';
  await w.doLogin();assert.equal(started,0);assert.equal(w.document.getElementById('li-email-code').parentElement.parentElement.hidden,false);
  assert.equal(w.document.getElementById('resend-login-code').disabled,true);
  assert.equal(calls[0].data.resend_email,false);
  w.api=async()=>({success:true,user:{id:99,username:'Example'}});w.document.getElementById('li-email-code').value='12345678';
  await w.doLogin();assert.equal(started,1);assert.equal(w.document.getElementById('li-email-code').value,'');
});

test('tile finder parses grid IDs, island IDs and geographic coordinates',()=>{
  const cell=polish.parseTileTarget('200, 100');assert.equal(cell.key,'200,100');assert.ok(Math.abs(cell.lat-36.09)<1e-8);
  assert.equal(polish.parseTileTarget('59.91, 10.75','latlng').key,'332,59');
  assert.equal(polish.parseTileTarget('-0.01 -0.01','latlng').key,'-1,-1');
  assert.equal(polish.parseTileTarget('island:sample-1').key,'island:sample-1');
  for(const [value,mode] of [['Infinity,2','grid'],['200.2,2','grid'],['500,1','grid'],['91,0','latlng'],['0,180','latlng']])assert.throws(()=>polish.parseTileTarget(value,mode));
});

test('action quantities and searches never create discard controls, editors still do',async t=>{
  const w=fixture(t),doc=w.document;
  const scope=doc.getElementById('panel-market');scope.insertAdjacentHTML('beforeend','<input id="sell-quantity" value="1"><button id="sell-action">Sell</button>');w.WCInterface.runtime.enhance();
  const input=doc.getElementById('sell-quantity');input.focus();input.value='20';input.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.equal(scope.querySelector('.ui-draft-status'),null);
  doc.getElementById('sell-action').click();await w.api('POST','/api/resources/sell',{});await pause();
  assert.equal(scope.querySelector('.ui-draft-status'),null);
  const editor=doc.getElementById('panel-catalog');editor.insertAdjacentHTML('beforeend','<input id="real-editor" value="Old">');w.WCInterface.runtime.enhance();
  const field=doc.getElementById('real-editor');field.focus();field.value='New';field.dispatchEvent(new w.Event('input',{bubbles:true}));assert.ok(editor.querySelector('.ui-draft-status'));
});

test('mobile menu uses the same role-filtered routes and searches locally',t=>{
  const w=fixture(t,{user:{id:1}}),doc=w.document;w.mobileNav('more');
  assert.equal(doc.querySelector('[data-ui-route="catalog"]'),null);
  assert.equal(doc.querySelector('.ui-menu-group'),null);
  const input=doc.getElementById('ui-mobile-search');input.value='stock';input.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.deepEqual([...doc.querySelectorAll('[data-ui-route]')].filter(b=>!b.hidden).map(b=>b.dataset.uiRoute),['stocks']);
});

test('mobile menu navigation also protects unsaved edits',t=>{
  const w=fixture(t),doc=w.document;w.mobileNav('more','catalog');
  const panel=doc.getElementById('panel-catalog');panel.insertAdjacentHTML('beforeend','<input id="mobile-draft" value="Old">');w.WCInterface.runtime.enhance();
  const input=doc.getElementById('mobile-draft');input.focus();input.value='New';input.dispatchEvent(new w.Event('input',{bubbles:true}));
  w.mobileNav('map');assert.ok(doc.getElementById('ui-leave-dialog'));
  doc.querySelector('[data-choice="keep"]').click();assert.equal(doc.getElementById('mobile-sheet').classList.contains('open'),false);assert.equal(input.value,'New');
});

test('drafts require a leave choice and survive returning to the screen',async t=>{
  const w=fixture(t),doc=w.document;w.showPanel('catalog');
  const scope=doc.getElementById('panel-catalog');scope.insertAdjacentHTML('beforeend','<input id="draft-name" value="Original">');w.WCInterface.runtime.enhance();
  const input=doc.getElementById('draft-name');input.focus();input.value='Changed';input.dispatchEvent(new w.Event('input',{bubbles:true}));
  w.showPanel('banks');assert.ok(doc.getElementById('ui-leave-dialog'));assert.ok(scope.classList.contains('active'));
  doc.querySelector('[data-choice="keep"]').click();assert.ok(doc.getElementById('panel-banks').classList.contains('active'));
  w.showPanel('catalog');assert.equal(input.value,'Changed');
  w.showPanel('banks');doc.querySelector('[data-choice="discard"]').click();assert.equal(input.value,'Original');
  await pause();
});

test('identical pending mutations make one request and expose a busy button',async t=>{
  let resolve,calls=0;const w=fixture(t,{api:()=>{calls++;return new Promise(r=>resolve=r)}}),doc=w.document;
  const scope=doc.getElementById('catalog-content');scope.innerHTML='<button id="save">Save changes</button>';w.WCInterface.runtime.enhance();const button=doc.getElementById('save');button.click();
  const first=w.api('POST','/api/admin/catalog',{name:'A'}),second=w.api('POST','/api/admin/catalog',{name:'A'});
  assert.equal(calls,1);assert.equal(button.disabled,true);assert.equal(button.getAttribute('aria-busy'),'true');
  resolve({success:true,message:'Definition saved'});await Promise.all([first,second]);
  assert.equal(button.disabled,false);assert.equal(button.hasAttribute('aria-busy'),false);assert.match(doc.querySelector('.ui-feedback').textContent,/Definition saved/);
});

test('late failures keep newer edits without restoring obsolete feedback',async t=>{
  let resolve;const w=fixture(t,{api:()=>new Promise(r=>resolve=r)}),doc=w.document;
  const scope=doc.getElementById('panel-catalog');scope.insertAdjacentHTML('beforeend','<input id="draft" value="First"><button id="save">Save</button>');w.WCInterface.runtime.enhance();
  doc.getElementById('save').click();const pending=w.api('POST','/api/admin/catalog',{});const input=doc.getElementById('draft');input.value='Newer draft';input.dispatchEvent(new w.Event('input',{bubbles:true}));
  resolve({error:'Connection interrupted'});await pending;await pause();assert.equal(input.value,'Newer draft');assert.equal(scope.querySelector('[role="alert"]'),null);
});

test('settings are grouped and the account controls remain accessible',t=>{
  const w=fixture(t),doc=w.document;w.buildSettings();
  assert.ok(doc.querySelector('#ui-settings-account #recovery'));assert.ok(doc.querySelector('#ui-settings-account #password'));
  const account=doc.getElementById('ui-settings-account-tab');account.click();assert.equal(doc.getElementById('ui-settings-account').hidden,false);
  account.focus();account.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Home',bubbles:true}));assert.equal(doc.getElementById('ui-settings-appearance-tab').getAttribute('aria-selected'),'true');
  w.buildSettings();assert.ok(doc.querySelector('#ui-settings-account #password'),'account controls survive preferences refresh');
});

test('failed redraw restores the last entered values rather than renderer defaults',async t=>{
  let resolve;const w=fixture(t,{api:()=>new Promise(r=>resolve=r)}),doc=w.document;
  const scope=doc.getElementById('panel-catalog');scope.insertAdjacentHTML('beforeend','<input id="redraw-draft" value="Draft"><button id="redraw-save">Save</button>');w.WCInterface.runtime.enhance();
  doc.getElementById('redraw-save').click();const pending=w.api('POST','/api/admin/catalog',{});resolve({error:'Please retry'});await pending;
  scope.querySelector('#redraw-draft').remove();scope.insertAdjacentHTML('beforeend','<input id="redraw-draft" value="Wrong default">');await pause();assert.equal(doc.getElementById('redraw-draft').value,'Draft');
});

test('locked inactivity dialogs stay above an open settings dialog',t=>{
  const w=fixture(t),doc=w.document;doc.getElementById('profile-modal').classList.add('open');
  const pause=doc.createElement('div');pause.id='activity-paused';pause.className='activity-overlay';pause.innerHTML='<section class="v6-dialog"><h2>Still playing?</h2><button>Keep playing</button></section>';doc.body.appendChild(pause);w.WCInterface.runtime.enhance();
  const button=pause.querySelector('button');button.focus();button.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));assert.equal(doc.activeElement,button);
  button.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));assert.ok(pause.isConnected);
});

test('top dialog traps focus and Escape closes only that dialog',t=>{
  const w=fixture(t),doc=w.document,trigger=doc.getElementById('nav-territory');trigger.focus();
  const first=doc.createElement('div');first.className='v6-overlay';first.innerHTML='<section class="v6-dialog"><h2>First dialog</h2><button>First action</button></section>';doc.body.appendChild(first);w.WCInterface.runtime.enhance();
  const second=doc.createElement('div');second.className='v6-overlay';second.innerHTML='<section class="v6-dialog"><h2>Second dialog</h2><button>Action</button><button data-close>Close</button></section>';second.querySelector('[data-close]').onclick=()=>second.remove();doc.body.appendChild(second);w.WCInterface.runtime.enhance();
  const buttons=second.querySelectorAll('button');buttons[1].focus();buttons[1].dispatchEvent(new w.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));assert.equal(doc.activeElement,buttons[0]);
  buttons[0].dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));assert.equal(second.isConnected,false);assert.equal(first.isConnected,true);
});

test('recovery acknowledgement cannot be escaped',t=>{
  const w=fixture(t),doc=w.document,dialog=doc.createElement('div');dialog.className='v6-overlay';dialog.dataset.requiresAcknowledgement='true';dialog.innerHTML='<section class="v6-dialog"><h2>Save recovery code</h2><button data-close>Saved</button></section>';dialog.querySelector('button').onclick=()=>dialog.remove();doc.body.appendChild(dialog);w.WCInterface.runtime.enhance();
  dialog.querySelector('button').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));assert.equal(dialog.isConnected,true);
});

test('numeric validation rejects invalid quantities with field-specific help',()=>{
  assert.equal(ui.validateValue({type:'number',value:'-1',min:'0',max:'10',step:'1'}),'Use 0 or more.');
  assert.equal(ui.validateValue({type:'number',value:'1.5',min:'0',max:'10',step:'1'}),'Use increments of 1.');
  assert.equal(ui.validateValue({type:'text',value:'',required:true}),'Complete this field.');
  assert.equal(ui.validateValue({type:'number',value:'2',min:'0',max:'10',step:'1'}),'');
});

test('HTML uses semantic authentication forms and local interface assets',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8'),dom=new JSDOM(html),doc=dom.window.document;
  for(const id of ['form-login','form-register','form-forgot']){assert.equal(doc.getElementById(id).tagName,'FORM');assert.ok(doc.getElementById(id).querySelector('button[type="submit"]'))}
  assert.equal(doc.getElementById('rg-pin').type,'hidden');assert.ok(doc.querySelector('a[href="#main"]'));assert.ok(doc.querySelector('script[src="/static/interface.js"]'));assert.ok(doc.querySelector('link[href="/static/interface.css"]'));dom.window.close();
});

test('all production scripts initialize together in an offline DOM',async t=>{
  const {w}=productionDOM(t);
  assert.ok(w.document.getElementById('ui-navigation'));
  assert.ok(w.document.querySelector('#form-login #li-otp'));
  assert.equal(w.document.querySelectorAll('label[for="li-user"]').length,1);
  await pause();
});

test('island selection works without Turf, including holes and multipolygons',t=>{
  const {w,dom}=productionDOM(t);
  w.turf={};
  const square=[[0,0],[4,0],[4,4],[0,4],[0,0]],hole=[[1,1],[3,1],[3,3],[1,3],[1,1]];
  const island={properties:{key:'island:test'},geometry:{type:'Polygon',coordinates:[square,hole]}};
  assert.equal(w.islandContainsPoint(island,.5,.5),true);
  assert.equal(w.islandContainsPoint(island,2,2),false);
  assert.equal(w.islandContainsPoint(island,2,1),true);
  assert.equal(w.islandContainsPoint(island,2,0),true);
  assert.equal(w.islandContainsPoint(island,4,4),true);
  assert.equal(w.islandContainsPoint(island,4.1,4),false);
  const multi={...island,geometry:{type:'MultiPolygon',coordinates:[[square,hole],[[[6,0],[7,0],[7,1],[6,1],[6,0]]]]}};
  assert.equal(w.islandContainsPoint(multi,.5,6.5),true);
  assert.equal(w.islandContainsPoint(multi,.5,5.5),false);
  w.__island=island;
  vm.runInContext('islandBuckets.set("0,0",[__island])',dom.getInternalVMContext());
  assert.equal(w.islandAt(.5,.5).properties.key,'island:test');
  assert.equal(w.islandAt(2,2),undefined);
  island.properties.grid_tiles=['0,0'];
  assert.equal(w.islandAt(.5,.5),undefined);
  vm.runInContext('territories["island:test"]={owner_id:1}',dom.getInternalVMContext());
  assert.equal(w.islandAt(.5,.5).properties.key,'island:test');
});

test('major feature renderers use real API-shaped fixtures without network access',async t=>{
  const {w,dom}=productionDOM(t);
  const generated=spawnSync('python',['-X','utf8',path.join(__dirname,'ui_fixtures.py')],{encoding:'utf8',timeout:60000});
  assert.equal(generated.status,0,generated.stderr);const fixtures=JSON.parse(generated.stdout);
  w.__fixture=fixtures;
  vm.runInContext('currentUser=__fixture["/api/me"];gameConfig=__fixture["/api/bootstrap"];BLD=__fixture["/api/buildings"];Object.assign(RESEARCH_TREE,__fixture["/api/research"].tree);territories=Object.fromEntries(__fixture["/api/territories"].map(t=>[t.grid_key,t]));',dom.getInternalVMContext());
  w.api=async(method,url)=>structuredClone(fixtures[url.split('?')[0]]??{error:'No offline fixture for '+url});
  w.WCInterface.runtime.updateNavigation();
  for(const name of ['buildResearch','buildOperations','buildTrading','buildBanks','buildCatalogEditor','loadLeaderboard','buildSettings','buildModeration','buildSpace','buildServerDashboard','buildAdminAccounts','buildGuestAnalytics','buildStatistics','buildEmpire','buildMarket','buildStocks','buildFaction','buildChat','buildQuests','loadBattleLog','buildPlaytime','buildAdminEmail','buildIpRestrictions']){
    await assert.doesNotReject(async()=>w[name](),name);w.WCInterface.runtime.enhance();
  }
  assert.ok(w.document.querySelector('#research-content .research-branch'));
  assert.ok(w.document.querySelector('#catalog-content #catalog-fields'));
  assert.ok(w.document.querySelector('#moderation-content #moderate-player'));
  assert.ok(w.document.querySelector('#chat-filter-settings'));
  assert.ok(w.document.querySelector('#research-filters'));
  const search=w.document.getElementById('research-search');search.value='Fusion Propulsion';search.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.equal([...w.document.querySelectorAll('.focus-node')].filter(node=>!node.hidden).length,4);
  assert.ok([...w.document.querySelectorAll('.focus-node')].filter(node=>!node.hidden).every(node=>node.textContent.includes('Fusion Propulsion')));
  assert.ok(w.document.querySelector('#settings-content .ui-settings-tabs'));
  assert.ok(w.document.querySelector('#space-content').textContent.length>50);
  assert.ok(w.document.querySelector('#server-health .server-metrics'));
  assert.ok(w.document.querySelector('#admin-account-search'));
  assert.ok(w.document.querySelector('#public-player-presence time'));
  vm.runInContext('currentUser={...currentUser,territory_count:0,building_counts:{},research:[]}',dom.getInternalVMContext());
  await vm.runInContext('PANELS.empire.f()',dom.getInternalVMContext());
  assert.ok(w.document.querySelector('#country-first-steps'),'Country navigation uses the final objectives renderer');
  assert.ok(w.document.querySelector('#capital-development'),'Country navigation includes real capital development status');
  assert.equal(w.document.querySelectorAll('[data-daily-choice]').length,2,'Daily reward offers both server-backed choices');
  assert.ok(w.document.querySelector('#guest-analytics-retention'));
  assert.equal(w.document.querySelectorAll('#guest-analytics-traffic').length,1,'Crawler filter belongs only to guest analytics');
  await Promise.all([w.buildServerDashboard(),w.buildServerDashboard()]);
  assert.equal([...w.document.querySelectorAll('#admin-server h3')].filter(e=>e.textContent==='Administration').length,1,'Concurrent dashboard renders do not duplicate cards');
  assert.equal(w.document.querySelector('.admin-group-tabs'),null);
  assert.equal(w.document.querySelector('.admin-tabs').hidden,false);
  assert.equal(w.document.querySelector('#admin-tool-select'),null);
  await assert.doesNotReject(()=>w.inspectAdminAccount(fixtures['/api/me'].id));
  assert.ok(w.document.querySelector('#dashboard-account-role'));
  assert.ok(w.document.querySelector('#dashboard-account-research option'));
  await assert.doesNotReject(()=>w.reviewAccountDeletion(fixtures['/api/admin/account/delete-preview'].user_id));
  assert.ok(w.document.querySelector('#delete-account-name'));
  assert.ok(w.document.querySelector('#account-delete-review').textContent.includes('without repayment'));
  const calls=[];w.act=async(path,data)=>{calls.push({path,data});return {error:'Stop test'}};
  w.document.getElementById('delete-account-name').value='wrong name';await w.confirmAccountDeletion();assert.equal(calls.length,0);
  const before=w.document.getElementById('admin-server').textContent;vm.runInContext('currentUser=null',dom.getInternalVMContext());
  await w.buildServerDashboard();assert.equal(w.document.getElementById('admin-server').textContent,before);
});

test('away summary is claimed before display and survives refresh without another popup',async t=>{
  const {w,dom}=productionDOM(t);Object.defineProperty(w.document,'hidden',{configurable:true,value:false});
  vm.runInContext('currentUser={id:55};',dom.getInternalVMContext());
  let claims=0,accepted=false;const summary={since:123,resources:{money:12}};
  w.api=async(method,path)=>{if(path==='/api/away')return {summary};if(path==='/api/away/claim'){claims++;if(accepted)return {summary:null};accepted=true;return {summary}}return {wars:[]}};
  await Promise.all([w.showReturnSummary(),w.showReturnSummary()]);assert.equal(w.document.querySelectorAll('#away-ack').length,1);
  assert.equal(claims,1);w.document.getElementById('expansion-dialog').remove();
  await w.showReturnSummary();assert.equal(w.document.getElementById('away-ack'),null);assert.equal(claims,2);
});

test('player events aggregate only one actor and keep critical events separate',t=>{
  const {w}=productionDOM(t),base={type:'territory_lost',priority:2,created_at:'2026-10-22 10:00:01',data:{actor_id:1,actor_name:'One'}};
  const grouped=w.WCPlayerEvents.grouped([{...base,id:1},{...base,id:2},{...base,id:3,data:{actor_id:2,actor_name:'Two'}},{...base,id:4,type:'capital_lost',priority:1}]);
  assert.equal(grouped.length,3);assert.equal(grouped[0].type,'capital_lost');assert.equal(grouped[1].members.length,2);assert.match(w.WCPlayerEvents.text(grouped[1]),/One captured 2/);
  assert.equal(w.WCPlayerEvents.grouped([{...base,id:1,is_read:1},{...base,id:2,is_read:0}])[0].is_read,0,'Mixed groups remain unread');
});

test('notifications use server presentation claims, limit visible cards and escape content',async t=>{
  const {w,dom}=productionDOM(t);Object.defineProperty(w.document,'hidden',{configurable:true,value:false});vm.runInContext('currentUser={id:99}',dom.getInternalVMContext());let presented=false;
  const events=[1,2,3,4].map(id=>({id,type:'war_declared',message:'<img src=x onerror=alert(1)>',priority:1,presented_at:0,created_at:'2026-10-22 10:00:00',data:{}}));
  w.api=async(method,url)=>url==='/api/notifications'?events:url==='/api/notifications/present'?{events:presented?[]:(presented=true,events)}:{events:[],next_before:null};
  await w.pollNotifications();assert.equal(w.document.querySelectorAll('.player-event-toast').length,2);assert.equal(w.document.querySelectorAll('.player-event-toast img').length,0);
  await w.pollNotifications();assert.equal(w.document.querySelectorAll('.player-event-toast').length,2);
  await w.openNotificationInbox('history');assert.match(w.document.getElementById('v6-dialog').textContent,/Recent history/);
});

test('detailed tutorial has working topic navigation and keyboard access',t=>{
  const {w}=productionDOM(t);w.showTutorial(0);const select=w.document.querySelector('[aria-label="Tutorial topic"]');assert.ok(select.options.length>=20);
  const capital=[...select.options].find(o=>o.textContent.includes('Develop your capital'));select.value=capital.value;select.dispatchEvent(new w.Event('change',{bubbles:true}));assert.match(w.document.getElementById('tutorial-title').textContent,/capital/);
  const next=w.document.getElementById('tutorial-next');next.focus();next.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));assert.equal(w.document.activeElement.tagName,'SELECT');
});

test('release notes wait for inactivity confirmation instead of stacking dialogs',t=>{
  const {w,dom}=productionDOM(t);vm.runInContext('currentUser={id:45}',dom.getInternalVMContext());
  w.requestAnimationFrame=cb=>w.setTimeout(cb,0);
  const paused=w.document.createElement('div');paused.id='activity-paused';w.document.body.appendChild(paused);
  w.showTextModal('What changed — test','Test release');assert.equal(w.document.getElementById('v6-dialog'),null);
  w.clearActivityPause();assert.match(w.document.getElementById('v6-dialog').textContent,/Test release/);
});

test('axe checks navigation, settings and auth semantics in offline DOMs',async t=>{
  const axeSource=fs.readFileSync(require.resolve('axe-core/axe.min.js'),'utf8');
  const {w}=productionDOM(t);w.eval(axeSource);
  for(const id of ['ui-navigation','auth-box']){
    const result=await w.axe.run(w.document.getElementById(id),{runOnly:{type:'tag',values:['wcag2a','wcag2aa']},rules:{'color-contrast':{enabled:false}}});
    assert.equal(result.violations.length,0,id+': '+JSON.stringify(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))));
  }
  const settings=fixture(t);settings.buildSettings();settings.document.getElementById('profile-modal').classList.add('open');settings.WCInterface.runtime.enhance();settings.eval(axeSource);
  const result=await settings.axe.run(settings.document.getElementById('settings-content'),{runOnly:{type:'tag',values:['wcag2a','wcag2aa']},rules:{'color-contrast':{enabled:false}}});
  assert.equal(result.violations.length,0,JSON.stringify(result.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))));
});

test('shared foreground colors meet WCAG AA against shared surfaces',()=>{
  const luminance=hex=>{const rgb=hex.slice(1).match(/../g).map(s=>parseInt(s,16)/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722};
  for(const sheet of [css,fs.readFileSync(path.join(__dirname,'../static/product-ui.css'),'utf8')]){
    const color=name=>sheet.match(new RegExp('--'+name+':\\s*(#[0-9a-f]{6})','i'))[1];
    for(const foreground of ['text','text2','text3'])for(const background of ['bg','panel','panel2','panel3']){const a=luminance(color(foreground)),b=luminance(color(background));assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,foreground+' on '+background)}
  }
});

test('older map responses never undo newer ownership or a world reset',t=>{
  const {w,dom}=productionDOM(t);let renders=0;w.renderTerritories=()=>renders++;
  vm.runInContext('mapVersion="3:20";territories={"200,200":{owner_id:1,grid_key:"200,200"}};',dom.getInternalVMContext());
  w.applyTerritoryDelta({version:'3:19',reset:false,changed:[],removed:['200,200']});
  w.applyTerritoryDelta({version:'2:9999',reset:true,changed:[],removed:[]});
  assert.equal(vm.runInContext('territories["200,200"].owner_id',dom.getInternalVMContext()),1);assert.equal(renders,0);
  w.applyTerritoryDelta({version:'3:21',reset:false,changed:[{grid_key:'200,200',owner_id:2,base_color:'#123456'}],removed:[]});
  assert.equal(vm.runInContext('territories["200,200"].owner_id',dom.getInternalVMContext()),2);
  w.applyTerritoryDelta({version:'4:0',reset:true,changed:[],removed:[]});
  assert.equal(vm.runInContext('Object.keys(territories).length',dom.getInternalVMContext()),0);
});

test('display preferences persist locally and first-country goals use real progress',t=>{
  const {w}=productionDOM(t);w.WCProduct.setPreferences({effects:'reduced',motion:'off'});
  assert.equal(w.document.documentElement.dataset.effects,'reduced');assert.equal(w.document.documentElement.dataset.motion,'off');
  assert.equal(w.localStorage.getItem('wc-visual-effects'),'reduced');
  const steps=w.WCProduct.objectives({territory_count:1,building_counts:{farm:{count:1}},research:[]});
  assert.deepEqual(Array.from(steps,s=>s.done),[true,true,false]);
  w.showDisplayOptions();assert.equal(w.document.querySelector('[data-display-option=effects]').value,'reduced');
  const select=w.document.querySelector('[data-display-option=effects]');select.value='auto';select.dispatchEvent(new w.Event('change',{bubbles:true}));
  assert.equal(w.WCProduct.preferences().effects,'auto');
});

test('copying a recovery code does not acknowledge or close its safeguard',async t=>{
  const {w}=productionDOM(t);let copied='',ack=0;
  w.requestAnimationFrame=cb=>w.setTimeout(cb,0);
  Object.defineProperty(w.navigator,'clipboard',{configurable:true,value:{writeText:async value=>copied=value}});
  w.showTextModal('Save your one-time recovery code','disposable-code\n\nKeep it private.',()=>ack++,'I saved the code');
  const copy=[...w.document.querySelectorAll('#v6-dialog button')].find(b=>b.textContent==='Copy recovery code');assert.ok(copy);copy.click();await pause();
  assert.equal(copied,'disposable-code');assert.equal(ack,0);assert.ok(w.document.querySelector('#v6-dialog'));
});

test('city directory searches locally, escapes names and filters owned tiles',async t=>{
  let calls=0;
  const records=[{id:'1',name:'Oslo',country:'Norway',population:600000,national_capital:true,grid_key:'332,59',playable:true},{id:'2',name:'<Test City>',country:'Japan',population:300000,grid_key:'200,200',playable:true}];
  const {w,dom}=productionDOM(t,{fetch:async url=>{if(!url.startsWith('/api/cities'))return new Promise(()=>{});calls++;return {ok:true,json:async()=>({cities:records})}}});
  vm.runInContext('currentUser={id:77};territories={"332,59":{owner_id:77,owner:"Preview"}}',dom.getInternalVMContext());
  await w.showCityDirectory();assert.equal(calls,1);
  const search=w.document.getElementById('city-search'),results=w.document.getElementById('city-results');
  assert.match(results.textContent,/Oslo/);assert.match(results.innerHTML,/&lt;Test City&gt;/);
  search.value='Japan';search.dispatchEvent(new w.Event('input',{bubbles:true}));assert.doesNotMatch(results.textContent,/Oslo/);assert.match(results.textContent,/<Test City>/);
  search.value='';search.dispatchEvent(new w.Event('input',{bubbles:true}));const owned=w.document.getElementById('city-owned');owned.checked=true;owned.dispatchEvent(new w.Event('change',{bubbles:true}));assert.match(results.textContent,/Oslo/);assert.doesNotMatch(results.textContent,/<Test City>/);assert.equal(calls,1);
});

test('fallout skips unknown legacy islands and redraws when their geometry becomes available',async t=>{
  const {w,dom}=productionDOM(t);let rectangles=0,islands=0;
  w.L.layerGroup=()=>({addTo(map){this._map=map;return this}});
  w.L.rectangle=bounds=>{assert.ok(bounds.flat().every(Number.isFinite));rectangles++;return {addTo(){}}};
  w.L.geoJSON=()=>{islands++;return {addTo(){}}};
  vm.runInContext('map={removeLayer(){}};foLayer=null;pacificIslands={}',dom.getInternalVMContext());
  const keys=['1,2','island:legacy','broken','999999,4'];
  await w.drawFallout(keys);assert.equal(rectangles,1);assert.equal(islands,0);
  await w.drawFallout(keys);assert.equal(rectangles,1);
  vm.runInContext('pacificIslands["island:legacy"]={type:"Feature",properties:{},geometry:{type:"Polygon",coordinates:[]}}',dom.getInternalVMContext());
  await w.drawFallout(keys);assert.equal(islands,1);assert.equal(rectangles,2);
});

test('sync feedback observes existing requests and clears after a successful retry',async t=>{
  let failed=true,mapCalls=0;
  const fetch=async url=>({ok:true,status:200,json:async()=>{
    if(url==='/api/bootstrap')return {csrf:'fixture',ideologies:{},religions:{},faction_colors:[]};
    if(String(url).startsWith('/api/map/sync')){mapCalls++;return failed?{error:'Connection interrupted. Please try again.'}:{version:'1:1',changed:[],removed:[]}};
    return {banner:{enabled:false}};
  }});
  const {w}=productionDOM(t,{fetch});await w.api('GET','/api/map/sync');assert.equal(w.document.getElementById('product-sync-status').hidden,false);
  failed=false;await w.api('GET','/api/map/sync');assert.equal(w.document.getElementById('product-sync-status').hidden,true);assert.equal(mapCalls,2);
});

test('full guest map and signed-in startup complete with local terrain and API fixtures',async t=>{
  const fetched=[];
  let fixtures;
  if(process.env.WC_STARTUP_FIXTURES)fixtures=JSON.parse(fs.readFileSync(process.env.WC_STARTUP_FIXTURES,'utf8'));
  else {
    const generated=spawnSync('python',['-X','utf8',path.join(__dirname,'ui_fixtures.py')],{encoding:'utf8',timeout:60000});
    assert.equal(generated.status,0,generated.stderr);fixtures=JSON.parse(generated.stdout);
  }
  const fetch=async(url,options={})=>{
    const base=String(url).split('?')[0];
    fetched.push(base);
    if(base==='/api/terrain/cells')return {ok:true,arrayBuffer:async()=>{const data=fs.readFileSync(path.join(__dirname,'../data/land-cells.bin'));return data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength)}};
    if(base==='/api/islands')return {ok:true,json:async()=>JSON.parse(fs.readFileSync(path.join(__dirname,'../data/pacific-islands.geojson'),'utf8'))};
    if(base.startsWith('/static/map/'))return {ok:true,json:async()=>JSON.parse(fs.readFileSync(path.join(__dirname,'..',base),'utf8'))};
    const response=base==='/api/changelog'?{show:false}:base==='/api/away'?{}:base==='/api/wars/unseen'?{wars:[]}:base==='/api/strikes'?{events:[]}:options.method==='POST'?{success:true}:fixtures[base]??{};
    return {ok:true,status:200,json:async()=>structuredClone(response)};
  };
  const {w,dom}=productionDOM(t,{fetch,canvas:true});
  Object.defineProperty(w.document,'hidden',{configurable:true,value:false});
  const guestIntervals=[],realInterval=w.setInterval;
  w.setInterval=(fn,ms)=>{const id=realInterval(fn,ms);guestIntervals.push({fn,ms});return id};
  const failures=[];w.console.error=(...args)=>failures.push(args.map(a=>a?.stack||String(a)).join(' '));
  await w.startSpectatorMode();
  assert.equal(guestIntervals.filter(t=>t.ms===60000).length,1,'One guest refresh timer per minute');
  assert.equal(guestIntervals.filter(t=>t.ms===2000||t.ms===4000||t.ms===12000).length,0,'No rapid guest background polls: '+guestIntervals.filter(t=>t.ms===2000||t.ms===4000||t.ms===12000).map(t=>t.ms+': '+t.fn.toString()).join('\n'));
  const beforeRefresh=fetched.length;
  await guestIntervals.find(t=>t.ms===60000).fn();
  assert.deepEqual(fetched.slice(beforeRefresh).filter(p=>p.startsWith('/api/')),['/api/spectator/sync']);
  w.setInterval=realInterval;
  assert.equal(w.document.getElementById('game-screen').style.display,'flex',failures.join('\n'));
  assert.equal(w.document.getElementById('auth-overlay').style.display,'none',failures.join('\n'));
  await w.startGame(fixtures['/api/me']);
  assert.equal(w.document.getElementById('game-screen').style.display,'flex',failures.join('\n'));
  assert.equal(w.document.getElementById('auth-overlay').style.display,'none',failures.join('\n'));
  assert.deepEqual(failures,[]);
  await pause();
  assert.ok(w.document.querySelector('.ownership-canvas'));
  assert.equal(w.document.querySelector('.leaflet-world-overview-pane').style.zIndex,'210');
  assert.ok(w.document.querySelector('.ownership-canvas').parentElement.classList.contains('leaflet-overlay-pane'));
  assert.equal(vm.runInContext('Object.keys(tlayers).length',dom.getInternalVMContext()),0);
  assert.ok(w.WCMap.lastFrame);
  vm.runInContext('territories["200,200"].capital=true;renderTerritories();map.setZoom(3,{animate:false});drawCaps()',dom.getInternalVMContext());
  assert.ok(w.document.querySelector('.cap-star'),'Capital stars remain visible on the simplified map');
  assert.ok(w.document.querySelector('.map-tile-finder form'));
  const originalLoad=w.fetch;let regionRequests=0;
  w.fetch=async(...args)=>{if(String(args[0]).includes('/islands-'))regionRequests++;return originalLoad(...args);};
  const index=JSON.parse(fs.readFileSync(path.join(__dirname,'../static/map/manifest.json'),'utf8'));
  const region=Object.keys(index.regions)[0];
  await Promise.all([w.WCMap.loadRegion(region),w.WCMap.loadRegion(region)]);
  assert.equal(regionRequests,1);await w.WCMap.loadRegion(region);assert.equal(regionRequests,1);
  const unclaimed=fixtures['/api/territory/200,201'];
  assert.ok(unclaimed,'Real unclaimed-territory response is required');
  w.api=async(method,url)=>structuredClone(url==='/api/territory/200,201'?unclaimed:fixtures[url.split('?')[0]]??{});
  const finder=w.document.querySelector('.map-tile-finder');finder.querySelector('input').value='200,201';finder.querySelector('form').dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));await pause();
  assert.equal(vm.runInContext('selectedKey',dom.getInternalVMContext()),'200,201');
  vm.runInContext('selectedKey=null',dom.getInternalVMContext());
  const mapElement=w.document.getElementById('map');
  Object.defineProperty(mapElement,'offsetWidth',{get:()=>1000});
  Object.defineProperty(mapElement,'offsetHeight',{get:()=>600});
  mapElement.getBoundingClientRect=()=>({left:0,top:0,right:1000,bottom:600,width:1000,height:600});
  vm.runInContext('map.setView([200.5*GRID,201.5*GRID],8,{animate:false})',dom.getInternalVMContext());
  await pause();
  const canvas=mapElement.querySelector('canvas');
  assert.ok(canvas);
  // A broken tooltip used to abort background clicks before tile selection.
  w.hoverInfo=()=>{throw new Error('Optional hover information unavailable')};
  canvas.dispatchEvent(new w.MouseEvent('click',{bubbles:true,clientX:500,clientY:300}));
  await pause();
  assert.equal(vm.runInContext('selectedKey',dom.getInternalVMContext()),'200,201');
  assert.match(w.document.getElementById('territory-info').textContent,/Unclaimed/);
  assert.ok(w.document.querySelector('.claim-btn'));
  Object.defineProperty(w,'innerWidth',{configurable:true,value:600});
  canvas.dispatchEvent(new w.MouseEvent('click',{bubbles:true,clientX:500,clientY:300}));
  await pause();
  assert.ok(w.document.getElementById('mobile-sheet').classList.contains('open'));
  assert.match(w.document.getElementById('mobile-sheet-content').textContent,/Unclaimed/);
  assert.ok(w.document.querySelector('#mobile-sheet-content .claim-btn'));
  // Render failures must offer a recovery action instead of silently stopping.
  const render=w.buildTerritoryPanel;
  w.buildTerritoryPanel=()=>{throw new Error('Renderer unavailable')};
  await w.fetchAndBuildPanel('200,201');
  const retry=w.document.querySelector('#mobile-sheet-content button');
  assert.equal(retry.textContent,'Retry territory');
  w.buildTerritoryPanel=render;retry.click();await pause();
  assert.ok(w.document.querySelector('#mobile-sheet-content .claim-btn'));
  assert.equal(failures.length,1);assert.match(failures[0],/Territory panel failed:.*Renderer unavailable/s);
  vm.runInContext('stopPolling()',dom.getInternalVMContext());
});


test('old action errors cannot return after a newer successful action',async t=>{
  let resolve;const w=fixture(t,{api:()=>new Promise(r=>resolve=r)}),doc=w.document;
  const scope=doc.getElementById('panel-territory');scope.insertAdjacentHTML('beforeend','<button id="attack">Attack</button>');
  doc.getElementById('attack').click();const first=w.api('POST','/api/attack',{tile:'1,1'});
  resolve({error:'Cannot attack an ally'});await first;
  const second=w.api('POST','/api/claim',{tile:'2,2'});resolve({success:true,message:'Claimed'});await second;await pause();
  assert.doesNotMatch(scope.textContent,/Cannot attack an ally/);assert.match(scope.textContent,/Claimed/);
  scope.querySelector('[aria-label="Dismiss message"]').click();assert.equal(scope.querySelector('.ui-feedback'),null);
});

test('leaving a panel and editing a field clear obsolete action errors',async t=>{
  const w=fixture(t,{api:async()=>({error:'Cannot attack an ally'})}),doc=w.document;
  const scope=doc.getElementById('panel-territory');scope.insertAdjacentHTML('beforeend','<input id="target"><button id="attack">Attack</button>');
  doc.getElementById('attack').click();await w.api('POST','/api/attack',{});await pause();
  const input=doc.getElementById('target');input.value='2,2';input.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.equal(scope.querySelector('.ui-feedback'),null);
  doc.getElementById('attack').click();await w.api('POST','/api/attack',{});w.showPanel('banks');await pause();
  assert.equal(scope.querySelector('.ui-feedback'),null);
});
