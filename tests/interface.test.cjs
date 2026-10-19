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
const pause = () => new Promise(resolve => setTimeout(resolve, 15));
function productionDOM(t,options={}) {
  const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
  const dom=new JSDOM(html,{runScripts:'outside-only',url:'https://offline.invalid/'});t.after(()=>dom.window.close());const w=dom.window;
  w.fetch=options.fetch||(()=>new Promise(()=>{}));w.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});w.Audio=function(){this.play=async()=>{};this.pause=()=>{};this.load=()=>{};this.removeAttribute=()=>{}};w.confirm=()=>false;
  if(options.canvas){
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
  assert.equal(Object.keys(ui.routes).length,18);
  assert.equal(new Set(ui.groups.flatMap(g=>g.routes)).size,18);
  assert.equal(ui.canVisit('catalog',{is_moderator:1}),false);
  assert.equal(ui.canVisit('moderation',{is_moderator:1}),true);
  assert.equal(ui.canVisit('catalog',{is_admin:1}),true);
  assert.equal(ui.canVisit('trading',null),false);
  assert.equal(ui.canVisit('territory',null),true);
  assert.equal(ui.visibleGroups(null).some(g=>g.id==='host'),false);
  assert.deepEqual(ui.visibleGroups({id:1},undefined,'loan').flatMap(g=>g.routes),['banks']);
});

test('all fields have visible associated labels without duplicates',t=>{
  const w=fixture(t),doc=w.document,scope=doc.getElementById('catalog-content');
  scope.innerHTML='<input id="amount" type="number" placeholder="Amount"><label>Reason<textarea id="reason"></textarea></label><select id="choice" aria-label="Choose a player"><option>A</option></select>';
  w.WCInterface.runtime.enhance();w.WCInterface.runtime.enhance();
  for(const input of scope.querySelectorAll('input,textarea,select'))assert.equal(input.labels.length,1,input.id);
  assert.equal(scope.querySelectorAll('label[for="amount"]').length,1);
});

test('desktop grouping, search and roving keyboard focus',t=>{
  const w=fixture(t),doc=w.document;
  assert.equal(doc.querySelector('.scroll-controls'),null);
  const select=doc.getElementById('ui-nav-group');select.value='economy';select.dispatchEvent(new w.Event('change',{bubbles:true}));
  const visible=[...doc.querySelectorAll('.stab')].filter(b=>!b.hidden);
  assert.deepEqual(visible.map(b=>b.dataset.panel),['market','trading','banks','stocks']);
  visible[0].focus();visible[0].dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert.equal(doc.activeElement,visible[1]);
  const search=doc.getElementById('ui-nav-search');search.value='loan';search.dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.deepEqual([...doc.querySelectorAll('.stab')].filter(b=>!b.hidden).map(b=>b.dataset.panel),['banks']);
});

test('mobile menu uses the same role-filtered routes and searches locally',t=>{
  const w=fixture(t,{user:{id:1}}),doc=w.document;w.mobileNav('more');
  assert.equal(doc.querySelector('[data-ui-route="catalog"]'),null);
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

test('late failures keep newer edits and announce actionable errors',async t=>{
  let resolve;const w=fixture(t,{api:()=>new Promise(r=>resolve=r)}),doc=w.document;
  const scope=doc.getElementById('panel-catalog');scope.insertAdjacentHTML('beforeend','<input id="draft" value="First"><button id="save">Save</button>');w.WCInterface.runtime.enhance();
  doc.getElementById('save').click();const pending=w.api('POST','/api/admin/catalog',{});const input=doc.getElementById('draft');input.value='Newer draft';input.dispatchEvent(new w.Event('input',{bubbles:true}));
  resolve({error:'Connection interrupted'});await pending;await pause();assert.equal(input.value,'Newer draft');assert.match(scope.querySelector('[role="alert"]').textContent,/input is kept/);
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
  for(const name of ['buildResearch','buildOperations','buildTrading','buildBanks','buildCatalogEditor','loadLeaderboard','buildSettings','buildModeration','buildSpace']){
    await assert.doesNotReject(async()=>w[name](),name);w.WCInterface.runtime.enhance();
  }
  assert.ok(w.document.querySelector('#research-content .research-branch'));
  assert.ok(w.document.querySelector('#catalog-content #catalog-fields'));
  assert.ok(w.document.querySelector('#moderation-content #moderate-player'));
  assert.ok(w.document.querySelector('#settings-content .ui-settings-tabs'));
  assert.ok(w.document.querySelector('#space-content').textContent.length>50);
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
  const color=name=>css.match(new RegExp('--'+name+':\\s*(#[0-9a-f]{6})','i'))[1];
  const luminance=hex=>{const rgb=hex.slice(1).match(/../g).map(s=>parseInt(s,16)/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722};
  for(const foreground of ['text','text2','text3'])for(const background of ['bg','panel','panel2','panel3']){const a=luminance(color(foreground)),b=luminance(color(background));assert.ok((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,foreground+' on '+background)}
});

test('full guest map and signed-in startup complete with local terrain and API fixtures',async t=>{
  let fixtures;
  if(process.env.WC_STARTUP_FIXTURES)fixtures=JSON.parse(fs.readFileSync(process.env.WC_STARTUP_FIXTURES,'utf8'));
  else {
    const generated=spawnSync('python',['-X','utf8',path.join(__dirname,'ui_fixtures.py')],{encoding:'utf8',timeout:60000});
    assert.equal(generated.status,0,generated.stderr);fixtures=JSON.parse(generated.stdout);
  }
  const fetch=async(url,options={})=>{
    const base=String(url).split('?')[0];
    if(base==='/api/terrain/cells')return {ok:true,arrayBuffer:async()=>{const data=fs.readFileSync(path.join(__dirname,'../data/land-cells.bin'));return data.buffer.slice(data.byteOffset,data.byteOffset+data.byteLength)}};
    if(base==='/api/islands')return {ok:true,json:async()=>JSON.parse(fs.readFileSync(path.join(__dirname,'../data/pacific-islands.geojson'),'utf8'))};
    const response=base==='/api/changelog'?{show:false}:base==='/api/away'?{}:base==='/api/wars/unseen'?{wars:[]}:base==='/api/strikes'?{events:[]}:options.method==='POST'?{success:true}:fixtures[base]??{};
    return {ok:true,status:200,json:async()=>structuredClone(response)};
  };
  const {w,dom}=productionDOM(t,{fetch,canvas:true});
  const failures=[];w.console.error=(...args)=>failures.push(args.map(a=>a?.stack||String(a)).join(' '));
  await w.startSpectatorMode();
  assert.equal(w.document.getElementById('game-screen').style.display,'flex',failures.join('\n'));
  assert.equal(w.document.getElementById('auth-overlay').style.display,'none',failures.join('\n'));
  await w.startGame(fixtures['/api/me']);
  assert.equal(w.document.getElementById('game-screen').style.display,'flex',failures.join('\n'));
  assert.equal(w.document.getElementById('auth-overlay').style.display,'none',failures.join('\n'));
  assert.deepEqual(failures,[]);
  const unclaimed=fixtures['/api/territory/200,201'];
  assert.ok(unclaimed,'Real unclaimed-territory response is required');
  w.api=async(method,url)=>structuredClone(url==='/api/territory/200,201'?unclaimed:fixtures[url.split('?')[0]]??{});
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
