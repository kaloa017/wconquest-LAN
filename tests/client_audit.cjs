const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/legacy-client.js'),'utf8');
function functionSource(name){const start=source.indexOf('async function '+name+'(');assert(start>=0);const end=source.indexOf('\nasync function ',start+1);return source.slice(start,end<0?undefined:end)}
(async()=>{
const element={innerHTML:''},context={api:async()=>[{id:1,message:'<img src=x onerror=alert(1)>',image_url:'https://example.com/<script>',author:'<b>Host</b>',created_at:'2026-10-08'}],document:{getElementById:()=>element}};
vm.createContext(context);
vm.runInContext("const esc=s=>String(s??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"+functionSource('loadAdminAnns'),context);
await context.loadAdminAnns();assert(!element.innerHTML.includes('<img'));assert(element.innerHTML.includes('&lt;img'));assert(element.innerHTML.includes('&lt;script&gt;'));console.log('Client security regressions passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
