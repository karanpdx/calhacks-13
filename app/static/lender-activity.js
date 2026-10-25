// Background-process views: the referee ticker (recent agent messages and verdicts) and the outcome flow.
(function(){
  const LC=window.LC=window.LC||{};
  const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const reduced=()=>window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const OK='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>';
  const NO='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>';
  let items=[],cursor=0,timer=null,paused=false,opts={};

  function who(x){
    const s=String(x??'');
    if(s==='you')return 'Your agent';
    const r=s.match(/^rival-([A-Z])$/);if(r)return 'Lender '+r[1];
    if(/^APP-[0-9A-F]{6}$/i.test(s))return opts.isCase&&opts.isCase(s)?`<button type="button" data-pick="${safe(s)}">${safe(s)}</button>`:safe(s);
    if(s==='gate'||s==='crs')return 'CRS gate';
    return safe(s);
  }
  function li(it,enter){
    const ok=it.verdict!=='blocked';
    return `<li class="tick${enter?' enter':''}"><span class="v ${ok?'ok':'no'}">${ok?OK:NO}</span><div><div class="who">${who(it.from)} → ${who(it.to)}</div><div class="what">${safe(it.what)}</div></div><span class="verdict ${ok?'':'no'}">${ok?'Allowed':'Blocked'}</span></li>`;
  }
  function bind(list){
    list.querySelectorAll('[data-pick]').forEach(b=>{if(b.dataset.bound)return;b.dataset.bound='1';b.addEventListener('click',()=>opts.onSelect&&opts.onSelect(b.dataset.pick,'ticker'))});
  }
  const VISIBLE=7;
  function step(){
    const list=document.getElementById('tickList');if(!list||!items.length||paused||document.hidden)return;
    const it=items[cursor%items.length];cursor++;
    list.insertAdjacentHTML('afterbegin',li(it,true));
    while(list.children.length>VISIBLE)list.lastElementChild.remove();
    bind(list);
  }
  function setPaused(p){
    paused=p;const b=document.getElementById('tickerToggle');if(!b)return;
    b.setAttribute('aria-pressed',String(p));b.setAttribute('aria-label',p?'Resume ticker':'Pause ticker');
    b.innerHTML=p?'<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l12-7z"/></svg>':'<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
  }

  function ticker(list,options){
    opts=options||{};items=(list||[]).filter(x=>x&&x.what);cursor=0;clearInterval(timer);
    const el=document.getElementById('tickList'),foot=document.getElementById('tickerFoot'),btn=document.getElementById('tickerToggle');
    if(!el)return;
    const panel=el.closest('.panel');
    if(!items.length){if(panel)panel.hidden=true;return}
    if(panel)panel.hidden=false;
    if(foot)foot.textContent=opts.derived?'Replay built from your own sessions: offers, counters and outcomes, each checked by the referee.':'Replay of the latest referee checks across the exchange.';
    const first=items.slice(0,VISIBLE);cursor=first.length;
    el.innerHTML=first.slice().reverse().map(it=>li(it,false)).join('');bind(el);
    if(reduced()||items.length<=VISIBLE){if(btn)btn.hidden=true;return}
    if(btn){btn.hidden=false;if(!btn.dataset.bound){btn.dataset.bound='1';btn.addEventListener('click',()=>setPaused(!paused))}}
    if(!el.dataset.bound){el.dataset.bound='1';
      el.addEventListener('mouseenter',()=>{el.dataset.hover='1'});el.addEventListener('mouseleave',()=>{delete el.dataset.hover});
      el.addEventListener('focusin',()=>{el.dataset.hover='1'});el.addEventListener('focusout',()=>{delete el.dataset.hover});
    }
    setPaused(false);
    timer=setInterval(()=>{if(!el.dataset.hover)step()},2600);
  }

  // Outcome flow: nested proportional bars; each child row sits under its parent segment.
  function flow(c,options){
    const box=document.getElementById('flowBody');if(!box)return;
    const o=options||{},T=Math.max(1,c.total||0),pc=n=>100*n/T;
    const seg=(key,label,n,left,cls)=>n>0?`<button type="button" class="seg ${cls}" data-act="${key}" style="left:${left.toFixed(3)}%;width:${pc(n).toFixed(3)}%" aria-label="${safe(label)}: ${n}" title="${safe(label)}: ${n}">${n}</button>`:'';
    const keys=list=>`<div class="flow-keys">${list.map(([key,label,n,color])=>`<button type="button" data-act="${key}"><i style="background:${color}"></i>${safe(label)} <b>${n}</b></button>`).join('')}</div>`;
    const guide=(left,n)=>n>0?`<span class="flow-guide" style="left:${left.toFixed(3)}%;width:${pc(n).toFixed(3)}%" aria-hidden="true"></span>`:'';
    const gL=pc(c.gate),oL=gL;
    box.innerHTML=`
      <div class="flow-row"><span class="stage-name">Borrower agents in the exchange</span><div class="flow-track">${seg('all','All borrower agents',c.total,0,'f-all')}</div></div>
      <div class="flow-row"><span class="stage-name">CRS gate (fraud, identity, bureaus)</span><div class="flow-track">${seg('gate','Stopped at the CRS gate',c.gate,0,'f-gate')}${seg('in','Reached you',c.admitted,gL,'f-in')}</div>
        ${keys([['gate','Stopped at gate',c.gate,'var(--red-line)'],['in','Reached you',c.admitted,'#3A5C9E']])}</div>
      <div class="flow-row"><span class="stage-name">Your rules</span><div class="flow-track">${guide(gL,c.admitted)}${seg('offered','You offered',c.offered,oL,'f-offered')}${seg('declined','You declined',c.declined,oL+pc(c.offered),'f-declined')}</div>
        ${keys([['offered','You offered',c.offered,'var(--steel)'],['declined','You declined',c.declined,'var(--mist)']])}</div>
      <div class="flow-row"><span class="stage-name">Negotiation</span><div class="flow-track">${guide(oL,c.offered)}${seg('won','Won',c.won,oL,'f-won')}${seg('lost','Lost to another offer',c.lost,oL+pc(c.won),'f-lost')}${seg('nodeal','No deal',c.nodeal,oL+pc(c.won+c.lost),'f-nodeal')}</div>
        ${keys([['won','Won',c.won,'var(--primary)'],['lost','Lost to another offer',c.lost,'var(--slate)'],['nodeal','No deal',c.nodeal,'var(--tint-2)']])}</div>
      <p class="flow-note">Bars share one scale: width is the share of all ${safe(c.total)} borrower agents.</p>`;
    box.querySelectorAll('[data-act]').forEach(b=>b.addEventListener('click',()=>o.onPick&&o.onPick(b.dataset.act)));
  }

  LC.activity={ticker,flow,stop(){clearInterval(timer)}};
})();
