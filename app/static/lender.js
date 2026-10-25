// Lender console: one lender's side of every CRS sandbox session (GET /api/lender/{id}).
// It only ever receives what the lender saw: the passport, its own offers and books, anonymous quotes, the outcome.
let cases=[],data=null,filter='All',selected=null,resolved=new Set();
let lenderId=new URLSearchParams(location.search).get('lender')||'campus_cu';
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=t=>t?`${t.apr}%`:'—';
const money=n=>'$'+Number(n).toLocaleString();
const RISK={Strong:['#e8f4df','#50753b'],Good:['#edf2fc','#58719f'],Fair:['#fff1e8','#a96842'],Weak:['#fdecec','#a4383d'],Thin:['#f3effb','#6b55a3']};
const initials=n=>n.split(/\s+/).map(w=>w[0]).join('').slice(0,2).toUpperCase();
const needsReview=c=>c.attention&&!resolved.has(c.id);

async function load(){
  document.getElementById('rowCount').textContent='Loading...';
  try{const r=await fetch(`/api/lender/${encodeURIComponent(lenderId)}`);if(!r.ok)throw new Error(r.status);data=await r.json();}
  catch(e){document.getElementById('heroMotive').textContent='Couldn’t load the queue ('+e.message+').';return}
  cases=data.cases;selected=(cases[0]||{}).id;
  const L=data.lender,pick=document.getElementById('lenderPick');
  pick.innerHTML=data.lenders.map(l=>`<option value="${safe(l.id)}"${l.id===L.id?' selected':''}>${safe(l.name)}</option>`).join('');
  document.getElementById('heroTitle').textContent=L.name;
  document.getElementById('heroMotive').textContent=L.motive;
  document.getElementById('lenderNameSide').textContent=L.name;
  document.getElementById('lenderInitials').textContent=initials(L.name);
  const s=data.stats;
  document.getElementById('mApps').textContent=s.applications;
  document.getElementById('mGate').textContent=`${s.blocked_at_gate} stopped at the CRS gate, never shown to you`;
  document.getElementById('mOffered').textContent=s.offered;
  document.getElementById('mWon').textContent=s.won;
  document.getElementById('mVolume').textContent=`${L.volume.booked} of ${L.volume.target} booked this month`;
  counts();renderRows();
}
function counts(){
  const n=f=>visibleCases(f,'').length;
  for(const [id,f] of [['fAll','All'],['fReview','Review'],['fWon','Won'],['fLost','Lost'],['fDeclined','Declined']])document.getElementById(id).textContent=n(f);
  const open=cases.filter(needsReview).length;
  document.getElementById('exceptionCount').textContent=open;document.getElementById('metricExceptions').textContent=open;
}
function setFilter(next){filter=next;document.querySelectorAll('.filter').forEach(b=>b.classList.toggle('active',b.dataset.filter===next));renderRows()}
function visibleCases(f=filter,q=(document.getElementById('search')?.value||'').toLowerCase()){
  return cases.filter(c=>(f==='All'||(f==='Review'?needsReview(c):f==='Declined'?['Declined','No deal'].includes(c.status):c.status===f))
    &&(!q||`${c.id} ${c.band} ${c.stage}`.toLowerCase().includes(q)))}
function statusPill(c){
  if(needsReview(c))return '<span class="status review">Review</span>';
  return c.status==='Won'?'<span class="status done">Won</span>':c.status==='Lost'?'<span class="status active">Lost</span>':`<span class="status" style="background:#f1f3f2;color:#6b7775">${safe(c.status)}</span>`;
}
function renderRows(){
  const body=document.getElementById('caseRows');if(!body)return;const rows=visibleCases();
  document.getElementById('rowCount').textContent=`Showing ${rows.length} of ${cases.length} applications · CRS sandbox sessions`;
  body.innerHTML=rows.length?rows.map(c=>{const [bg,fg]=RISK[c.risk]||RISK.Good;return `<tr data-id="${safe(c.id)}" class="${c.id===selected?'selected':''}" tabindex="0"><td><div class="borrower-cell"><div class="avatar">${safe(c.id.slice(4,6))}</div><div><b>${safe(c.id)}</b><small>${safe(c.band)}</small></div></div></td><td class="mono">${money(c.request.amount)}</td><td><span class="tag" style="background:${bg};color:${fg}">${safe(c.risk)}</span></td><td class="stage">${safe(c.stage)}</td><td class="mono">${c.final?safe(pct(c.opening)+' → '+pct(c.final)):'—'}</td><td>${statusPill(c)}</td></tr>`}).join(''):'<tr><td colspan="6" class="queue-empty">No applications match this view.</td></tr>';
  body.querySelectorAll('tr[data-id]').forEach(row=>{const go=()=>{selected=row.dataset.id;renderRows()};row.addEventListener('click',go);row.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}})});
  renderDetail();
}
function row(k,v){return `<div class="detail-row"><span>${safe(k)}</span><b>${safe(v)}</b></div>`}
function renderDetail(){
  const el=document.getElementById('caseDetail');if(!el)return;const c=cases.find(x=>x.id===selected)||cases[0];
  if(!c){el.innerHTML='<p class="footnote">No applications.</p>';return}
  const review=needsReview(c),b=c.books;
  el.innerHTML=`<div class="card-head"><div class="eyebrow">Application detail</div><span class="demo-pill">${safe(c.id)}</span></div>
  <div class="case-head" style="margin-top:18px"><div class="avatar">${safe(c.id.slice(4,6))}</div><div><h3>${safe(c.band)} · ${safe(c.risk)}</h3><p>Passport only · no name, SSN or contact</p></div><span class="detail-status status ${review?'review':c.status==='Won'?'done':'active'}">${review?'Review':safe(c.status)}</span></div>
  <div class="detail-amount"><small>Requested</small><b>${money(c.request.amount)}</b><span>${safe(c.request.terms)} · ${safe(c.signals.join(' · '))}</span></div>
  <div class="detail-rows">${c.final?row('Your opening → final',`${pct(c.opening)} → ${pct(c.final)}${c.final.autopay?' (autopay)':''}`)+row('Rounds',`${c.rounds} offers · ${c.counters} counters`)+row('Rival quotes you were shown',c.verified_quotes?`${c.verified_quotes} (anonymous, verified)`:'none'):row('Decision',c.decline_code||c.status)}
  ${b?row('Your break-even / floor',`${b.break_even_apr}% / ${b.floor_apr}%`)+row('Default probability',`${(b.probability_of_default*100).toFixed(1)}%`)+row('Your style',b.concession_style):''}</div>
  <hr class="divider">
  ${c.exceptions.length?c.exceptions.map(x=>`<div class="case-note" style="margin-bottom:10px"><b>${safe(x.title)}</b><p>${safe(x.note)}</p></div>`).join(''):`<div class="case-note"><b>${c.status==='Declined'?'Why you declined':'Nothing to review'}</b><p>${safe(c.decline_reason||'Your agent stayed inside your books; nothing needs a human before funding.')}</p></div>`}
  ${review?'<div class="case-actions"><button class="button lime small" id="resolveCase">Mark reviewed</button></div>':''}
  <p class="footnote" style="margin-bottom:0">You never learn which lender won, or the borrower's limits. Funding and identity steps are simulated.</p>`;
  document.getElementById('resolveCase')?.addEventListener('click',()=>{resolved.add(c.id);counts();renderRows();toast('Marked reviewed · ready to fund (simulated)')});
}
function toast(message){const el=document.getElementById('toast');if(!el)return;el.textContent=message;el.classList.add('show');clearTimeout(window.toastTimer);window.toastTimer=setTimeout(()=>el.classList.remove('show'),2300)}
document.getElementById('search')?.addEventListener('input',renderRows);
document.getElementById('lenderPick')?.addEventListener('change',e=>{lenderId=e.target.value;resolved=new Set();const u=new URL(location.href);u.searchParams.set('lender',lenderId);history.replaceState(null,'',u);load()});
document.getElementById('refresh')?.addEventListener('click',()=>{load();toast('Queue refreshed')});
load();
