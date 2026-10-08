const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/legacy-client.js'),'utf8');
function functionSource(name){const start=source.indexOf('async function '+name+'(');assert(start>=0);const end=source.indexOf('\nasync function ',start+1);return source.slice(start,end<0?undefined:end)}
(async()=>{
const element={innerHTML:''},context={api:async()=>[{id:1,message:'<img src=x onerror=alert(1)>',image_url:'https://example.com/<script>',author:'<b>Host</b>',created_at:'2026-10-08'}],document:{getElementById:()=>element}};
vm.createContext(context);
vm.runInContext("const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"+functionSource('loadAdminAnns'),context);
await context.loadAdminAnns();assert(!element.innerHTML.includes('<img'));assert(element.innerHTML.includes('&lt;img'));assert(element.innerHTML.includes('&lt;script&gt;'));// A delayed territory response must not repaint a newly selected tile.
const panel=source.slice(source.lastIndexOf('async function fetchAndBuildPanel('),source.lastIndexOf('async function fetchAndBuildPanel(')+source.slice(source.lastIndexOf('async function fetchAndBuildPanel(')).indexOf('\n/* keep scouting'));
let resolveTile,painted=false;const tileContext={sessionGeneration:1,selectedKey:'old',reportWater:async()=>{},api:()=>new Promise(resolve=>resolveTile=resolve),territories:{},renderTerritories:()=>{painted=true},window:{},isMobile:()=>false,buildTerritoryPanel:()=>{painted=true}};
vm.createContext(tileContext);vm.runInContext(panel,tileContext);const pending=tileContext.fetchAndBuildPanel('old');await new Promise(resolve=>setImmediate(resolve));tileContext.selectedKey='new';resolveTile({owner_id:1});await pending;assert.equal(painted,false);assert.deepEqual(Object.keys(tileContext.territories),[]);
// Private chat must not enter a different conversation after a channel switch.
let resolveChat,appended=false;const box={innerHTML:'',insertAdjacentHTML:()=>{appended=true}};
const chatContext={currentUser:{id:1,faction:{id:7}},sessionGeneration:1,chatCh:'faction',chatLastId:{global:0,faction:0},document:{getElementById:()=>box},api:()=>new Promise(resolve=>resolveChat=resolve)};
vm.createContext(chatContext);vm.runInContext(functionSource('pollChat'),chatContext);const chat=chatContext.pollChat();chatContext.chatCh='global';resolveChat({messages:[{id:1,text:'private'}],last_id:1});await chat;assert.equal(appended,false);assert.equal(chatContext.chatLastId.faction,0);
assert(source.includes('window.innerWidth<=768'));
// Failed bootstrap must become a useful API error, not an unhandled rejection.
const active=fs.readFileSync(path.join(__dirname,'../static/client.js'),'utf8');const startup=active.slice(0,active.indexOf('function card('));
const failedContext={Audio:function(){},fetch:async()=>({ok:false,status:503}),api:null};vm.createContext(failedContext);vm.runInContext(startup,failedContext);const failed=await failedContext.api('GET','/api/me');assert.match(failed.error,/Connection interrupted/);
const statusStart=source.indexOf('async function checkGameStatus('),statusEnd=source.indexOf('\n}',statusStart)+2;
let hidden=false;const statusContext={api:async()=>({status:'winner',automatic_reset:false,reset_in:null}),hideWinScreen:()=>{hidden=true},showWinScreen:()=>{throw Error('Must not start a destructive countdown')},winShowing:false};vm.createContext(statusContext);vm.runInContext(source.slice(statusStart,statusEnd),statusContext);await statusContext.checkGameStatus();assert.equal(hidden,true);
console.log('Client security, stale responses, startup and safe win-status regressions passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
