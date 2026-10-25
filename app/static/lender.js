// Lender console: one lender's side of every CRS sandbox session.
// GET /api/lender/{id} (queue), GET /api/lender/{id}/network (CRS checks, agents, referee), /live/stream (SSE),
// POST /api/lender/{id}/ask (desk agent). Only hashed APP ids. Sealed market: other lenders never appear. All server text is escaped.
(function(){
'use strict';
const LC=window.LC=window.LC||{};
const $=id=>document.getElementById(id);
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=n=>'$'+Number(n||0).toLocaleString();
const apr=v=>v==null?'—':Number(v).toFixed(2)+'%';
const reduced=()=>window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
const wide=()=>window.matchMedia('(min-width: 1280px)').matches;
const phone=()=>window.matchMedia('(max-width: 760px)').matches;
const SVGNS='http://www.w3.org/2000/svg';

const state=LC.state={data:null,cases:[],net:null,filter:'All',selected:null,resolved:new Set(),chat:[],busy:false,
  lenderId:new URLSearchParams(location.search).get('lender')||'campus_cu',loadedFor:null};
const caseById=id=>state.cases.find(c=>c.id===id)||null;
const needsReview=c=>!!c.attention&&!state.resolved.has(c.id);
async function getJSON(url,opt){const r=await fetch(url,opt);if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}

// outcome -> visual class
const OUT={Won:'won',Lost:'grey','No deal':'offered',Declined:'grey'};
function outcomePill(c){
  const cls=c.status==='Won'?'won':c.status==='No deal'?'offered':'';
  return `<span class="pill ${cls}">${safe(c.status)}</span>`;
}
const riskPill=r=>r?`<span class="pill risk">${safe(r)}</span>`:'';
function shortReason(c){
  const x=(c.exceptions||[])[0];
  const t=x&&x.title?x.title:'Flagged for review';
  return t.split(/\s+/).slice(0,5).join(' ');
}

// ---------- load ----------
async function load(){
  const id=encodeURIComponent(state.lenderId);
  const [lr,nr]=await Promise.allSettled([getJSON(`/api/lender/${id}`),getJSON(`/api/lender/${id}/network`)]);
  if(lr.status!=='fulfilled'){
    $('lenderName').textContent='Couldn’t load';
    $('needsList').innerHTML=`<li><span class="err">Load failed.</span> <button class="btn sm" type="button" id="retry">Retry</button></li>`;
    $('retry').addEventListener('click',load);return;
  }
  const d=state.data=lr.value;state.cases=Array.isArray(d.cases)?d.cases:[];
  const n=nr.status==='fulfilled'?nr.value:null;
  state.net=(n&&Array.isArray(n.nodes)&&n.nodes.length)?n:deriveNetwork();
  const L=d.lender||{};
  $('lenderPick').innerHTML=(d.lenders||[]).map(l=>`<option value="${safe(l.id)}"${l.id===L.id?' selected':''}>${safe(l.name)}</option>`).join('');
  $('lenderName').textContent=L.name||'Lender console';
  const v=L.volume||{};
  $('lenderLine').textContent=v.target?`${v.booked} of ${v.target} loans booked this month`:'One lender’s side of every session';
  $('lenderLine').title=L.motive||'';
  document.title=`${L.name||'Lender'} · Lender console`;
  renderNeeds();renderMetrics();renderTabs();renderRows();renderNetwork();renderFunnel();renderFeed();
  if(state.loadedFor!==state.lenderId){state.loadedFor=state.lenderId;resetChat();initLive()}
}

// Fallback network built from the lender's own cases if the network feed is unavailable.
function deriveNetwork(){
  const d=state.data,s=d.stats||{},nodes=[{id:'you',kind:'you',label:(d.lender||{}).name,messages:0,deals:0}],edges=[];
  const K={Won:'won',Lost:'lost','No deal':'offered',Declined:'declined'};
  state.cases.forEach(c=>{const m=c.opening?(c.rounds||0)+(c.counters||0)+1:1;
    nodes.push({id:c.id,kind:'applicant',status:c.status,risk:c.risk,messages:m});
    edges.push({source:'you',target:c.id,messages:m,kind:K[c.status]||'offered'});nodes[0].messages+=m;});
  for(let i=0;i<(s.blocked_at_gate||0);i++)nodes.push({id:'gate-'+(i+1),kind:'applicant',status:'Blocked',messages:0});
  return {nodes,edges,recent:[],stats:{borrower_agents:state.cases.length+(s.blocked_at_gate||0),admitted:state.cases.length,blocked_at_gate:s.blocked_at_gate||0,messages_checked:nodes[0].messages}};
}

// ---------- needs you ----------
function renderNeeds(){
  const list=state.cases.filter(needsReview);
  $('needsList').innerHTML=list.length?list.map(c=>`<li class="need"><span class="id">${safe(c.id)}</span><span class="why" title="${safe((c.exceptions||[]).map(x=>x.note).join(' '))}">${safe(shortReason(c))}</span><button class="btn sm" type="button" data-open="${safe(c.id)}">Review</button></li>`).join('')
    :'<li class="none">Nothing needs you right now</li>';
  $('needsList').querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',()=>openDrawer(b.dataset.open,b)));
}

// ---------- metrics ----------
function counts(){
  const cs=state.cases,offered=cs.filter(c=>c.opening).length,won=cs.filter(c=>c.status==='Won').length;
  const s=(state.net&&state.net.stats)||{},ds=(state.data&&state.data.stats)||{};
  const gate=s.blocked_at_gate??ds.blocked_at_gate??0;
  return {apps:cs.length,offered,won,gate,total:s.borrower_agents??(cs.length+gate),rate:offered?Math.round(100*won/offered):0};
}
function renderMetrics(){
  const k=counts(),v=(state.data.lender||{}).volume||{};
  const M=[
    ['All','Applications',k.apps,`${k.gate} blocked at gate`,'Borrower agents that passed the CRS gate and reached you'],
    ['Offered','Offers made',k.offered,`${k.apps?Math.round(100*k.offered/k.apps):0}% of apps`,'Applications your agent bid on'],
    ['Won','Loans won',k.won,v.target?`${v.booked}/${v.target} month`:'','Borrower agent accepted your offer'],
    ['Won','Win rate',k.rate+'%',`${k.won} of ${k.offered}`,'Loans won ÷ offers made'],
  ];
  $('metrics').innerHTML=M.map(([f,l,val,sub,t],i)=>`<button class="metric" type="button" data-filter="${f}" data-i="${i}" title="${safe(t)}" aria-pressed="false"><span class="k">${safe(l)}</span><span class="v">${safe(val)}</span><span class="s">${safe(sub)}</span></button>`).join('');
  $('metrics').querySelectorAll('.metric').forEach(b=>b.addEventListener('click',()=>{setFilter(b.dataset.filter);$('apps').scrollIntoView({behavior:reduced()?'auto':'smooth',block:'start'})}));
  syncMetricPress();
}
function syncMetricPress(){
  document.querySelectorAll('.metric').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter===state.filter&&state.filter!=='All'&&b.dataset.i!=='3')));
}

// ---------- network (layered flow: CRS checks -> borrower agents -> referee -> you) ----------
// Sealed market: only your agent and the borrower agents it talked to. Other lenders never appear.
const NW={W:900,H:440,SRC:{x:24,w:104,h:28},GATE:{x:214,w:8},APP:{x:360,w:96,h:15},REF:{cx:652,cy:236,w:136,h:66},YOU:{cx:830,cy:236,r:30}};
const G={appY:{},srcY:{},byId:{}};
const f1=v=>Number(v).toFixed(1);
// Horizontal S-curve: leaves and enters level, bends in the middle.
const sCurve=(x1,y1,x2,y2)=>{const m=(x1+x2)/2;return `M${f1(x1)},${f1(y1)} C${f1(m)},${f1(y1)} ${f1(m)},${f1(y2)} ${f1(x2)},${f1(y2)}`};
const refEndY=ay=>NW.REF.cy+(ay-NW.REF.cy)*.22;
function dAR(id,rev){const y=G.appY[id];if(y==null)return null;const a=[NW.APP.x+NW.APP.w,y],b=[NW.REF.cx-NW.REF.w/2,refEndY(y)];return rev?sCurve(b[0],b[1],a[0],a[1]):sCurve(a[0],a[1],b[0],b[1])}
function dRY(rev){const a=NW.REF.cx+NW.REF.w/2,b=NW.YOU.cx-NW.YOU.r,y=NW.REF.cy;return rev?sCurve(b,y,a,y):sCurve(a,y,b,y)}
function appKind(n,e){if(n.status==='Blocked')return 'blocked';if(n.status==='Won'||(e&&e.kind==='won'))return 'won';if(n.status==='No deal'||(e&&e.kind==='offered'))return 'offered';return 'grey'}
const defaultSources=[{product:'tu',label:'TransUnion'},{product:'efx',label:'Equifax'},{product:'exp',label:'Experian'},{product:'idv',label:'Identity'},{product:'fraudfinder',label:'Fraud'},{product:'reverse',label:'Contact'}];
function renderNetwork(){
  const svg=$('netSvg'),net=state.net,s=net.stats||{},{W,H,SRC,GATE,APP,REF,YOU}=NW;
  const sources=Array.isArray(net.sources)&&net.sources.length?net.sources:defaultSources;
  const byId={};net.nodes.forEach(n=>byId[n.id]=n);G.byId=byId;
  const yourEdge={};(net.edges||[]).forEach(e=>{if(e.source==='you')yourEdge[e.target]=e;else if(e.target==='you')yourEdge[e.source]=e});
  const ORDER={won:0,offered:1,grey:2,blocked:3};
  const apps=net.nodes.filter(n=>n.kind==='applicant').map(n=>({n,k:appKind(n,yourEdge[n.id]),e:yourEdge[n.id]}))
    .sort((a,b)=>(ORDER[a.k]-ORDER[b.k])||String(a.n.id).localeCompare(b.n.id));
  const you=byId.you||{};
  const talked=apps.filter(a=>a.e&&a.k!=='blocked').length;
  const total=you.messages??s.messages_checked??apps.reduce((t,a)=>t+(a.n.messages||0),0);
  $('netStats').textContent=`${talked} borrower agents · ${s.messages_checked??total} messages checked`;
  // layout
  const top=40,bot=H-14;
  const aGap=apps.length>1?Math.min(22,(bot-top-APP.h)/(apps.length-1)):0,aTop=(top+bot)/2-aGap*(apps.length-1)/2;
  G.appY={};apps.forEach((a,i)=>G.appY[a.n.id]=aTop+i*aGap);
  const sGap=sources.length>1?Math.min(64,(bot-top-60)/(sources.length-1)):0,sTop=REF.cy-sGap*(sources.length-1)/2;
  G.srcY={};sources.forEach((x,i)=>G.srcY[x.product]=sTop+i*sGap);
  // edges: CRS check -> applicant
  const flagCount={};
  const chk=[];
  apps.forEach(({n})=>{(n.checks||[]).forEach(c=>{const sy=G.srcY[c.product];if(sy==null)return;
    if(c.flag)flagCount[c.product]=(flagCount[c.product]||0)+1;
    chk.push(`<path class="e chk${c.flag?' flag':''}" data-src="${safe(c.product)}" data-app="${safe(n.id)}" d="${sCurve(SRC.x+SRC.w,sy,APP.x,G.appY[n.id])}"/>`)})});
  // flagged on top so the red stays readable
  chk.sort((a,b)=>(a.includes(' flag"')?1:0)-(b.includes(' flag"')?1:0));
  // applicant -> referee (only agents yours talked to; nothing passes the gate for blocked ones)
  const maxM=Math.max(1,...apps.map(a=>(a.e&&a.e.messages)||a.n.messages||0));
  const ar=apps.filter(a=>a.k!=='blocked'&&(a.e||a.n.messages)).map(({n,k,e})=>{
    const m=(e&&e.messages)||n.messages||0;
    return `<path class="e ar ${k}" data-app="${safe(n.id)}" d="${dAR(n.id)}" stroke-width="${f1(1+3*Math.min(1,m/maxM))}"/>`});
  const ryW=Math.min(10,3+(total||0)/12);
  const ry=`<path class="e ry" d="${dRY()}" stroke-width="${f1(ryW)}"/>`;
  // nodes
  const col=(x,t)=>`<text class="col-t" x="${x}" y="14" text-anchor="middle">${t}</text>`;
  const heads=col(SRC.x+SRC.w/2,'CRS checks')+col(GATE.x+GATE.w/2,'Gate')+col(APP.x+APP.w/2,'Borrower agents')+col(REF.cx,'Referee')+col(YOU.cx,'Your agent');
  const gate=`<g class="gate" id="netGate"><rect class="shape" x="${GATE.x}" y="${top-6}" width="${GATE.w}" height="${bot-top+12}" rx="${GATE.w/2}"/></g>`;
  const srcSvg=sources.map(x=>{const y=G.srcY[x.product],fc=flagCount[x.product]||0,n=apps.filter(a=>(a.n.checks||[]).some(c=>c.product===x.product)).length;
    return `<g class="n src" data-id="${safe(x.product)}" tabindex="0" role="img" aria-label="${safe(x.label)}: checked ${n} borrower agents, ${fc} flagged"><rect class="shape" x="${SRC.x}" y="${f1(y-SRC.h/2)}" width="${SRC.w}" height="${SRC.h}" rx="${SRC.h/2}"/><text class="src-t" x="${SRC.x+13}" y="${f1(y+4)}">${safe(x.label)}</text>${fc?`<text class="src-f" x="${SRC.x+SRC.w-12}" y="${f1(y+4)}" text-anchor="end">${fc}</text>`:''}</g>`}).join('');
  const appSvg=apps.map(({n,k,e})=>{const y=G.appY[n.id],click=!!caseById(n.id),flags=(n.checks||[]).filter(c=>c.flag).length;
    const label=`${n.id}, ${k==='blocked'?'stopped at the gate':(n.status||'no outcome')}, ${(e&&e.messages)||n.messages||0} messages, ${flags} checks flagged`;
    return `<g class="n app ${k}${click?' click':''}${n.id===state.selected?' sel':''}" data-id="${safe(n.id)}" tabindex="0" role="${click?'button':'img'}" aria-label="${safe(label)}"><rect class="shape" x="${APP.x}" y="${f1(y-APP.h/2)}" width="${APP.w}" height="${APP.h}" rx="${APP.h/2}"/><text class="app-t" x="${APP.x+APP.w/2}" y="${f1(y+3.3)}" text-anchor="middle">${safe(n.id)}</text></g>`}).join('');
  const rx=REF.cx-REF.w/2,ryy=REF.cy-REF.h/2;
  const ref=`<g class="n ref" data-id="referee" tabindex="0" role="img" aria-label="Referee: rules, no AI. ${s.messages_checked??total} messages checked, ${s.messages_blocked??0} blocked"><rect class="shape" x="${rx}" y="${ryy}" width="${REF.w}" height="${REF.h}" rx="20"/><text class="ref-t" x="${REF.cx}" y="${REF.cy-6}" text-anchor="middle">Referee</text><text class="ref-s" x="${REF.cx}" y="${REF.cy+10}" text-anchor="middle">rules, no AI</text><text class="ref-m" x="${REF.cx}" y="${REF.cy+24}" text-anchor="middle">${safe(s.messages_checked??total)} checked</text>
    <g class="verdict" transform="translate(${rx+REF.w-6},${ryy+6})" aria-hidden="true"><circle r="10"/><path class="ok-p" d="M-4.5,0.5 L-1.2,3.8 L4.6,-3"/><path class="no-p" d="M-3.6,-3.6 L3.6,3.6 M3.6,-3.6 L-3.6,3.6"/></g></g>`;
  const name=String(you.label||(state.data&&state.data.lender||{}).name||'');
  const youSvg=`<g class="n you" data-id="you" tabindex="0" role="img" aria-label="Your agent, ${you.messages??0} messages, ${you.deals??0} deals"><circle class="shape" cx="${YOU.cx}" cy="${YOU.cy}" r="${YOU.r}"/><text class="you-t" x="${YOU.cx}" y="${YOU.cy+4}" text-anchor="middle">You</text><text class="you-s" x="${YOU.cx}" y="${YOU.cy+YOU.r+16}" text-anchor="middle">${safe(name.length>20?name.slice(0,19)+'…':name)}</text><text class="you-m" x="${YOU.cx}" y="${YOU.cy+YOU.r+30}" text-anchor="middle">${safe(you.deals??0)} deals</text></g>`;
  svg.innerHTML=`${heads}<g class="edges">${chk.join('')}${ar.join('')}${ry}</g>${gate}<g class="live"></g><g class="nodes">${srcSvg}${appSvg}${ref}${youSvg}</g>`;
  svg.setAttribute('aria-label',`Flow from ${sources.length} CRS checks through the gate to ${apps.length} borrower agents, through the referee, to your agent. Other lenders are sealed off.`);
  wireNetwork(svg,apps);
}
function wireNetwork(svg,apps){
  const tip=$('netTip'),stage=$('netStage'),byId=G.byId;
  const q=sel=>svg.querySelectorAll(sel);
  const hl=el=>el&&el.classList.add('hl');
  const pathFor=id=>{
    hl(svg.querySelector(`.n.app[data-id="${CSS.escape(id)}"]`));
    q(`.e.chk[data-app="${CSS.escape(id)}"]`).forEach(e=>{hl(e);hl(svg.querySelector(`.n.src[data-id="${CSS.escape(e.dataset.src)}"]`))});
    const a=svg.querySelector(`.e.ar[data-app="${CSS.escape(id)}"]`);
    if(a){hl(a);hl(svg.querySelector('.e.ry'));hl(svg.querySelector('.n.ref'));hl(svg.querySelector('.n.you'))}
  };
  const place=(g,html)=>{
    tip.innerHTML=html;
    const r=g.getBoundingClientRect(),sr=stage.getBoundingClientRect();
    const x=Math.max(70,Math.min(sr.width-70,r.left-sr.left+r.width/2));
    tip.style.left=x+'px';tip.style.top=(r.top-sr.top-4)+'px';tip.hidden=false;
  };
  const show=g=>{
    const id=g.dataset.id;svg.classList.add('dim');q('.hl').forEach(x=>x.classList.remove('hl'));
    if(g.classList.contains('app')){
      pathFor(id);const n=byId[id]||{},flags=(n.checks||[]).filter(c=>c.flag).length,a=apps.find(x=>x.n.id===id);
      const m=(a&&a.e&&a.e.messages)||n.messages||0,st=n.status==='Blocked'?'Stopped at gate':(n.status||'—');
      place(g,`<b>${safe(id)}</b> <span>· ${safe(st)} · ${m} msgs · ${flags} of ${(n.checks||[]).length} checks flagged</span>`);
    }else if(g.classList.contains('src')){
      hl(g);let n=0,fl=0;
      q(`.e.chk[data-src="${CSS.escape(id)}"]`).forEach(e=>{hl(e);n++;if(e.classList.contains('flag'))fl++;hl(svg.querySelector(`.n.app[data-id="${CSS.escape(e.dataset.app)}"]`))});
      place(g,`<b>${safe(g.querySelector('.src-t').textContent)}</b> <span>· checked ${n} borrower agents · ${fl} flagged</span>`);
    }else if(g.classList.contains('ref')){
      hl(g);q('.e.ar,.e.ry').forEach(hl);hl(svg.querySelector('.n.you'));apps.forEach(a=>{if(svg.querySelector(`.e.ar[data-app="${CSS.escape(a.n.id)}"]`))hl(svg.querySelector(`.n.app[data-id="${CSS.escape(a.n.id)}"]`))});
      const s=state.net.stats||{};
      place(g,`<b>Referee</b> <span>· deterministic rules · ${s.messages_checked??0} checked · ${s.messages_blocked??0} blocked</span>`);
    }else{
      hl(g);q('.e.ar,.e.ry').forEach(hl);hl(svg.querySelector('.n.ref'));
      apps.forEach(a=>{if(svg.querySelector(`.e.ar[data-app="${CSS.escape(a.n.id)}"]`))hl(svg.querySelector(`.n.app[data-id="${CSS.escape(a.n.id)}"]`))});
      const y=byId.you||{};place(g,`<b>Your agent</b> <span>· ${y.messages??0} msgs · ${y.deals??0} deals</span>`);
    }
  };
  const hide=()=>{svg.classList.remove('dim');q('.hl').forEach(x=>x.classList.remove('hl'));tip.hidden=true};
  q('.n').forEach(g=>{
    g.addEventListener('mouseenter',()=>show(g));g.addEventListener('mouseleave',hide);
    g.addEventListener('focus',()=>show(g));g.addEventListener('blur',hide);
    if(g.classList.contains('click')){
      const go=()=>{hide();openDrawer(g.dataset.id,g)};
      g.addEventListener('click',go);
      g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}});
    }
  });
}
function markNetSelected(){document.querySelectorAll('#netSvg .n.app').forEach(g=>g.classList.toggle('sel',g.dataset.id===state.selected))}

// ---------- live (server-sent events; quiet at rest, only the negotiating borrower lights up) ----------
// GET /api/lender/{id}/live/stream -> events hello {seq}, session {seq, at, session:{applicant, admitted, checks,
// steps:[{from,to,type,verdict,what}], outcome}}, ping. Falls back to polling GET /live?after=seq if the stream keeps failing.
const LIVE={seq:null,last:null,at:null,es:null,errors:0,poll:null,polls:0,idle:null,token:0,running:false,ago:null};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const liveUrl=after=>`/api/lender/${encodeURIComponent(state.lenderId)}/live${after!=null?`?after=${encodeURIComponent(after)}`:''}`;
function setLiveState(st){
  const el=$('liveState');if(!el)return;el.dataset.state=st;
  $('liveText').textContent=st==='live'?'Live':st==='polling'?'Live (polling)':st==='connecting'?'Connecting…':'Reconnecting…';
}
function renderAgo(){
  const el=$('lastAgo');if(!el)return;
  if(!LIVE.at){el.textContent='';return}
  const s=Math.max(0,Math.round(Date.now()/1000-LIVE.at));
  el.textContent='Last session '+(s<5?'just now':s<60?`${s}s ago`:s<3600?`${Math.floor(s/60)}m ago`:`${Math.floor(s/3600)}h ago`);
}
function closeStream(){if(LIVE.es){LIVE.es.close();LIVE.es=null}}
function stopPolling(){clearTimeout(LIVE.poll);LIVE.poll=null}
function stopLive(){closeStream();stopPolling()}
function initLive(){
  stopLive();LIVE.seq=null;LIVE.last=null;LIVE.at=null;LIVE.errors=0;quiet();renderAgo();
  $('replayBtn').disabled=true;
  const lender=state.lenderId;
  getJSON(liveUrl()).then(r=>{
    if(lender!==state.lenderId||!r)return;
    if(r.seq!=null&&(LIVE.seq==null||r.seq>LIVE.seq))LIVE.seq=r.seq;
    if(r.session&&!LIVE.last){LIVE.last=r.session;LIVE.at=r.at||null;$('replayBtn').disabled=false;renderAgo()}
  }).catch(()=>{});
  openStream();
  clearInterval(LIVE.ago);LIVE.ago=setInterval(renderAgo,5000);
}
function openStream(){
  stopLive();
  if(!('EventSource' in window)){startPolling();return}
  const lender=state.lenderId;
  const es=LIVE.es=new EventSource(`/api/lender/${encodeURIComponent(lender)}/live/stream`);
  setLiveState(LIVE.errors?'reconnecting':'connecting');
  const ok=()=>{if(LIVE.es===es){LIVE.errors=0;setLiveState('live')}};
  es.onopen=ok;
  es.addEventListener('ping',ok);
  es.addEventListener('hello',ev=>{
    if(LIVE.es!==es)return;ok();
    let d=null;try{d=JSON.parse(ev.data)}catch(e){}
    if(!d||d.seq==null)return;
    if(LIVE.seq==null)LIVE.seq=d.seq;
    else if(d.seq>LIVE.seq)catchUp(lender);   // a session ran while we were disconnected
  });
  es.addEventListener('session',ev=>{if(LIVE.es!==es)return;let m=null;try{m=JSON.parse(ev.data)}catch(e){return}onSession(m,lender)});
  es.onerror=()=>{
    if(LIVE.es!==es)return;
    LIVE.errors++;setLiveState('reconnecting');
    // EventSource retries on its own; after repeated failures switch to polling
    if(LIVE.errors>=3||es.readyState===2){closeStream();startPolling()}
  };
}
async function catchUp(lender){try{const r=await getJSON(liveUrl(LIVE.seq));onSession(r,lender)}catch(e){}}
function startPolling(){
  stopPolling();setLiveState('polling');LIVE.polls=0;
  const lender=state.lenderId;
  const tick=async()=>{
    if(lender!==state.lenderId)return;
    try{const r=await getJSON(liveUrl(LIVE.seq));setLiveState('polling');onSession(r,lender)}catch(e){setLiveState('reconnecting')}
    if(lender!==state.lenderId||LIVE.es)return;
    // try the stream again every ~30s
    if(++LIVE.polls>=20&&'EventSource' in window){LIVE.errors=1;openStream();return}
    LIVE.poll=setTimeout(tick,1500);
  };
  LIVE.poll=setTimeout(tick,1500);
}
let liveQueue=Promise.resolve();
function onSession(m,lender){
  if(!m||m.seq==null||lender!==state.lenderId)return;
  if(LIVE.seq==null){LIVE.seq=m.seq;return}
  if(m.seq<=LIVE.seq)return;
  LIVE.seq=m.seq;
  if(!m.session)return;
  LIVE.last=m.session;LIVE.at=m.at||Date.now()/1000;$('replayBtn').disabled=false;renderAgo();
  // refresh the counts first so the new session is in the graph, then animate it
  liveQueue=liveQueue.then(async()=>{try{await load()}catch(e){}if(lender===state.lenderId&&LIVE.last===m.session)play(m.session)});
}
function caption(text,mode){
  const c=$('netCaption');c.textContent=text;c.title=text;
  c.className='cap-text '+(mode==='bad'?'bad':mode==='on'?'on':'muted');
}
const whoLive=x=>String(x||'')==='you'?'You':'Borrower';
function nodeEl(sel){return $('netSvg').querySelector(sel)}
function lit(el,...cls){if(el)el.classList.add('on',...cls);return el}
function travel(d,ms,tok,cls){
  return new Promise(res=>{
    const layer=$('netSvg').querySelector('.live');
    if(!layer||!d||ms<=0)return res(null);
    const guide=document.createElementNS(SVGNS,'path');guide.setAttribute('d',d);guide.setAttribute('fill','none');guide.setAttribute('stroke','none');layer.appendChild(guide);
    const dot=document.createElementNS(SVGNS,'circle');dot.setAttribute('r','4.2');dot.setAttribute('class','pkt'+(cls?' '+cls:''));layer.appendChild(dot);
    const L=guide.getTotalLength(),t0=performance.now();let done=false;
    const finish=()=>{if(done)return;done=true;clearTimeout(guard);guide.remove();res(dot)};
    // a throttled or hidden tab may starve requestAnimationFrame: never let the timeline stall
    const guard=setTimeout(finish,ms+120);
    const frame=()=>{
      if(done)return;
      const k=Math.min(1,(performance.now()-t0)/ms),e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2,pt=guide.getPointAtLength(e*L);
      dot.setAttribute('cx',pt.x.toFixed(1));dot.setAttribute('cy',pt.y.toFixed(1));
      if(k<1&&tok===LIVE.token)requestAnimationFrame(frame);else finish();
    };
    frame();
  });
}
function verdict(ok){
  const v=nodeEl('.n.ref .verdict');if(!v)return;
  v.classList.remove('ok','no');void v.getBBox();v.classList.add(ok?'ok':'no');
  clearTimeout(verdict.t);verdict.t=setTimeout(()=>v.classList.remove('ok','no'),ok?420:900);
}
async function stepAnim(st,app,blocked,tok){
  const fromYou=st.from==='you';
  const segs=fromYou?[dRY(true),dAR(app,true)]:[dAR(app),dRY()];
  let dot=await travel(segs[0],260,tok);
  if(dot)dot.remove();
  if(tok!==LIVE.token)return;
  verdict(!blocked);
  if(blocked){
    const r=nodeEl('.n.ref');if(r)r.classList.add('bad');
    await sleep(380);if(r)r.classList.remove('bad');return;
  }
  await sleep(80);if(tok!==LIVE.token)return;
  dot=await travel(segs[1],200,tok);if(dot)dot.remove();
  await sleep(40);
}
function clearLive(svg){
  const l=svg.querySelector('.live');if(l)l.innerHTML='';
  svg.querySelectorAll('.on,.bad,.won-path').forEach(el=>el.classList.remove('on','bad','won-path','flag-live'));
  const v=svg.querySelector('.verdict');if(v)v.classList.remove('ok','no');
}
async function play(s,replay){
  if(!s)return;
  const tok=++LIVE.token,still=reduced(),svg=$('netSvg');
  clearTimeout(LIVE.idle);LIVE.running=true;
  clearLive(svg);$('wonChip').hidden=true;
  svg.classList.add('live-on');
  const app=s.applicant,esc=CSS.escape(app);
  const appEl=lit(nodeEl(`.n.app[data-id="${esc}"]`));
  const node=G.byId[app]||{};
  const checks=Array.isArray(s.checks)&&s.checks.length?s.checks:(node.checks||[]);
  caption('Checking the borrower with CRS…','on');
  lit(nodeEl('#netGate'));
  for(const c of checks){
    if(tok!==LIVE.token)return;
    const e=nodeEl(`.e.chk[data-app="${esc}"][data-src="${CSS.escape(c.product)}"]`);
    lit(e,...(c.flag?['flag-live']:[]));lit(nodeEl(`.n.src[data-id="${CSS.escape(c.product)}"]`),...(c.flag?['bad']:[]));
    if(!still)await sleep(120);
  }
  if(tok!==LIVE.token)return;
  if(!s.admitted){
    const g=nodeEl('#netGate');if(g)g.classList.add('bad');
    caption('Stopped at the identity gate','bad');
    LIVE.running=false;LIVE.idle=setTimeout(quiet,20000);return;
  }
  lit(nodeEl(`.e.ar[data-app="${esc}"]`));lit(nodeEl('.e.ry'));lit(nodeEl('.n.ref'));lit(nodeEl('.n.you'));
  const steps=(Array.isArray(s.steps)?s.steps:[]).filter(st=>st.to!=='*');
  if(!steps.length)caption('Borrower agent entered the market','on');
  for(const st of steps){
    if(tok!==LIVE.token)return;
    const blocked=st.verdict==='blocked';
    caption(`${whoLive(st.from)}: ${st.what||st.type||''}${blocked?' · blocked by the referee':''}`,blocked?'bad':'on');
    if(!replay)pushFeed(st);
    if(!still)await stepAnim(st,app,blocked,tok);
  }
  if(tok!==LIVE.token)return;
  const last=steps[steps.length-1];
  if(s.outcome==='won'){
    [appEl,nodeEl(`.e.ar[data-app="${esc}"]`),nodeEl('.e.ry'),nodeEl('.n.you')].forEach(el=>el&&el.classList.add('won-path'));
    $('wonChip').hidden=false;caption('Accepted your offer','on');
  }
  else if(s.outcome==='closed')caption('Borrower agent took another offer','on');
  else if(last)caption(`${whoLive(last.from)}: ${last.what||last.type||''}`,'on');
  LIVE.running=false;
  LIVE.idle=setTimeout(quiet,20000);
}
function pushFeed(st){
  if(!state.net)return;
  const rec=state.net.recent=state.net.recent||[];
  if(rec.slice(-20).some(r=>r.from===st.from&&r.to===st.to&&r.what===st.what))return;
  rec.push({from:st.from,to:st.to,what:st.what,verdict:st.verdict});state.net.recent=rec.slice(-50);renderFeed();
}
function quiet(){
  LIVE.token++;LIVE.running=false;clearTimeout(LIVE.idle);
  const svg=$('netSvg');if(svg){svg.classList.remove('live-on');clearLive(svg)}
  $('wonChip').hidden=true;caption('Waiting for a borrower…');
}
async function simulate(){
  const b=$('simBtn');b.disabled=true;caption('Sending a sample borrower…','on');
  try{await getJSON('/api/exchange/P03');setTimeout(()=>{if(!LIVE.running&&$('netCaption').textContent.startsWith('Sending'))caption('Waiting for a borrower…')},8000)}
  catch(e){caption('Simulation failed','bad')}
  b.disabled=false;
}

// ---------- pipeline ----------
function renderFunnel(){
  const k=counts();
  const S=[['All','Borrower agents',k.total,'#C9D7F0'],['All','Passed gate',k.apps,'var(--blue-2)'],['Offered','Offered',k.offered,'#4F78D1'],['Won','Won',k.won,'var(--primary)']];
  const max=Math.max(1,k.total);
  $('funnel').innerHTML=S.map(([f,l,v,c])=>`<button class="fstep" type="button" data-filter="${f}" title="Show ${safe(l.toLowerCase())} in the table"><span class="fl">${safe(l)}</span><span class="track"><span class="fill" style="display:block;width:${(100*v/max).toFixed(1)}%;background:${c}"></span></span><span class="fv">${safe(v)}</span></button>`).join('');
  $('funnel').querySelectorAll('.fstep').forEach(b=>b.addEventListener('click',()=>{setFilter(b.dataset.filter);$('apps').scrollIntoView({behavior:reduced()?'auto':'smooth',block:'start'})}));
}
function who(x){const s=String(x??'');if(s==='you')return 'You';if(/^APP-/i.test(s))return 'Borrower';return 'Gate'}
function shortWhat(t){
  let s=String(t||'').split(/ on \$|,|:/)[0].trim();
  const w=s.split(/\s+/);if(w.length>5)s=w.slice(0,5).join(' ')+'…';
  return s;
}
function renderFeed(){
  const rec=(state.net.recent||[]).slice(-5).reverse();
  if(!rec.length){$('feed').innerHTML='<li class="muted">No recent activity</li>';return}
  $('feed').innerHTML=rec.map(it=>{
    const app=[it.from,it.to].find(x=>/^APP-/i.test(String(x)))||'';
    const mine=it.from==='you'||it.to==='you',blocked=it.verdict==='blocked';
    const dot=blocked?'style="background:var(--red)"':mine?'style="background:var(--primary)"':'style="background:var(--grey-link)"';
    const idEl=app?(caseById(app)?`<button class="a" type="button" data-open="${safe(app)}" aria-label="Open ${safe(app)}">${safe(app)}</button>`:`<span class="a">${safe(app)}</span>`):'';
    return `<li title="${safe(it.what)}"><i class="dot" ${dot} aria-hidden="true"></i><span class="w"><b>${safe(who(it.from))}</b> ${safe(shortWhat(it.what).replace(/^./,c=>c.toLowerCase()))}${blocked?' · blocked':''}</span>${idEl}</li>`;
  }).join('');
  $('feed').querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',()=>openDrawer(b.dataset.open,b)));
}

// ---------- table ----------
const TABS=[['All','All'],['Review','Needs review'],['Offered','Offered'],['Won','Won'],['Lost','Lost'],['Declined','Declined']];
function match(c,f){
  if(f==='All')return true;if(f==='Review')return needsReview(c);if(f==='Offered')return !!c.opening;
  if(f==='Lost')return c.status==='Lost'||c.status==='No deal';return c.status===f;
}
function visibleCases(){const q=($('search').value||'').trim().toLowerCase();return state.cases.filter(c=>match(c,state.filter)&&(!q||`${c.id} ${c.band} ${c.risk}`.toLowerCase().includes(q)))}
function renderTabs(){
  $('tabs').innerHTML=TABS.map(([f,l])=>`<button class="tab" type="button" role="tab" data-filter="${f}" aria-selected="${f===state.filter}">${safe(l)} <span class="c">${state.cases.filter(c=>match(c,f)).length}</span></button>`).join('');
  $('tabs').querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>setFilter(b.dataset.filter)));
}
function setFilter(f){
  state.filter=f;
  document.querySelectorAll('.tab').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.filter===f)));
  syncMetricPress();renderRows();
}
function renderRows(){
  const rows=visibleCases(),body=$('rows');
  body.innerHTML=rows.length?rows.map(c=>{
    const rate=c.opening?`${Number(c.opening.apr).toFixed(2)}<span class="arrow">→</span>${c.final?apr(c.final.apr):'—'}`:'<span class="muted">—</span>';
    return `<tr data-id="${safe(c.id)}" tabindex="0" class="${c.id===state.selected?'sel':''}" aria-label="${safe(c.id)}, ${safe(c.status)}"><td class="id">${safe(c.id)}${needsReview(c)?'<span class="rdot" title="Needs review"></span>':''}</td><td class="num">${money(c.request&&c.request.amount)}</td><td class="c-risk">${riskPill(c.risk)}</td><td>${outcomePill(c)}</td><td class="num c-rate">${rate}</td></tr>`;
  }).join(''):'<tr><td colspan="5" class="empty">No applications match</td></tr>';
  $('rowCount').textContent=`${rows.length} of ${state.cases.length}`;
  body.querySelectorAll('tr[data-id]').forEach(tr=>{const go=()=>openDrawer(tr.dataset.id,tr);tr.addEventListener('click',go);tr.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}})});
}

// ---------- drawer ----------
let drawerReturn=null;
function rateChart(c){
  const b=c.books,o=c.opening.apr,fi=c.final.apr,fl=b.floor_apr,be=b.break_even_apr;
  const W=372,H=132,X0=8,X1=W-118,Y0=16,Y1=H-16;
  const lo=Math.min(fl,be,fi)-.4,hi=Math.max(o,fi)+.4,y=v=>Y1-(v-lo)/(hi-lo)*(Y1-Y0);
  const n=Math.max(2,c.rounds||2),xs=i=>X0+i*(X1-X0)/(n);
  // only the opening and final rates are known: hold the opening, step once to the final at the last round
  const step=`M${X0},${y(o).toFixed(1)} H${xs(n-1).toFixed(1)} V${y(fi).toFixed(1)} H${X1}`;
  const ref=(v,t,dy)=>`<line class="ref-l" x1="${X0}" x2="${X1}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text class="ref-t" x="${X1+6}" y="${(y(v)+3.5+dy).toFixed(1)}">${t} ${v}%</text>`;
  const close=Math.abs(y(fl)-y(be))<11,dyF=close?(fl>=be?-6:6):0,dyB=close?-dyF:0;
  return `<svg class="rate-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Rate: opened ${o}%, final ${fi}%, floor ${fl}%, break-even ${be}%">
    ${ref(fl,'floor',dyF)}${ref(be,'break-even',dyB)}
    <path class="step" d="${step}"/>
    <circle class="pt o" cx="${X0}" cy="${y(o).toFixed(1)}" r="3.5"/><circle class="pt" cx="${X1}" cy="${y(fi).toFixed(1)}" r="4"/>
    <text class="val" x="${X0+8}" y="${(y(o)-7).toFixed(1)}">${o}%</text>
    <text class="val" x="${X1}" y="${(y(fi)-9).toFixed(1)}" text-anchor="end">${fi}%</text>
  </svg>`;
}
function readable(code){return String(code||'').replace(/_/g,' ').toLowerCase().replace(/^./,c=>c.toUpperCase())}
function renderDrawer(c){
  const review=needsReview(c),b=c.books,t=c.final||c.opening;
  const kv=[];
  kv.push(['Score band',c.band,'txt'],['Risk',c.risk,'txt']);
  if(c.final){kv.push(['Rounds',`${c.rounds} offers · ${c.counters} counters`,'txt']);kv.push(['Term',`${c.final.term_months} mo${c.final.autopay?' · autopay':''}`,'txt'])}
  else kv.push(['Decision',c.decline_code?readable(c.decline_code):c.status,'txt']);
  if(b){kv.push(['Default prob.',(b.probability_of_default*100).toFixed(1)+'%']);kv.push(['Margin',c.final?`${(c.final.apr-b.break_even_apr).toFixed(2)} pts`:'—'])}
  const notes=(c.exceptions||[]).length?c.exceptions.map(x=>`<div class="note${review?' warn':''}"><b>${safe(x.title)}</b><p>${safe(x.note)}</p>${typeof x.action==='string'&&x.action?`<p>${safe(x.action)}</p>`:''}</div>`).join('')
    :c.decline_reason?`<div class="note"><b>Why declined</b><p>${safe(c.decline_reason)}</p></div>`:'';
  $('drawer').innerHTML=`<div class="dr-head"><div class="t"><h2 id="drTitle">${safe(c.id)}</h2>${review?'<span class="pill review">Needs review</span>':outcomePill(c)}</div><button class="icon-btn" id="drClose" type="button" aria-label="Close details"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>
  <div class="dr-body">
    <div class="dr-amount">${money(c.request&&c.request.amount)}</div>
    <p class="muted dr-terms">${safe(c.request&&c.request.terms)}${t&&c.final?` · offered ${money(c.final.amount)}`:''}</p>
    ${c.opening&&c.final&&b?`<div class="dr-sec"><h3 class="label" title="Opening rate to final rate, against your floor and break-even">Rate</h3>${rateChart(c)}</div>`:''}
    <div class="dr-sec"><dl class="kv">${kv.map(([k,v,cl])=>`<dt>${safe(k)}</dt><dd class="${cl||''}">${safe(v)}</dd>`).join('')}</dl></div>
    ${notes?`<div class="dr-sec"><h3 class="label">Notes</h3>${notes}</div>`:''}
    <div class="dr-actions">${review?'<button class="btn primary" type="button" id="resolveCase">Mark reviewed</button>':''}<button class="btn" type="button" id="askAbout"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z"/></svg>Ask about this</button></div>
  </div>`;
  $('drClose').addEventListener('click',closeDrawer);
  $('resolveCase')?.addEventListener('click',()=>{state.resolved.add(c.id);renderNeeds();renderTabs();renderRows();renderDrawer(c);toast('Marked reviewed (simulated)')});
  $('askAbout').addEventListener('click',()=>{closeDrawer(false);openCopilot();ask(`Tell me about ${c.id}`)});
}
function placeDrawer(){
  const r=document.body.classList.contains('cp-push')?getComputedStyle(document.documentElement).getPropertyValue('--cp-w').trim():'0px';
  $('drawer').style.right=r;$('scrim').style.right=r;
}
function openDrawer(id,from){
  const c=caseById(id);if(!c)return;
  state.selected=id;drawerReturn=from||document.activeElement;
  renderDrawer(c);renderRows();markNetSelected();
  const d=$('drawer'),sc=$('scrim');
  d.hidden=false;sc.hidden=false;placeDrawer();
  requestAnimationFrame(()=>{d.classList.add('open');sc.classList.add('show')});
  setTimeout(()=>$('drClose')&&$('drClose').focus({preventScroll:true}),reduced()?0:60);
}
function closeDrawer(restore=true){
  const d=$('drawer'),sc=$('scrim');if(!d.classList.contains('open'))return;
  d.classList.remove('open');sc.classList.remove('show');
  setTimeout(()=>{if(!d.classList.contains('open')){sc.hidden=true}},230);
  if(restore&&drawerReturn&&document.contains(drawerReturn))drawerReturn.focus({preventScroll:true});
}

// ---------- copilot ----------
// Resizable by its left edge: width lives in --cp-w (the push layout and the drawer read it), saved per browser.
const CPW={min:300,def:380,key:'lc.cpWidth',step:24};
const cpMax=()=>Math.max(CPW.min,Math.min(720,Math.round(window.innerWidth*.6)));
let cpW=CPW.def;
function setCpW(w,save){
  cpW=Math.round(Math.min(cpMax(),Math.max(CPW.min,Number(w)||CPW.def)));
  document.documentElement.style.setProperty('--cp-w',cpW+'px');
  const h=$('cpResize');h.setAttribute('aria-valuenow',String(cpW));h.setAttribute('aria-valuemax',String(cpMax()));h.setAttribute('aria-valuetext',cpW+' pixels wide');
  if(save){try{localStorage.setItem(CPW.key,String(cpW))}catch(e){}}
  if($('drawer').classList.contains('open'))placeDrawer();
}
function initResize(){
  const h=$('cpResize');let saved=null;
  try{saved=parseInt(localStorage.getItem(CPW.key),10)}catch(e){}
  setCpW(Number.isFinite(saved)?saved:CPW.def);
  h.addEventListener('pointerdown',e=>{
    if(e.button!==0||phone())return;
    e.preventDefault();try{h.setPointerCapture(e.pointerId)}catch(_){}
    const x0=e.clientX,w0=cpW;let next=w0,raf=0;
    document.body.classList.add('cp-resizing');
    const move=ev=>{next=w0+(x0-ev.clientX);if(!raf)raf=requestAnimationFrame(()=>{raf=0;setCpW(next)})};
    const up=ev=>{
      try{h.releasePointerCapture(ev.pointerId)}catch(_){}
      h.removeEventListener('pointermove',move);h.removeEventListener('pointerup',up);h.removeEventListener('pointercancel',up);
      cancelAnimationFrame(raf);setCpW(next,true);document.body.classList.remove('cp-resizing');
    };
    h.addEventListener('pointermove',move);h.addEventListener('pointerup',up);h.addEventListener('pointercancel',up);
  });
  h.addEventListener('dblclick',()=>{setCpW(CPW.def);try{localStorage.removeItem(CPW.key)}catch(e){}});
  h.addEventListener('keydown',e=>{
    const k=e.key;let w=null;
    if(k==='ArrowLeft')w=cpW+CPW.step;else if(k==='ArrowRight')w=cpW-CPW.step;else if(k==='Home')w=CPW.min;else if(k==='End')w=cpMax();
    if(w==null)return;e.preventDefault();setCpW(w,true);
  });
  window.addEventListener('resize',()=>setCpW(cpW));
}
const CHIPS=[['Summary','Give me a summary'],['Needs review','What needs my review?'],['Win rate',"What's my win rate?"],['Why we lost','Why did we lose deals?'],['Agents connected','How many agents are we connected to?']];
function layoutCopilot(){
  const open=document.body.classList.contains('cp-open');
  document.body.classList.toggle('cp-push',open&&wide());
  document.body.classList.toggle('cp-overlay',open&&!wide());
  $('askToggle').setAttribute('aria-expanded',String(open));$('fab').setAttribute('aria-expanded',String(open));
  if($('drawer').classList.contains('open'))placeDrawer();
}
function openCopilot(focus){document.body.classList.add('cp-open');layoutCopilot();if(focus)setTimeout(()=>$('cpInput').focus({preventScroll:true}),reduced()?0:120)}
function closeCopilot(){document.body.classList.remove('cp-open');layoutCopilot()}
function toggleCopilot(){document.body.classList.contains('cp-open')?closeCopilot():openCopilot(true)}
function setSource(src){const b=$('cpSource');b.textContent=src==='claude'?'Claude':'Rule-based';b.classList.toggle('claude',src==='claude')}
function formatReply(text){
  const link=s=>s.replace(/APP-[0-9A-F]{6}/g,m=>caseById(m)?`<button type="button" class="inline-ref" data-open="${m}">${m}</button>`:m);
  const bullet=/^\s*[-*•]\s+/;
  return String(text||'').trim().split(/\n{2,}/).map(par=>{
    const lines=par.split('\n'),head=[],items=[];
    lines.forEach(l=>(bullet.test(l)?items:items.length?items:head).push(l));
    return (head.length?`<p>${head.map(l=>link(safe(l))).join('<br>')}</p>`:'')+(items.length?`<ul>${items.map(l=>`<li>${link(safe(l.replace(bullet,'')))}</li>`).join('')}</ul>`:'');
  }).join('');
}
function addMsg(role,text,meta={}){
  const log=$('cpLog'),div=document.createElement('div');
  div.className='msg '+(role==='user'?'user':'agent');
  if(role==='user')div.textContent=text;
  else{
    const refs=[...new Set(meta.refs||[])].filter(caseById).slice(0,8);
    div.innerHTML=formatReply(text)+(refs.length?`<div class="refs">${refs.map(r=>`<button type="button" class="ref" data-open="${safe(r)}" aria-label="Open ${safe(r)}">${safe(r)}</button>`).join('')}</div>`:'');
    div.querySelectorAll('[data-open]').forEach(b=>b.addEventListener('click',()=>openDrawer(b.dataset.open,b)));
  }
  log.appendChild(div);log.scrollTop=log.scrollHeight;
}
function resetChat(){
  state.chat=[];$('cpLog').innerHTML='';setSource('rules');
  const open=state.cases.filter(needsReview).length;
  addMsg('agent',`Hi. I read this console’s data only.${open?` ${open} ${open===1?'application needs':'applications need'} you.`:''}`,{refs:state.cases.filter(needsReview).map(c=>c.id)});
}
async function ask(q){
  q=String(q||'').trim();if(!q||state.busy)return;
  state.busy=true;$('cpSend').disabled=true;
  addMsg('user',q);state.chat.push({role:'user',content:q});
  const typing=document.createElement('div');typing.className='msg agent typing';typing.setAttribute('aria-label','Answering');typing.innerHTML='<i></i><i></i><i></i>';
  $('cpLog').appendChild(typing);$('cpLog').scrollTop=$('cpLog').scrollHeight;
  let res=null;
  try{
    const r=await getJSON(`/api/lender/${encodeURIComponent(state.lenderId)}/ask`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({messages:state.chat})});
    if(r&&typeof r.reply==='string'&&r.reply.trim())res={reply:r.reply,source:r.source==='claude'?'claude':'rules',refs:Array.isArray(r.refs)?r.refs:[]};
  }catch(e){}
  if(!res&&typeof LC.desk==='function'){const l=LC.desk(q,state);res={reply:l.reply,refs:l.refs,source:'rules'}}
  if(!res)res={reply:'The desk is unavailable right now.',refs:[],source:'rules'};
  typing.remove();setSource(res.source);addMsg('agent',res.reply,res);state.chat.push({role:'assistant',content:res.reply});
  state.busy=false;$('cpSend').disabled=false;
}

// ---------- misc ----------
function toast(m){const el=$('toast');el.textContent=m;el.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove('show'),2400)}

// ---------- wire up ----------
$('copilot').hidden=false;
initResize();
$('cpChips').innerHTML=CHIPS.map(([l,q])=>`<button type="button" data-q="${safe(q)}">${safe(l)}</button>`).join('');
$('cpChips').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>ask(b.dataset.q)));
$('cpForm').addEventListener('submit',e=>{e.preventDefault();const i=$('cpInput'),q=i.value;i.value='';ask(q)});
$('cpReset').addEventListener('click',()=>{resetChat();$('cpInput').focus()});
$('cpClose').addEventListener('click',()=>{closeCopilot();(phone()?$('fab'):$('askToggle')).focus()});
$('askToggle').addEventListener('click',toggleCopilot);
$('fab').addEventListener('click',()=>openCopilot(true));
$('scrim').addEventListener('click',()=>closeDrawer());
$('replayBtn').disabled=true;
$('replayBtn').addEventListener('click',()=>{if(LIVE.last)play(LIVE.last,true)});
$('simBtn').addEventListener('click',simulate);
$('search').addEventListener('input',renderRows);
$('lenderPick').addEventListener('change',e=>{
  state.lenderId=e.target.value;state.resolved=new Set();state.selected=null;state.filter='All';$('search').value='';
  const u=new URL(location.href);u.searchParams.set('lender',state.lenderId);history.replaceState(null,'',u);closeDrawer(false);load();
});
document.addEventListener('keydown',e=>{
  if(e.key!=='Escape')return;
  if($('drawer').classList.contains('open')){closeDrawer();return}
  if(document.body.classList.contains('cp-open')&&(!wide()||$('copilot').contains(document.activeElement))){closeCopilot();(phone()?$('fab'):$('askToggle')).focus()}
});
let lastWide=wide();
window.addEventListener('resize',()=>{const w=wide();if(w!==lastWide){lastWide=w;layoutCopilot()}});
if(wide())document.body.classList.add('cp-open');
layoutCopilot();
load();
LC.ask=ask;LC.open=openDrawer;
})();
