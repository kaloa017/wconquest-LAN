/* Offline visual checks: no game server is launched or contacted. */
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),{chromium}=require('playwright');
const project=path.resolve(__dirname,'..'),fixtures=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),output=path.resolve(process.argv[3]);
fs.mkdirSync(output,{recursive:true});
let browser;
(async()=>{
  browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],posts=[],checks=[];
  page.on('pageerror',error=>errors.push(error.stack));
  await page.route('**/*',async route=>{
    const url=new URL(route.request().url()),name=url.pathname;
    if(url.hostname!=='game.test')return route.abort();
    if(name==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(project,'index.html'))});
    if(name.startsWith('/static/')){const file=path.join(project,name.slice(1));if(!fs.existsSync(file))return route.fulfill({status:404,body:''});return route.fulfill({contentType:name.endsWith('.css')?'text/css':name.endsWith('.js')?'text/javascript':'image/png',body:fs.readFileSync(file)})}
    if(name==='/api/terrain/cells')return route.fulfill({contentType:'application/octet-stream',body:fs.readFileSync(path.join(project,'data/land-cells.bin'))});
    if(name==='/api/islands')return route.fulfill({contentType:'application/json',body:fs.readFileSync(path.join(project,'data/pacific-islands.geojson'))});
    if(route.request().method()==='POST'){const data=route.request().postDataJSON();posts.push({path:name,data});if(name==='/api/combat/preview')return route.fulfill({contentType:'application/json',body:JSON.stringify({odds:65,attack:1000,defense:500,atk_mods:[],def_mods:[]})});if(name==='/api/planes/attack')return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,attacker_wins:false,message:'Your force retreated.',breakdown:{attack:25000,defense:50000,weather:'clear',atk_mods:[],def_mods:[]}})});if(name==='/api/changelog/seen')fixtures['/api/changelog'].data.show=false;return route.fulfill({contentType:'application/json',body:JSON.stringify({success:true,message:'Saved',campaign_id:1})})}
    const fixture=fixtures[name];return route.fulfill({status:fixture?.status||200,contentType:'application/json',body:JSON.stringify(fixture?.data||{})});
  });
  await page.addInitScript(()=>localStorage.setItem('wc_tut','1'));
  await page.goto('https://game.test');await page.evaluate(async user=>{await ready;await startSession(user)},fixtures['/api/me'].data);
  await page.locator('#v6-dialog').waitFor();
  assert.equal(await page.locator('#v6-dialog .v6-dialog').evaluate(el=>el.scrollTop),0);
  const notes=await page.locator('#v6-dialog pre').textContent();assert(notes.includes('# 6.5.0'));assert(!notes.includes('# 6.3.6'));checks.push('Changelog includes unseen releases and opens at top');
  await page.locator('#text-dialog-done').click();
  assert(posts.some(p=>p.path==='/api/changelog/seen'&&p.data.version==='6.5.0'));
  fixtures['/api/notifications']={status:200,data:[{id:901,type:'info',message:'An unread notification',created_at:'2026-10-09',data:null}]};
  await page.evaluate(()=>pollNotifications());
  assert.equal(await page.locator('#notification-count').textContent(),' 1');
  assert.equal(await page.locator('.notif-popup').count(),0);
  await page.locator('#notification-bell').click();
  await page.locator('#notification-inbox').waitFor();
  assert((await page.locator('#notification-inbox').textContent()).includes('An unread notification'));
  await page.evaluate(()=>closeCommunityDialog());
  checks.push('Notifications stay in the bell inbox without covering the game');
  await page.evaluate(()=>openExpansionPanel('operations'));
  assert.equal(await page.locator('.private-battle-icon').count(),1);
  await page.waitForFunction(()=>document.getElementById('operations-content')?.textContent.includes('12,345'));
  await page.screenshot({path:path.join(output,'operations-desktop.png')});
  await page.evaluate(()=>beginBattlePlan('200,200'));
  await page.evaluate(()=>onMapClick({latlng:{lat:(200+.5)*GRID,lng:(201+.5)*GRID}}));
  await page.evaluate(()=>onMapClick({latlng:{lat:(200+.5)*GRID,lng:(202+.5)*GRID}}));
  assert((await page.locator('#plan-route').textContent()).includes('200,201 → 200,202'));
  await page.locator('#plan-troops').fill('123456');await page.locator('#plan-start').click();
  await page.waitForFunction(()=>!document.getElementById('battle-planner'));
  assert(posts.some(p=>p.path==='/api/attack'&&p.data.troops===123456&&p.data.target_keys.length===2));checks.push('Map planner sends an exact troop count and queued targets');
  await page.evaluate(async()=>{selectedKey='200,202';showPanel('territory');await fetchAndBuildPanel(selectedKey)});
  await page.locator('[data-airstrike="1"]').waitFor();
  await page.keyboard.press('f');await page.waitForTimeout(150);
  assert(posts.some(p=>p.path==='/api/planes/attack'));
  const strikes=posts.filter(p=>p.path==='/api/planes/attack').length;
  await page.keyboard.press('f');assert.equal(posts.filter(p=>p.path==='/api/planes/attack').length,strikes);
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await page.evaluate(()=>showTextModal('Typing test','A dialog is open'));await page.keyboard.press('f');assert.equal(posts.filter(p=>p.path==='/api/planes/attack').length,strikes);await page.locator('#text-dialog-done').click();checks.push('F triggers an available air assault and is blocked by dialogs');
  await page.evaluate(()=>{document.getElementById('toast').classList.remove('show');openExpansionPanel('space')});await page.locator('.planet-tile').first().waitFor();
  assert.equal(await page.locator('.planet-tile').count(),36);
  await page.locator('#space-qty-satellite').focus();await page.keyboard.press('f');assert.equal(posts.filter(p=>p.path==='/api/planes/attack').length,strikes);
  await page.locator('#space-qty-satellite').fill('5000');assert.equal(await page.locator('#space-qty-satellite').getAttribute('max'),null);
  await page.evaluate(()=>{document.activeElement.blur();document.getElementById('panel-space').scrollTop=0});await page.screenshot({path:path.join(output,'space-desktop.png')});
  for(const viewport of [{width:768,height:900},{width:390,height:844},{width:320,height:640}]){
    await page.setViewportSize(viewport);await page.evaluate(()=>openExpansionPanel('space'));await page.locator('.planet-tile').first().waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    const bounds=await page.locator('.planet-grid').evaluate(el=>{const r=el.getBoundingClientRect();return{left:r.left,right:r.right}});assert(bounds.left>=0&&bounds.right<=viewport.width);
    await page.screenshot({path:path.join(output,`space-${viewport.width}.png`)});
    await page.locator('.planet-grid').screenshot({path:path.join(output,`planet-${viewport.width}.png`)});
    await page.evaluate(()=>beginBattlePlan('200,200'));await page.waitForTimeout(250);const planBounds=await page.locator('#battle-planner').boundingBox();assert(planBounds.x>=0&&planBounds.x+planBounds.width<=viewport.width&&planBounds.y>=0);await page.screenshot({path:path.join(output,`planner-${viewport.width}.png`)});await page.evaluate(()=>cancelBattlePlan());
    await page.evaluate(()=>showTextModal('Long update',('Release notes\n'+'More detail '.repeat(30)+'\n').repeat(30),()=>{},'Acknowledge'));
    assert.equal(await page.locator('#v6-dialog .v6-dialog').evaluate(el=>el.scrollTop),0);await page.locator('#text-dialog-done').click();
  }
  checks.push('Space maps, planners and long dialogs fit 320, 390, 768 and 1440 pixel layouts');
  await page.setViewportSize({width:1440,height:1000});
  for(const id of ['territory','chat','faction','quests','empire','research','market','stocks','banks','trading','leaderboard','battles','social','moderation','catalog']){await page.evaluate(id=>showPanel(id),id);await page.waitForTimeout(80)}
  checks.push('Existing country, economy, community and host menus render without page errors');
  await page.evaluate(()=>{showPanel('space');renderSpace(spaceSnapshot)});
  fixtures['/api/space'].data.tutorial_required=true;
  await page.evaluate(()=>buildSpace());await page.locator('#v6-dialog').waitFor();
  assert((await page.locator('#v6-dialog pre').textContent()).includes('Every player gets the same personal'));assert.equal(await page.locator('#v6-dialog .v6-dialog').evaluate(el=>el.scrollTop),0);
  await page.locator('#text-dialog-done').click();fixtures['/api/space'].data.tutorial_required=false;await page.evaluate(()=>buildSpace());assert.equal(await page.locator('#v6-dialog').count(),0);checks.push('Space tutorial appears on unlock and acknowledgement prevents repeat display');
  const program=fixtures['/api/space'].data.program;program.state='returning';program.arrival=Math.ceil(Date.now()/1000)+180;program.remaining_seconds=180;
  await page.evaluate(()=>buildSpace());await page.locator('#space-countdown').waitFor();const before=await page.locator('#space-countdown').textContent();await page.waitForFunction(before=>document.getElementById('space-countdown').textContent!==before,before);checks.push('Travel countdown updates while expedition controls are locked');
  await page.evaluate(()=>drawPrivateBattles([{id:99,attacker:998,defender:997,status:'active'}]));assert.equal(await page.locator('.private-battle-icon').count(),0);checks.push('Client also rejects markers for unrelated participants');
  await page.evaluate(()=>openAdmin());await page.waitForTimeout(100);await page.evaluate(()=>closeAdmin());

  await page.evaluate(()=>stopPolling());assert.equal(await page.locator('.private-battle-icon').count(),0);checks.push('Session cleanup removes private battle markers');
  assert.deepEqual(errors,[]);checks.push('No browser page errors');
  fs.writeFileSync(path.join(output,'ui-results.json'),JSON.stringify({checks,errors},null,2));
  console.log(checks.join('\n'));await browser.close();
})().catch(async error=>{console.error(error);await browser?.close();process.exitCode=1});
