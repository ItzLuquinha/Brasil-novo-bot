const guildSelect=document.querySelector('#guild')
const metrics=document.querySelector('#metrics')
const activity=document.querySelector('#activity')
const statusNode=document.querySelector('#status')
const settingsForm=document.querySelector('#settings')
const automodForm=document.querySelector('#automod-settings')
const automodRules=document.querySelector('#automod-rules')
const ticketsList=document.querySelector('#tickets-list')
const suggestionsList=document.querySelector('#suggestions-list')
const reportsList=document.querySelector('#reports-list')
const giveawaysList=document.querySelector('#giveaways-list')
const pollsList=document.querySelector('#polls-list')

async function getJson(url,options){const response=await fetch(url,options);if(response.status===401){window.location.href='/auth/login';throw new Error('Sessão expirada. Redirecionando para o Discord...')}if(!response.ok){const body=await response.json().catch(()=>({detail:'Erro'}));throw new Error(body.detail||'Erro');}return response.json()}

function metric(label,value){return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`}
function esc(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#039;'})[char])}
function selectStatus(kind,id,status,options){return `<select data-community-kind="${esc(kind)}" data-community-id="${esc(id)}"><option value="${esc(status)}" selected>${esc(status)}</option>${options.filter(value=>value!==status).map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('')}</select>`}

async function loadAutomod(){const guildId=guildSelect.value;if(!guildId)return;try{const data=await getJson(`/api/guilds/${guildId}/automod`);automodForm.enabled.value=String(data.enabled);automodForm.blacklist_action.value=data.blacklist_action;automodRules.innerHTML=data.rules.map(rule=>`<div class="rule-row"><strong>#${esc(rule.id)} ${esc(rule.name)}</strong><span>${esc(rule.rule_type)}</span><span>${esc(rule.action)}</span><span>${rule.enabled?'ATIVA':'OFF'}</span><span>P${rule.priority}</span></div>`).join('')||'<p>Nenhuma regra.</p>'}catch(error){automodRules.innerHTML=`<p>${esc(error.message)}</p>`}}

async function loadOverview(){const guildId=guildSelect.value;if(!guildId)return;statusNode.textContent='Atualizando dados...';try{const data=await getJson(`/api/guilds/${guildId}/overview`);metrics.innerHTML=[metric('Membros',data.members),metric('Mensagens',data.messages),metric('Economia',data.economy.toFixed(2)),metric('Tickets',data.tickets),metric('Denúncias',data.reports),metric('Warns',data.warnings),metric('Sugestões',data.pending_suggestions)].join('');const activityData=await getJson(`/api/guilds/${guildId}/activity?days=7`);const max=Math.max(...activityData.messages.map(item=>item.value),1);activity.innerHTML=activityData.messages.map(item=>`<div class="bar"><span>${new Date(item.bucket).toLocaleString()}</span><i style="width:${Math.max(4,(item.value/max)*70)}%"></i><b>${item.value}</b></div>`).join('')||'<p>Nenhuma atividade registrada no período.</p>';const config=await getJson(`/api/guilds/${guildId}/settings`);settingsForm.timezone.value=config.timezone;settingsForm.locale.value=config.locale;statusNode.textContent='Dados atualizados.'}catch(error){statusNode.textContent=error.message}}

async function loadGuilds(){try{const guilds=await getJson('/api/guilds');guildSelect.innerHTML=guilds.map(guild=>`<option value="${esc(guild.id)}">${esc(guild.name)}</option>`).join('');if(!guilds.length){statusNode.textContent='Nenhum servidor disponível para gerenciamento.';return}await loadOverview();await loadAutomod();await loadCommunity()}catch(error){statusNode.textContent=error.message}}

guildSelect.addEventListener('change',async()=>{await loadOverview();await loadAutomod();await loadCommunity()})
document.querySelector('#refresh').addEventListener('click',async()=>{await loadOverview();await loadAutomod();await loadCommunity()})
settingsForm.addEventListener('submit',async(event)=>{event.preventDefault();try{await getJson(`/api/guilds/${guildSelect.value}/settings`,{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('input[name=csrf]')?.value||''},body:JSON.stringify({timezone:settingsForm.timezone.value,locale:settingsForm.locale.value})});statusNode.textContent='Configuração salva.'}catch(error){statusNode.textContent=error.message}})

loadGuilds()

automodForm.addEventListener('submit',async(event)=>{event.preventDefault();try{await getJson(`/api/guilds/${guildSelect.value}/automod`,{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('input[name=csrf]')?.value||''},body:JSON.stringify({enabled:automodForm.enabled.value==='true',blacklist_action:automodForm.blacklist_action.value})});statusNode.textContent='AutoMod salvo.';await loadAutomod()}catch(error){statusNode.textContent=error.message}})

async function loadCommunity(){
 const guildId=guildSelect.value;if(!guildId)return;
 try{
  const data=await getJson(`/api/guilds/${guildId}/community`);
  ticketsList.innerHTML=data.tickets.map(row=>`<div class="data-row"><div><strong>#${esc(row.id)}</strong><span>${esc(row.category)} · ${esc(row.priority)}</span></div><span>${esc(row.status)}</span>${selectStatus('ticket',row.id,row.status,['open','closed'])}</div>`).join('')||'<p>Nenhum ticket.</p>';
  suggestionsList.innerHTML=data.suggestions.map(row=>`<div class="data-row"><div><strong>#${esc(row.id)}</strong><span>${esc(row.content).slice(0,120)}</span></div><span>${esc(row.upvotes)} / ${esc(row.downvotes)}</span>${selectStatus('suggestion',row.id,row.status,['pending','analysis','approved','rejected','implemented'])}<button type="button" data-delete-suggestion="${esc(row.id)}">Excluir</button></div>`).join('')||'<p>Nenhuma sugestão.</p>';
  reportsList.innerHTML=data.reports.map(row=>`<div class="data-row"><div><strong>#${esc(row.id)}</strong><span>${esc(row.reason).slice(0,120)}</span></div><span>${esc(row.reported_id)}</span>${selectStatus('report',row.id,row.status,['open','investigating','resolved','rejected'])}</div>`).join('')||'<p>Nenhuma denúncia.</p>';
  giveawaysList.innerHTML=data.giveaways.map(row=>`<div class="data-row"><div><strong>#${esc(row.id)}</strong><span>${esc(row.prize)}</span></div><span>${esc(row.entrants)} participantes</span><span>${esc(row.status)}</span></div>`).join('')||'<p>Nenhum sorteio.</p>';
  pollsList.innerHTML=data.polls.map(row=>`<div class="data-row"><div><strong>#${esc(row.id)}</strong><span>${esc(row.question).slice(0,120)}</span></div><span>${esc(row.votes)} votos</span><span>${esc(row.status)}</span></div>`).join('')||'<p>Nenhuma enquete.</p>';
 }catch(error){const message=`<p>${esc(error.message)}</p>`;ticketsList.innerHTML=message;suggestionsList.innerHTML=message;reportsList.innerHTML=message;giveawaysList.innerHTML=message;pollsList.innerHTML=message}
}

async function updateCommunityStatus(kind,id,status){
 const endpoint={ticket:'tickets',suggestion:'suggestions',report:'reports'}[kind];if(!endpoint)return;
 try{await getJson(`/api/guilds/${guildSelect.value}/${endpoint}/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('input[name=csrf]')?.value||''},body:JSON.stringify({status,note:'Atualizado pelo dashboard'})});statusNode.textContent='Estado atualizado.';await loadCommunity();await loadOverview()}catch(error){statusNode.textContent=error.message;await loadCommunity()}
}

suggestionsList.addEventListener('click',async(event)=>{const button=event.target.closest('[data-delete-suggestion]');if(!button)return;const id=button.dataset.deleteSuggestion;if(!window.confirm(`Excluir permanentemente a sugestão #${id}?`))return;button.disabled=true;try{await getJson(`/api/guilds/${guildSelect.value}/suggestions/${encodeURIComponent(id)}`,{method:'DELETE',headers:{'X-CSRF-Token':document.querySelector('input[name=csrf]')?.value||''}});statusNode.textContent=`Sugestão #${id} excluída.`;await loadCommunity();await loadOverview()}catch(error){statusNode.textContent=error.message;button.disabled=false}})
for(const selector of [ticketsList,suggestionsList,reportsList])selector.addEventListener('change',event=>{const node=event.target;if(!node.dataset.communityKind)return;updateCommunityStatus(node.dataset.communityKind,node.dataset.communityId,node.value)})
