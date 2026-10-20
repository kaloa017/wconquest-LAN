/* Admin word filters live beside player moderation. No third-party link fetching. */
const moderatedPanel=buildModeration;
buildModeration=async function(){
  await moderatedPanel();if(!currentUser?.is_admin)return;
  const configuration=await api('GET','/api/admin/chat_filter');if(configuration.error)return;
  const host=document.getElementById('moderation-content');if(!host)return;
  document.getElementById('chat-filter-settings')?.remove();
  const section=document.createElement('section');section.id='chat-filter-settings';section.className='v4-card';
  section.innerHTML='<h3>Chat word filter</h3><p>Blocks listed words and phrases in global chat, faction chat and private trade messages, including edited messages. Matches ignore case and invisible separators. Whole words avoid blocking parts of unrelated words.</p><label><input type="checkbox" id="chat-words-enabled"> Enable word filtering</label><label>Blocked words or phrases (one per line)<textarea id="chat-words" class="form-input" rows="7"></textarea></label><p>Up to 200 entries. An empty list allows all words.</p><button class="btn btn-primary" id="chat-filter-save">Save filter</button>';
  section.querySelector('input').checked=configuration.enabled;
  section.querySelector('textarea').value=configuration.words.join('\n');
  section.querySelector('button').onclick=async()=>{
    const result=await act('/api/admin/chat_filter',{enabled:section.querySelector('input').checked,words:section.querySelector('textarea').value.split('\n').map(word=>word.trim()).filter(Boolean)});
    if(!result.error)buildModeration();
  };
  host.appendChild(section);
};
PANELS.moderation.f=buildModeration;
