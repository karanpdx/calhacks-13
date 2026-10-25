// Lender console: one lender's side of every CRS sandbox session (GET /api/lender/{id}).
// It only ever receives what the lender saw: the passport, its own offers and books, anonymous quotes, the outcome.
// Optional feeds: GET /api/lender/{id}/network (agent web + referee ticker) and POST /api/lender/{id}/ask (the desk).
// Either can be missing: the web and ticker are then derived from the cases, and the desk answers with local rules.
(function(){
const LC=window.LC=window.LC||{};
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=id=>document.getElementById(id);
const money=n=>'$'+Number(n||0).toLocaleString();
const pct=t=>t?`${t.apr}%`:'-';
const reduced=()=>window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const SUGGEST=['Give me a summary','What needs my review?',"What's my win rate?",'Why did we lose deals?','How many agents are we connected to?'];
const state=LC.state={data:null,cases:[],net:null,filter:'All',selected:null,resolved:new Set(),chat:[],busy:false,
  lenderId:new URLSearchParams(location.search).get('lender')||'campus_cu',loadedFor:null};

const caseById=id=>state.cases.find(c=>c.id===id)||null;
const needsReview=c=>c.attention&&!state.resolved.has(c.id);
async function getJSON(url,opt){const r=await fetch(url,opt);if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}

// ---------- load ----------
async function load(){
  $('rowCount').textContent='Loading...';
  const id=encodeURIComponent(state.lenderId);
  const [lr,nr]=await Promise.allSettled([getJSON(`/api/lender/${id}`),getJSON(`/api/lender/${id}/network`)]);
  if(lr.status!=='fulfilled'){
    $('brief').innerHTML=`<span class="err">Couldn’t load your queue (${safe(lr.reason&&lr.reason.message)}).</span> <button class="chip" type="button" id="retry">Try again</button>`;
    $('retry')?.addEventListener('click',load);$('rowCount').textContent='Not loaded';return;
  }
  const d=state.data=lr.value;state.cases=Array.isArray(d.cases)?d.cases:[];
  const n=nr.status==='fulfilled'?nr.value:null;
  state.net=(n&&Array.isArray(n.nodes)&&Array.isArray(n.edges)&&n.nodes.length)?n:deriveNetwork();
  if(!caseById(state.selected))state.selected=(state.cases.find(needsReview)||state.cases[0]||{}).id||null;
  const L=d.lender||{};
  $('lenderPick').innerHTML=(d.lenders||[]).map(l=>`<option value="${safe(l.id)}"${l.id===L.id?' selected':''}>${safe(l.name)}</option>`).join('');
  $('heroTitle').textContent=L.name||'Lender console';
  $('heroMotive').textContent=L.motive||'';
  document.title=`${L.name||'Lender'} · Lender console`;
  renderBrief();counts();renderRows();
  LC.web.render(state.net,{selected:state.selected,caseById,onSelect:select,onToast:toast});
  LC.activity.ticker(state.net.recent&&state.net.recent.length?state.net.recent:deriveRecent(),{derived:!!state.net.derived||!(state.net.recent&&state.net.recent.length),isCase:id=>!!caseById(id),onSelect:select});
  LC.activity.flow(flowCounts(),{onPick:act});
  if(state.loadedFor!==state.lenderId){state.loadedFor=state.lenderId;resetChat()}
}

// ---------- fallbacks derived from the lender's own cases ----------
const EDGE_KIND={Won:'won',Lost:'lost','No deal':'offered',Declined:'declined'};
function msgCount(c){return c.opening?(c.rounds||0)+(c.counters||0)+1:1}
function deriveNetwork(){
  const d=state.data,s=d.stats||{},cases=state.cases;
  const nodes=[{id:'you',kind:'you',label:(d.lender||{}).name,messages:0,deals:0}],edges=[];
  const rivals=Math.max(0,Math.min(5,((d.lenders||[]).length||6)-1));
  for(let i=0;i<rivals;i++){const ch='ABCDE'[i];nodes.push({id:'rival-'+ch,kind:'rival',label:'Lender '+ch,messages:null,deals:null})}
  cases.forEach((c,i)=>{const m=msgCount(c);
    nodes.push({id:c.id,kind:'applicant',label:c.id,risk:c.risk,band:c.band,status:c.status,messages:m,deals:c.status==='Won'?1:0});
    edges.push({source:'you',target:c.id,messages:m,kind:EDGE_KIND[c.status]||'offered',last_seq:c.opening?cases.length+i:i,blocked:false});
    nodes[0].messages+=m;if(c.status==='Won')nodes[0].deals++;});
  const blocked=s.blocked_at_gate||0;
  for(let i=0;i<blocked;i++)nodes.push({id:'gate-'+(i+1),kind:'applicant',label:'Stopped at gate',status:'Blocked',messages:0,deals:0});
  return {lender:d.lender,nodes,edges,derived:true,recent:[],
    stats:{borrower_agents:cases.length+blocked,lender_agents:(d.lenders||[]).length||rivals+1,admitted:cases.length,blocked_at_gate:blocked,messages_checked:nodes[0].messages,messages_blocked:0,deals:nodes[0].deals}};
}
function readable(code){return String(code||'').replace(/_/g,' ').toLowerCase()}
function deriveRecent(){
  const lists=[],s=(state.data&&state.data.stats)||{};
  for(let i=0;i<(s.blocked_at_gate||0);i++)lists.push([{from:'A borrower agent',to:'gate',what:'Stopped before the market: fraud or identity check failed',verdict:'blocked'}]);
  for(const c of state.cases){
    const ev=[];
    if(!c.opening){ev.push({from:c.id,to:'you',what:`Loan request: ${money(c.request.amount)}, ${c.request.terms}`,verdict:'allowed'});ev.push({from:'you',to:c.id,what:`Declined: ${readable(c.decline_code)||'outside your rules'}`,verdict:'allowed'});lists.push(ev);continue}
    ev.push({from:c.id,to:'you',what:`Loan request: ${money(c.request.amount)}, ${c.request.terms}`,verdict:'allowed'});
    for(let r=0;r<(c.rounds||1);r++){
      const last=r===(c.rounds||1)-1;
      ev.push({from:'you',to:c.id,what:r===0?`Offer ${c.opening.apr}% APR, ${c.opening.term_months} months`:last&&c.final?`Final offer ${c.final.apr}%${c.final.autopay?' with autopay':''}`:'Revised offer, still above your floor',verdict:'allowed'});
      if(r<(c.counters||0))ev.push({from:c.id,to:'you',what:'Counter-offer: asks for a lower rate',verdict:'allowed'});
    }
    ev.push({from:c.id,to:'you',what:c.status==='Won'?`Accepted ${pct(c.final)}`:c.status==='Lost'?'Chose another verified offer':'Walked away: nothing inside its mandate',verdict:'allowed'});
    lists.push(ev);
  }
  const out=[];let k=0,any=true;
  while(any){any=false;for(const l of lists){if(l[k]){out.push(l[k]);any=true}}k++}
  return out;
}
function flowCounts(){
  const s=(state.net&&state.net.stats)||{},cs=state.cases,ds=(state.data&&state.data.stats)||{};
  const gate=s.blocked_at_gate??ds.blocked_at_gate??0,admitted=cs.length;
  const offered=cs.filter(c=>c.opening).length;
  return {total:admitted+gate,gate,admitted,offered,declined:admitted-offered,won:cs.filter(c=>c.status==='Won').length,lost:cs.filter(c=>c.status==='Lost').length,nodeal:cs.filter(c=>c.status==='No deal').length};
}

// ---------- brief (KPIs as a sentence) ----------
const chip=(key,num,label,cls='')=>`<button type="button" class="chip ${cls}" data-act="${key}"><b>${safe(num)}</b> ${safe(label)}</button>`;
function renderBrief(){
  const d=state.data,L=d.lender||{},v=L.volume||{},f=flowCounts(),s=state.net.stats||{};
  const review=state.cases.filter(needsReview).length;
  const agents=(s.borrower_agents||0)+(s.lender_agents||0);
  $('brief').innerHTML=`${chip('apps',f.admitted,'applications reached you','calm')} after the CRS gate stopped ${chip('gate',f.gate,f.gate===1?'borrower agent':'borrower agents')}. Your agent made ${chip('offered',f.offered,f.offered===1?'offer':'offers')} and won ${chip('won',f.won,f.won===1?'loan':'loans')}${review?`; ${chip('review',review,review===1?'needs your review':'need your review','warn')}`:'; nothing needs your review'}. Booked ${chip('volume',`${v.booked??'-'} of ${v.target??'-'}`,'this month')}, in an exchange of ${chip('agents',agents,'agents')} with ${chip('checked',s.messages_checked??'-',state.net.derived?'messages with your agent':'messages checked')}.`;
  $('brief').querySelectorAll('[data-act]').forEach(b=>b.addEventListener('click',()=>act(b.dataset.act)));
}
function goTo(id,focusEl){
  const el=$(id);if(!el)return;
  el.scrollIntoView({behavior:reduced()?'auto':'smooth',block:'start'});
  if(focusEl)setTimeout(()=>focusEl.focus({preventScroll:true}),reduced()?0:350);
}
function act(key){
  const filters={apps:'All',in:'All',all:'All',offered:'Offered',won:'Won',lost:'Lost',review:'Review',declined:'Declined',nodeal:'Declined'};
  if(filters[key]){setFilter(filters[key]);goTo('queue');return}
  if(key==='gate'){goTo('web');LC.web.showBlocked();toast('Dashed nodes: borrower agents the CRS gate stopped. You never see them.');return}
  if(key==='agents'){goTo('web');return}
  if(key==='checked'){goTo('activity');return}
  if(key==='volume'){goTo('desk');ask('How am I doing against my monthly target?');return}
}

// ---------- queue ----------
function counts(){
  const n=f=>visibleCases(f,'').length;
  for(const [id,f] of [['fAll','All'],['fReview','Review'],['fOffered','Offered'],['fWon','Won'],['fLost','Lost'],['fDeclined','Declined']])$(id).textContent=n(f);
  const open=state.cases.filter(needsReview).length,b=$('navReview');
  b.textContent=open;b.classList.toggle('zero',!open);
}
function setFilter(next){
  state.filter=next;
  document.querySelectorAll('.filter').forEach(b=>{const on=b.dataset.filter===next;b.classList.toggle('active',on);b.setAttribute('aria-pressed',String(on))});
  renderRows();
}
function visibleCases(f=state.filter,q=($('search')?.value||'').toLowerCase()){
  return state.cases.filter(c=>(f==='All'||(f==='Review'?needsReview(c):f==='Offered'?!!c.opening:f==='Declined'?['Declined','No deal'].includes(c.status):c.status===f))
    &&(!q||`${c.id} ${c.band} ${c.risk} ${c.stage}`.toLowerCase().includes(q)));
}
function statusPill(c){
  if(needsReview(c))return '<span class="status review">Needs review</span>';
  const cls=c.status==='Won'?'won':c.status==='Lost'?'lost':'declined';
  return `<span class="status ${cls}">${safe(c.status)}</span>`;
}
function renderRows(){
  const body=$('caseRows');if(!body)return;const rows=visibleCases();
  $('rowCount').textContent=`Showing ${rows.length} of ${state.cases.length} applications`;
  body.innerHTML=rows.length?rows.map(c=>`<tr data-id="${safe(c.id)}" class="${c.id===state.selected?'selected':''}" tabindex="0" aria-selected="${c.id===state.selected}"><td><div class="app-cell"><b>${safe(c.id)}</b><small>${safe(c.band)}</small></div></td><td class="mono">${money(c.request.amount)}</td><td class="c-risk"><span class="tag r-${safe(c.risk)}">${safe(c.risk)}</span></td><td class="c-stage stage-text">${safe(c.stage)}</td><td class="mono">${c.final?safe(pct(c.opening)+' → '+pct(c.final)):'-'}</td><td>${statusPill(c)}</td></tr>`).join(''):'<tr><td colspan="6" class="queue-empty">No applications match this view.</td></tr>';
  body.querySelectorAll('tr[data-id]').forEach(row=>{const go=()=>select(row.dataset.id,'queue');row.addEventListener('click',go);row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}})});
  renderDetail();
}
function select(id,src){
  if(!caseById(id))return;
  state.selected=id;
  if(!visibleCases().some(c=>c.id===id)){if($('search'))$('search').value='';setFilter('All')}else renderRows();
  LC.web.select(id);
  const c=caseById(id),strip=$('webSelect');
  if(strip){
    strip.hidden=false;
    strip.innerHTML=`<span>Selected <span class="mono">${safe(id)}</span> · ${safe(c.status)}${c.final?` at ${safe(c.final.apr)}%`:''}</span><button type="button" class="btn small ghost" id="openDetail">Open details</button>`;
    $('openDetail').addEventListener('click',()=>goTo('caseDetail',$('caseDetail')));
  }
  const row=document.querySelector(`#caseRows tr[data-id="${CSS.escape(id)}"]`);
  if(row&&src!=='queue'){row.classList.remove('flash');void row.offsetWidth;row.classList.add('flash')}
  if(src==='chat'||src==='ticker'||src==='list'||src==='detail-ask')goTo('caseDetail',$('caseDetail'));
}

// ---------- detail ----------
const drow=(k,v)=>`<div class="drow"><span>${safe(k)}</span><b>${safe(v)}</b></div>`;
function ladder(c){
  const b=c.books,o=c.opening.apr,f=c.final.apr,be=b.break_even_apr,fl=b.floor_apr;
  const lo=Math.min(be,fl,f)-.6,hi=Math.max(o,f)+.5,W=320,X0=6,X1=W-6,x=v=>X0+(v-lo)/(hi-lo)*(X1-X0);
  const cl=v=>Math.min(W-34,Math.max(34,v)),anch=v=>v<W/2?'start':'end',off=v=>v<W/2?v-2:v+2;
  const far=Math.abs(x(o)-x(f))>=84;
  const zoneW=Math.max(0,x(fl)-X0);
  return `<svg viewBox="0 0 ${W} 100" role="img" aria-label="Rate ladder: opened at ${o}%, ${c.status==='Won'?'closed':'last offer'} at ${f}%, floor ${fl}%, break-even ${be}%">
    <defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="#F3F6FB"/><line x1="0" y1="0" x2="0" y2="6" stroke="#DCE4EF" stroke-width="2"/></pattern></defs>
    <rect class="zone" x="${X0}" y="40" width="${zoneW.toFixed(1)}" height="24" rx="3"/>
    ${zoneW>78?`<text class="zt" x="${X0+5}" y="37">below your floor</text>`:''}
    <line class="axis" x1="${X0}" y1="52" x2="${X1}" y2="52"/>
    <line class="tickl" x1="${x(be).toFixed(1)}" y1="45" x2="${x(be).toFixed(1)}" y2="59"/>
    <line class="tickl" x1="${x(fl).toFixed(1)}" y1="42" x2="${x(fl).toFixed(1)}" y2="62"/>
    <text class="lbl m" x="${off(x(be)).toFixed(1)}" y="78" text-anchor="${anch(x(be))}">break-even ${be}%</text>
    <text class="lbl" x="${off(x(fl)).toFixed(1)}" y="94" text-anchor="${anch(x(fl))}">your floor ${fl}%</text>
    <path class="move" d="M${x(o).toFixed(1)},45 Q${((x(o)+x(f))/2).toFixed(1)},22 ${x(f).toFixed(1)},45"/>
    <circle class="open" cx="${x(o).toFixed(1)}" cy="52" r="5"/>
    <circle class="fin" cx="${x(f).toFixed(1)}" cy="52" r="6.5"/>
    <text class="lbl m" x="${cl(x(o)).toFixed(1)}" y="${far?14:12}" text-anchor="middle">opened ${o}%</text>
    <text class="lbl p" x="${cl(x(f)).toFixed(1)}" y="${far?14:26}" text-anchor="middle">${c.status==='Won'?'closed':'last'} ${f}%</text>
  </svg>`;
}
function roundSteps(c){
  const out=[];
  for(let i=0;i<(c.rounds||0);i++){out.push(`<i class="o" title="Your agent: offer ${i+1}">O</i>`);if(i<(c.counters||0))out.push('<span class="ln"></span>',`<i class="c" title="Borrower agent: counter ${i+1}">C</i>`);if(i<(c.rounds||0)-1)out.push('<span class="ln"></span>')}
  out.push('<span class="ln"></span>',`<i class="end ${c.status==='Won'?'won':''}">${c.status==='Won'?'Accepted':c.status==='Lost'?'Went elsewhere':'No deal'}</i>`);
  return out.join('');
}
function renderDetail(){
  const el=$('caseDetail');if(!el)return;const c=caseById(state.selected)||state.cases[0];
  if(!c){el.innerHTML='<p class="fine">No applications yet.</p>';return}
  const review=needsReview(c),b=c.books;
  const story=c.final&&b?`${c.status==='Won'?'Closed':'Last offer'} ${(c.final.apr-b.break_even_apr).toFixed(2)} pts above break-even, ${(c.final.apr-b.floor_apr).toFixed(2)} above your floor. Conceded ${(c.opening.apr-c.final.apr).toFixed(2)} pts${c.final.autopay?' for autopay':''}.`:'';
  el.innerHTML=`<div class="detail-top"><div><div class="eyebrow">Application detail</div><h3>${safe(c.id)}</h3><p>${safe(c.band)} · ${safe(c.risk)} · passport only, no name or SSN</p></div>${statusPill(c)}</div>
  <div class="amount-box"><div><small>Requested</small><b>${money(c.request.amount)}</b></div><span>${safe(c.request.terms)}${c.final?`<br>you offered ${money(c.final.amount)} · ${safe(c.final.term_months)} mo`:''}</span></div>
  <div class="signals">${(c.signals||[]).map(s=>`<span>${safe(s)}</span>`).join('')}</div>
  ${c.final&&b?`<div class="ladder"><h4>Rate ladder</h4>${ladder(c)}<p class="ladder-note">${safe(story)}</p></div>`:''}
  ${c.opening?`<div class="rounds"><h4>Negotiation, message by message</h4><div class="round-steps">${roundSteps(c)}</div><p>O = your agent's offer, C = the borrower agent's counter. The referee checked each one.</p></div>`:''}
  <div class="rows">${c.final?drow('Rounds',`${c.rounds} offers · ${c.counters} counters`)+drow('Rival quotes shown to you',c.verified_quotes?`${c.verified_quotes} (anonymous, verified)`:'none'):drow('Decision',c.decline_code?readable(c.decline_code):c.status)}
  ${b?drow('Default probability',`${(b.probability_of_default*100).toFixed(1)}%`)+drow('Your style',b.concession_style):''}</div>
  <hr class="divider">
  ${(c.exceptions||[]).length?c.exceptions.map(x=>`<div class="note${review?' warn':''}"><b>${safe(x.title)}</b><p>${safe(x.note)}</p>${typeof x.action==='string'&&x.action?`<p><b>Next:</b> ${safe(x.action)}</p>`:''}</div>`).join(''):`<div class="note"><b>${c.status==='Declined'?'Why you declined':'Nothing to review'}</b><p>${safe(c.decline_reason||'Your agent stayed inside your books; nothing needs a human before funding.')}</p></div>`}
  <div class="detail-actions">${review?'<button class="btn primary small" type="button" id="resolveCase">Mark reviewed</button>':''}<button class="btn ghost small" type="button" id="askAbout">Ask the desk about this</button></div>
  <p class="fine">You never learn which lender won, or the borrower's limits. Funding and identity steps are simulated.</p>`;
  $('resolveCase')?.addEventListener('click',()=>{state.resolved.add(c.id);counts();renderRows();renderBrief();toast('Marked reviewed · ready to fund (simulated)')});
  $('askAbout')?.addEventListener('click',()=>{goTo('desk');ask(`Tell me about ${c.id}`)});
}

// ---------- desk (chat) ----------
function formatReply(text){
  const linkify=s=>s.replace(/APP-[0-9A-F]{6}/g,m=>caseById(m)?`<button type="button" class="inline-ref" data-pick="${m}">${m}</button>`:m);
  return String(text||'').trim().split(/\n{2,}/).map(par=>{
    const lines=par.split('\n');
    if(lines.every(l=>/^\s*[-*]\s+/.test(l)))return `<ul>${lines.map(l=>`<li>${linkify(safe(l.replace(/^\s*[-*]\s+/,'')))}</li>`).join('')}</ul>`;
    const head=[],items=[];lines.forEach(l=>(/^\s*[-*]\s+/.test(l)?items:items.length?items:head).push(l));
    return `${head.length?`<p>${head.map(l=>linkify(safe(l))).join('<br>')}</p>`:''}${items.length?`<ul>${items.map(l=>`<li>${linkify(safe(l.replace(/^\s*[-*]\s+/,'')))}</li>`).join('')}</ul>`:''}`;
  }).join('');
}
const SRC={claude:'Claude · reads console data only',rules:'Rule-based desk · no AI',local:'Rule-based desk, offline · no AI'};
function addMsg(role,text,meta={}){
  const log=$('chatLog'),div=document.createElement('div');
  div.className='msg '+(role==='user'?'user':'agent');
  if(role==='user')div.textContent=text;
  else{
    const refs=(meta.refs||[]).filter((r,i,a)=>a.indexOf(r)===i).slice(0,10);
    div.innerHTML=formatReply(text)+`<div class="msg-meta"><span class="src">${safe(SRC[meta.source]||SRC.rules)}</span>${refs.map(r=>caseById(r)?`<button type="button" class="ref" data-pick="${safe(r)}" aria-label="Open application ${safe(r)}">${safe(r)}</button>`:'').join('')}</div>`;
    div.querySelectorAll('[data-pick]').forEach(b=>b.addEventListener('click',()=>select(b.dataset.pick,'chat')));
  }
  log.appendChild(div);log.scrollTop=log.scrollHeight;return div;
}
function resetChat(){
  state.chat=[];$('chatLog').innerHTML='';
  const g=LC.desk('summary',state);
  addMsg('agent',`Here is where your desk stands.\n\n${g.reply}`,{source:'local',refs:g.refs});
}
async function ask(q){
  q=String(q||'').trim();if(!q||state.busy)return;
  state.busy=true;$('chatSend').disabled=true;
  addMsg('user',q);state.chat.push({role:'user',content:q});
  const typing=document.createElement('div');typing.className='msg agent typing';typing.setAttribute('aria-label','Desk agent is answering');typing.innerHTML='<i></i><i></i><i></i>';
  $('chatLog').appendChild(typing);$('chatLog').scrollTop=$('chatLog').scrollHeight;
  let res=null;
  try{
    const r=await getJSON(`/api/lender/${encodeURIComponent(state.lenderId)}/ask`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({messages:state.chat})});
    if(r&&typeof r.reply==='string'&&r.reply.trim())res={reply:r.reply,source:r.source==='claude'?'claude':'rules',refs:Array.isArray(r.refs)?r.refs:[]};
  }catch(e){}
  if(!res){const l=LC.desk(q,state);res={reply:l.reply,refs:l.refs,source:'local'}}
  typing.remove();addMsg('agent',res.reply,res);state.chat.push({role:'assistant',content:res.reply});
  state.busy=false;$('chatSend').disabled=false;
}

// ---------- chrome: toast, scrollspy, reveal, fab ----------
function toast(message){const el=$('toast');if(!el)return;el.textContent=message;el.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove('show'),2600)}
function setupObservers(){
  if(!('IntersectionObserver' in window))return;
  const links=[...document.querySelectorAll('.nav a[data-sec]')];
  const spy=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting)links.forEach(a=>a.classList.toggle('active',a.dataset.sec===e.target.id))})},{rootMargin:'-35% 0px -55% 0px'});
  ['desk','web','activity','queue'].forEach(id=>$(id)&&spy.observe($(id)));
  const fab=$('askFab');
  new IntersectionObserver(es=>es.forEach(e=>fab.classList.toggle('hide',e.isIntersecting)),{threshold:.25}).observe($('desk'));
  if(reduced())return;
  document.documentElement.classList.add('js-reveal');
  const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.classList.remove('pending');io.unobserve(e.target)}}),{rootMargin:'0px 0px -6% 0px'});
  document.querySelectorAll('.reveal').forEach(el=>{if(el.getBoundingClientRect().top>window.innerHeight){el.classList.add('pending');io.observe(el)}});
}

$('suggest').innerHTML=SUGGEST.map(s=>`<button type="button">${safe(s)}</button>`).join('');
$('suggest').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>ask(b.textContent)));
$('composer').addEventListener('submit',e=>{e.preventDefault();const i=$('chatInput');const q=i.value;i.value='';ask(q)});
$('chatReset').addEventListener('click',()=>{resetChat();$('chatInput').focus()});
$('askFab').addEventListener('click',e=>{e.preventDefault();goTo('desk',$('chatInput'))});
document.querySelectorAll('.filter').forEach(b=>b.addEventListener('click',()=>setFilter(b.dataset.filter)));
$('search').addEventListener('input',renderRows);
$('lenderPick').addEventListener('change',e=>{state.lenderId=e.target.value;state.resolved=new Set();state.selected=null;const u=new URL(location.href);u.searchParams.set('lender',state.lenderId);history.replaceState(null,'',u);$('webSelect').hidden=true;load()});
$('refresh').addEventListener('click',()=>{load().then(()=>toast('Desk refreshed'))});
document.querySelectorAll('.nav a[data-sec]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();goTo(a.dataset.sec,a.dataset.sec==='desk'?$('chatInput'):null);history.replaceState(null,'',location.pathname+location.search+'#'+a.dataset.sec)}));
setupObservers();
load();
LC.ask=ask;LC.select=select;
})();
