// Agent web: this lender's agent, anonymous rival lender agents and borrower agents (hashed ids only).
// Plain SVG plus a small hand-written force layout: radial start, a few hundred iterations, then static.
(function(){
  const LC=window.LC=window.LC||{};
  const NS='http://www.w3.org/2000/svg';
  const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let svg,stage,tip,net=null,opts={},pinned=null,selectedId=null,byId={},adj={},liveEdges=[],lastSize='',resizeTimer=null;

  const el=(tag,attrs={})=>{const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);return e};
  const KIND_WORD={won:'won',offered:'offered',lost:'lost to another offer',declined:'you declined'};

  function statusOf(n){
    if(n.kind!=='applicant')return '';
    if(n.status)return n.status;
    const e=(net.edges||[]).find(e=>(e.source==='you'&&e.target===n.id)||(e.target==='you'&&e.source===n.id));
    return e?({won:'Won',lost:'Lost',offered:'No deal',declined:'Declined'}[e.kind]||''):'Blocked';
  }
  function sClass(n){
    const s=(statusOf(n)||'').toLowerCase();
    return s==='won'?'s-won':s==='lost'?'s-lost':s==='no deal'?'s-nodeal':s==='declined'?'s-declined':s==='blocked'?'s-blocked':'s-lost';
  }
  const isBlocked=n=>n.kind==='applicant'&&(String(statusOf(n)).toLowerCase()==='blocked');

  function simulate(nodes,edges,W,H){
    const cx=W/2,cy=H/2,R=Math.min(W,H)/2-26;
    const you=nodes.find(n=>n.kind==='you');
    const apps=nodes.filter(n=>n.kind==='applicant'&&!isBlocked(n));
    const blocked=nodes.filter(isBlocked),rivals=nodes.filter(n=>n.kind==='rival');
    const target=new Map();
    if(you){you.x=cx;you.y=cy;you.fixed=true}
    const hasRivalLinks=edges.some(e=>byId[e.source]&&byId[e.source].kind==='rival'||byId[e.target]&&byId[e.target].kind==='rival');
    const rApp=R*(hasRivalLinks?.52:.62),rRiv=R*.86,rBlk=R*.97;
    apps.forEach((n,i)=>{const a=i/Math.max(1,apps.length)*Math.PI*2-Math.PI/2;n.x=cx+Math.cos(a)*rApp;n.y=cy+Math.sin(a)*rApp;target.set(n,rApp)});
    rivals.forEach((n,i)=>{const a=(i+.5)/Math.max(1,rivals.length)*Math.PI*2-Math.PI/2;n.x=cx+Math.cos(a)*rRiv;n.y=cy+Math.sin(a)*rRiv;target.set(n,rRiv)});
    blocked.forEach((n,i)=>{const a=(i+.25)/Math.max(1,blocked.length)*Math.PI*2+Math.PI*.15;n.x=cx+Math.cos(a)*rBlk;n.y=cy+Math.sin(a)*rBlk;target.set(n,rBlk)});
    const links=edges.map(e=>[byId[e.source],byId[e.target]]).filter(([a,b])=>a&&b);
    const kRep=Math.pow(R*.16,2),N=nodes.length,ITER=300;
    for(let it=0;it<ITER;it++){
      const alpha=1-it/ITER;
      for(const n of nodes){n.vx=0;n.vy=0}
      for(let i=0;i<N;i++)for(let j=i+1;j<N;j++){
        const a=nodes[i],b=nodes[j];let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy;
        if(d2<1){dx=(i-j)*.5;dy=.5;d2=1}
        if(d2>R*R*.6)continue;
        const f=kRep/d2,d=Math.sqrt(d2);
        a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f;
      }
      for(const [a,b] of links){
        const L=(a.kind==='you'||b.kind==='you')?rApp:R*.36;
        const dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||1,f=(d-L)*.04;
        a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f;
      }
      for(const n of nodes){
        if(n.fixed)continue;
        const t=target.get(n);
        if(t){const dx=n.x-cx,dy=n.y-cy,d=Math.sqrt(dx*dx+dy*dy)||1,f=(t-d)*.06;n.vx+=dx/d*f;n.vy+=dy/d*f}
        const m=Math.sqrt(n.vx*n.vx+n.vy*n.vy),cap=8*alpha+.5;
        if(m>cap){n.vx*=cap/m;n.vy*=cap/m}
        n.x=Math.min(W-22,Math.max(22,n.x+n.vx));n.y=Math.min(H-20,Math.max(20,n.y+n.vy));
      }
    }
  }

  function radius(n,s){
    if(n.kind==='you')return 22*s;
    if(n.kind==='rival')return 13*s;
    if(isBlocked(n))return 6*s;
    return (5+Math.min(5,Math.sqrt(n.messages||0)*1.3))*s;
  }
  function curve(a,b){
    const mx=(a.x+b.x)/2,my=(a.y+b.y)/2,dx=b.x-a.x,dy=b.y-a.y,k=.08;
    return `M${a.x.toFixed(1)},${a.y.toFixed(1)} Q${(mx-dy*k).toFixed(1)},${(my+dx*k).toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)}`;
  }

  function size(){
    const phone=window.innerWidth<=640;
    const W=Math.max(280,Math.round(stage.clientWidth));
    let H=Math.round(stage.clientHeight);
    if(phone||H<300){H=Math.round(Math.min(520,Math.max(340,W*1.05)));svg.style.height=H+'px'}else svg.style.height='';
    return [W,phone?H:Math.max(340,Math.round(stage.clientHeight))];
  }

  function draw(){
    if(!net)return;
    const [W,H]=size();lastSize=W+'x'+H;
    const s=Math.max(.78,Math.min(1.1,Math.min(W,H)/520));
    const nodes=net.nodes.map(n=>Object.assign({},n));byId={};nodes.forEach(n=>byId[n.id]=n);
    const edges=liveEdges=(net.edges||[]).filter(e=>byId[e.source]&&byId[e.target]);
    adj={};edges.forEach((e,i)=>{(adj[e.source]=adj[e.source]||[]).push(i);(adj[e.target]=adj[e.target]||[]).push(i)});
    simulate(nodes,edges,W,H);
    svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.innerHTML='';
    const gE=el('g'),gP=el('g'),gN=el('g');svg.append(gE,gP,gN);
    const recent=edges.map((e,i)=>[e,i]).filter(([e])=>e.kind!=='declined'&&!e.blocked).sort((a,b)=>(b[0].last_seq||0)-(a[0].last_seq||0)).slice(0,6).map(x=>x[1]);
    edges.forEach((e,i)=>{
      const a=byId[e.source],b=byId[e.target],d=curve(a,b);
      const w=(1+Math.min(4.5,Math.sqrt(e.messages||1)*1.05)).toFixed(2);
      gE.append(el('path',{d,class:`e ${e.blocked?'blocked':e.kind||'offered'}`,'stroke-width':w,'data-i':i}));
      const ri=recent.indexOf(i);
      if(ri>=0){const p=el('path',{d,class:`p ${e.kind==='won'?'on-won':'on-other'}`,pathLength:100,'stroke-width':Math.max(2.4,+w+1).toFixed(1),'data-i':i});p.style.animationDelay=(ri*.45)+'s';gP.append(p)}
    });
    const order=nodes.slice().sort((a,b)=>(a.kind==='you')-(b.kind==='you'));
    for(const n of order){
      const r=radius(n,s),kind=n.kind==='applicant'?'app':n.kind;
      const g=el('g',{class:`n ${kind} ${sClass(n)}${n.id===selectedId?' sel':''}`,transform:`translate(${n.x.toFixed(1)},${n.y.toFixed(1)})`,tabindex:0,role:'button','data-id':n.id,'aria-label':ariaFor(n)});
      g.append(el('circle',{class:'ring',r:(r+4).toFixed(1)}),el('circle',{class:'c',r:r.toFixed(1)}));
      if(n.kind==='you'){const t=el('text',{class:'in','text-anchor':'middle',dy:'.35em'});t.textContent='You';g.append(t);
        const l=el('text',{class:'lab','text-anchor':'middle',y:(r+15).toFixed(1)});l.textContent=trunc(net.lender&&net.lender.name||n.label||'Your agent',26);g.append(l)}
      else if(n.kind==='rival'){const letter=String(n.label||n.id).replace(/^.*[- ]/,'').slice(0,1);const t=el('text',{class:'in','text-anchor':'middle',dy:'.35em'});t.textContent=letter;g.append(t);
        const l=el('text',{class:'lab','text-anchor':'middle',y:(r+14).toFixed(1)});l.textContent=n.label||('Lender '+letter);g.append(l)}
      else{const right=n.x<W-90;const l=el('text',{class:'lab','text-anchor':right?'start':'end',x:((right?1:-1)*(r+5)).toFixed(1),dy:'.35em'});l.textContent=isBlocked(n)?'Stopped at gate':n.id;g.append(l)}
      gN.append(g);
    }
    svg.querySelectorAll('.n').forEach(g=>{
      const id=g.dataset.id;
      g.addEventListener('pointerenter',e=>{if(e.pointerType!=='touch'){focusNode(id);showTip(id)}});
      g.addEventListener('pointerleave',e=>{if(e.pointerType!=='touch'){restore()}});
      g.addEventListener('focus',()=>{focusNode(id);showTip(id)});
      g.addEventListener('blur',()=>restore());
      g.addEventListener('click',e=>{e.stopPropagation();activate(id)});
      g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate(id)}else if(e.key==='Escape'){pinned=null;restore();g.blur()}});
    });
    if(pinned)focusNode(pinned);
  }
  const trunc=(t,n)=>t.length>n?t.slice(0,n-1)+'…':t;

  function caseFor(id){return opts.caseById?opts.caseById(id):null}
  function ariaFor(n){
    if(n.kind==='you')return `Your agent: ${n.messages||0} messages`;
    if(n.kind==='rival')return `${n.label||n.id}, anonymous rival lender agent`;
    if(isBlocked(n))return 'Borrower agent stopped at the CRS gate, not shown to you';
    const c=caseFor(n.id);
    return `Application ${n.id}: ${statusOf(n)}, ${n.messages||0} messages${c&&c.final?`, your rate ${c.final.apr}%`:''}. Press Enter to open.`;
  }
  function tipHTML(n){
    if(n.kind==='you'){const d=net.stats||{};return `<b>Your agent</b><span class="k">Messages</span> ${safe(n.messages??d.messages_checked??'-')}<br><span class="k">Deals</span> ${safe(n.deals??d.deals??'-')}<br><span class="k">Connected to</span> ${safe((adj[n.id]||[]).length)} agents`}
    if(n.kind==='rival')return `<b>${safe(n.label||n.id)}</b>Anonymous rival lender agent<br><span class="k">Messages</span> ${safe(n.messages??'not shared')}<br><span class="k">Deals</span> ${safe(n.deals??'not shared')}`;
    if(isBlocked(n))return `<b>Borrower agent</b>Stopped at the CRS gate (fraud or identity). You never saw this application.`;
    const c=caseFor(n.id);
    const rate=c&&c.final?`${c.opening?c.opening.apr+'% → ':''}${c.final.apr}%`:'no offer';
    return `<b>${safe(n.id)}</b><span class="k">Status</span> ${safe(statusOf(n))}${n.risk||c?` · ${safe(n.risk||c.risk)}`:''}<br><span class="k">Band</span> ${safe(n.band||(c&&c.band)||'-')}<br><span class="k">Messages</span> ${safe(n.messages??'-')}<br><span class="k">Your rate</span> ${safe(rate)}${c?'<br><span class="k">Click to open in the queue</span>':''}`;
  }
  function showTip(id){
    const n=byId[id];if(!n||!tip)return;
    tip.innerHTML=tipHTML(n);tip.hidden=false;
    const W=stage.clientWidth,r=radius(n,1);
    const x=Math.min(W-120,Math.max(120,n.x));
    tip.style.left=x+'px';
    const below=n.y<110;tip.classList.toggle('below',below);
    tip.style.top=(below?n.y+r:n.y-r)+'px';
  }
  function hideTip(){if(tip)tip.hidden=true}
  function focusNode(id){
    if(!svg)return;
    svg.classList.add('focusing');
    svg.querySelectorAll('.hl').forEach(x=>x.classList.remove('hl'));
    const keep=new Set([id]);
    for(const i of adj[id]||[]){const e=liveEdges[i];keep.add(e.source);keep.add(e.target);svg.querySelectorAll(`[data-i="${i}"]`).forEach(x=>x.classList.add('hl'))}
    svg.querySelectorAll('.n').forEach(g=>{if(keep.has(g.dataset.id))g.classList.add('hl')});
  }
  function restore(){
    hideTip();
    if(pinned){focusNode(pinned);return}
    if(!svg)return;svg.classList.remove('focusing');svg.querySelectorAll('.hl').forEach(x=>x.classList.remove('hl'));
  }
  function activate(id){
    const n=byId[id];if(!n)return;
    if(n.kind==='applicant'&&!isBlocked(n)&&caseFor(id)){pinned=null;restore();setSelected(id);opts.onSelect&&opts.onSelect(id,'web');showTip(id);return}
    if(isBlocked(n)){showTip(id);opts.onToast&&opts.onToast('Stopped at the CRS gate. You never saw this application.');return}
    if(n.kind==='rival'||n.kind==='applicant'){pinned=pinned===id?null:id;if(pinned){focusNode(id);showTip(id)}else restore();return}
    pinned=null;restore();
  }
  function setSelected(id){
    selectedId=id;if(!svg)return;
    svg.querySelectorAll('.n').forEach(g=>g.classList.toggle('sel',g.dataset.id===id));
  }
  function showBlocked(){
    if(!svg)return;svg.classList.add('show-blocked');
    clearTimeout(showBlocked.t);showBlocked.t=setTimeout(()=>svg.classList.remove('show-blocked'),3200);
  }

  function renderList(){
    const body=document.getElementById('webListRows');if(!body)return;
    const kindWord={you:'Your agent',rival:'Rival lender (anonymous)',applicant:'Borrower agent'};
    const rows=net.nodes.slice().sort((a,b)=>({you:0,rival:1,applicant:2}[a.kind]-{you:0,rival:1,applicant:2}[b.kind])||((b.messages||0)-(a.messages||0)));
    body.innerHTML=rows.map(n=>{
      const name=n.kind==='you'?'You':n.kind==='rival'?safe(n.label||n.id):isBlocked(n)?'Stopped at gate':(caseFor(n.id)?`<button type="button" data-pick="${safe(n.id)}">${safe(n.id)}</button>`:safe(n.id));
      return `<tr><td>${name}</td><td>${kindWord[n.kind]||safe(n.kind)}</td><td class="mono">${safe(n.messages??'-')}</td><td>${n.kind==='applicant'?safe(statusOf(n)):n.kind==='you'?safe((n.deals??'-')+' deals'):safe(n.deals!=null?n.deals+' deals':'not shared')}</td></tr>`;
    }).join('');
    body.querySelectorAll('[data-pick]').forEach(b=>b.addEventListener('click',()=>{setSelected(b.dataset.pick);opts.onSelect&&opts.onSelect(b.dataset.pick,'list')}));
  }

  function renderStats(){
    const box=document.getElementById('webStats'),src=document.getElementById('webSource'),sub=document.getElementById('webSub');
    const s=net.stats||{},derived=!!net.derived;
    const total=(s.borrower_agents||0)+(s.lender_agents||0);
    if(box)box.innerHTML=`<span><b>${safe(total)}</b> agents</span><span><b>${safe(s.borrower_agents??'-')}</b> borrower agents</span><span><b>${safe(s.lender_agents??'-')}</b> lender agents</span><span><button type="button" id="webGateBtn"><b>${safe(s.blocked_at_gate??0)}</b> stopped at the gate</button></span><span><b>${safe(s.messages_checked??'-')}</b> ${derived?'messages with your agent':'messages checked'}</span>${derived?'':`<span><b>${safe(s.messages_blocked??0)}</b> blocked by the referee</span>`}`;
    document.getElementById('webGateBtn')?.addEventListener('click',showBlocked);
    if(src){src.textContent=derived?'From your sessions':'Exchange feed';src.classList.toggle('derived',derived)}
    if(sub)sub.textContent=derived?'Your agent and every borrower agent it met. Rival lenders’ links are not in your data, so they stand apart.':'Every agent your agent met. Hover or tab to a node; click an application to open it.';
  }

  LC.web={
    render(network,options){
      svg=document.getElementById('webSvg');stage=document.getElementById('webStage');tip=document.getElementById('webTip');
      net=network;opts=options||{};pinned=null;selectedId=opts.selected||null;
      if(!svg||!stage)return;
      if(!net||!Array.isArray(net.nodes)||!net.nodes.length){svg.innerHTML='';stage.querySelector('.web-empty')||stage.insertAdjacentHTML('beforeend','<div class="web-empty">No agent activity to show yet.</div>');return}
      stage.querySelector('.web-empty')?.remove();
      renderStats();renderList();draw();
      if(!svg.dataset.bound){
        svg.dataset.bound='1';
        svg.addEventListener('click',()=>{pinned=null;restore()});
        window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(!net||!stage)return;const W=Math.round(stage.clientWidth);if(Math.abs(W-parseInt(lastSize))>24)draw()},180)});
      }
    },
    select:setSelected,
    showBlocked,
  };
})();
