let advertisementSettings=null;
function advertisementSafeUrl(value,image=false){if(!value||/[\s\\]/.test(value))return '';if(value.startsWith('/static/')&&!value.includes('..'))return value;try{const url=new URL(value);return (image?url.protocol==='https:':['https:','http:'].includes(url.protocol))&&!url.username&&!url.password?value:''}catch{return ''}}
function renderAdvertisement(banner,target=document.getElementById('advertisement-banner')){
  if(!target)return;target.hidden=!banner?.enabled;
  if(target.id==='advertisement-banner')document.body.classList.toggle('has-advertisement',!!banner?.enabled);
  if(target.id==='advertisement-banner')document.body.classList.toggle('advertisement-mobile',!!banner?.enabled&&banner.show_mobile);
  if(!banner?.enabled){target.replaceChildren();return}
  banner={...banner,link:advertisementSafeUrl(banner.link),image:advertisementSafeUrl(banner.image,true)};
  target.title=[banner.badge,banner.title,banner.message].filter(Boolean).join(' · ');
  target.className='host-advertisement'+(banner.show_mobile?'':' desktop-advertisement');
  target.style.background=banner.background;target.style.color=banner.text_color;target.style.borderColor=banner.border_color;
  target.style.fontSize=banner.font_size+'px';target.style.width=banner.width+'px';target.style.borderRadius=banner.radius+'px';target.style.textAlign=banner.alignment;
  target.innerHTML=(banner.image?`<img src="${esc(banner.image)}" alt="Advertisement image" referrerpolicy="no-referrer">`:'')+`<div class="ad-copy">${banner.badge?`<small style="color:${banner.accent}">${esc(banner.badge)}</small>`:''}${banner.title?`<b>${esc(banner.title)}</b>`:''}${banner.message?`<span>${esc(banner.message)}</span>`:''}${banner.link?`<a href="${esc(banner.link)}" target="_blank" rel="noopener noreferrer" style="color:${banner.accent}">${esc(banner.button_text||'Open link')} ↗</a>`:''}</div>`;
  target.querySelector('img')?.addEventListener('error',event=>event.target.remove());
}
async function refreshAdvertisement(){if(document.hidden)return;const r=await api('GET','/api/advertisement');if(!r.error)renderAdvertisement(r.banner)}
function installAdvertisementTab(){
  const tabs=document.querySelector('.admin-tabs');if(!tabs||document.getElementById('admin-advertisements'))return;
  const button=document.createElement('button');button.className='atab';button.textContent='Advertisements';button.onclick=e=>adminTab(e,'advertisements');tabs.appendChild(button);
  const panel=document.createElement('div');panel.id='admin-advertisements';panel.className='admin-panel';panel.innerHTML='<div id="advertisements-editor"></div>';tabs.parentElement.appendChild(panel);
}
const advertisementTab=adminTab;
adminTab=function(event,id){advertisementTab(event,id);if(id==='advertisements')buildAdvertisementEditor()};
async function buildAdvertisementEditor(){
  if(!currentUser?.is_admin)return;const r=await api('GET','/api/admin/advertisement');if(r.error)return toast(r.error,'error');advertisementSettings=r.banner;
  const field=(key,label,type='text',extra='')=>`<label>${esc(label)}<input class="form-input" id="ad-${key}" type="${type}" value="${esc(String(r.banner[key]))}" ${extra}></label>`;
  document.getElementById('advertisements-editor').innerHTML=card('📣 Banner beside WC',`<p>Plain text only. Changes apply to all players and spectators. External image hosts receive players’ image requests.</p><div class="ad-editor-grid"><label><input id="ad-enabled" type="checkbox" ${r.banner.enabled?'checked':''}> Show banner</label><label><input id="ad-show_mobile" type="checkbox" ${r.banner.show_mobile?'checked':''}> Show on phones</label>${field('badge','Badge / label','text','maxlength="25"')}${field('title','Title','text','maxlength="60"')}${field('message','Message','text','maxlength="160"')}${field('button_text','Link button text','text','maxlength="30"')}${field('link','Link URL (HTTP/HTTPS or /static/)','url')}${field('image','Image URL (HTTPS or /static/)','text')}${field('background','Background','color')}${field('text_color','Text color','color')}${field('accent','Accent / link color','color')}${field('border_color','Border color','color')}${field('font_size','Font size','number','min="10" max="20"')}${field('width','Desktop width','number','min="100" max="360"')}${field('radius','Corner radius','number','min="0" max="24"')}<label>Alignment<select id="ad-alignment" class="form-input"><option value="left" ${r.banner.alignment==='left'?'selected':''}>Left</option><option value="center" ${r.banner.alignment==='center'?'selected':''}>Center</option></select></label></div><h4>Preview</h4><div id="advertisement-preview"></div><div class="v4-row"><button class="btn btn-primary" onclick="saveAdvertisement()">Save banner</button><button class="btn btn-ghost" onclick="disableAdvertisement()">Remove banner</button></div>`);
  document.querySelectorAll('#advertisements-editor input,#advertisements-editor select').forEach(input=>input.addEventListener('input',previewAdvertisement));previewAdvertisement();
}
function advertisementForm(){const data={};for(const key of Object.keys(advertisementSettings)){const el=document.getElementById('ad-'+key);data[key]=el.type==='checkbox'?el.checked:el.type==='number'?Number(el.value):el.value}return data}
function previewAdvertisement(){const data=advertisementForm();renderAdvertisement({...data,enabled:true},document.getElementById('advertisement-preview'))}
async function saveAdvertisement(){const r=await api('POST','/api/admin/advertisement',advertisementForm());if(r.error)return toast(r.error,'error');advertisementSettings=r.banner;renderAdvertisement(r.banner);toast(r.message,'success')}
async function disableAdvertisement(){const r=await api('POST','/api/admin/advertisement',{...advertisementSettings,enabled:false});if(r.error)return toast(r.error,'error');advertisementSettings=r.banner;document.getElementById('ad-enabled').checked=false;renderAdvertisement(r.banner);toast('Banner removed','success')}
const advertisementStart=startSession;
startSession=async function(user){await advertisementStart(user);await refreshAdvertisement();pollHandles.push(setInterval(refreshAdvertisement,30000))};startGame=startSession;startSpectatorMode=()=>startSession(null);
installAdvertisementTab();ready.then(refreshAdvertisement);
