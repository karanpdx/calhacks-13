// Rule-based desk answers, used only when POST /api/lender/{id}/ask is unavailable.
// No AI: it reads the same lender-side data the console already holds and answers in plain words.
(function(){
  const LC=window.LC=window.LC||{};
  const avg=a=>a.length?a.reduce((s,x)=>s+x,0)/a.length:0;
  const f2=n=>Number(n).toFixed(2);
  const ids=list=>list.map(c=>c.id);
  const plural=(n,one,many)=>`${n} ${n===1?one:(many||one+'s')}`;

  function facts(st){
    const cases=st.cases||[],d=st.data||{},s=d.stats||{},L=d.lender||{};
    const offered=cases.filter(c=>c.opening),won=cases.filter(c=>c.status==='Won'),lost=cases.filter(c=>c.status==='Lost');
    const nodeal=cases.filter(c=>c.status==='No deal'),declined=cases.filter(c=>c.status==='Declined');
    const review=cases.filter(c=>c.attention&&!(st.resolved&&st.resolved.has(c.id)));
    return {cases,s,L,offered,won,lost,nodeal,declined,review,net:st.net||{stats:{}}};
  }

  function caseStory(c){
    if(!c)return null;
    const lines=[`${c.id}: ${c.band} band, ${c.risk} risk, asked for $${Number(c.request.amount).toLocaleString()} over ${c.request.terms}.`];
    if(c.opening&&c.final){
      lines.push(`Your agent opened at ${c.opening.apr}% and ${c.status==='Won'?'closed':'ended'} at ${c.final.apr}%${c.final.autopay?' with autopay':''} after ${plural(c.rounds,'offer')} and ${plural(c.counters,'counter')}.`);
      if(c.books)lines.push(`Your break-even was ${c.books.break_even_apr}% and your floor ${c.books.floor_apr}%, so the final rate sits ${f2(c.final.apr-c.books.break_even_apr)} points above break-even.`);
    }
    lines.push(`Outcome: ${c.status}${c.decline_code?` (${c.decline_code})`:''}. ${c.decline_reason||''}`.trim());
    for(const x of c.exceptions||[])lines.push(`- ${x.title}: ${x.note}`);
    return lines.join('\n');
  }

  LC.desk=function(question,st){
    const q=String(question||'').toLowerCase(),F=facts(st);
    const idm=String(question||'').toUpperCase().match(/APP-[0-9A-F]{6}/);
    if(idm){
      const c=F.cases.find(x=>x.id===idm[0]);
      return c?{reply:caseStory(c),refs:[c.id]}:{reply:`${idm[0]} isn't in your queue. Either it was stopped at the CRS gate (you never see those) or the id belongs to another lender's view: ids are hashed per lender.`,refs:[]};
    }
    if(/review|attention|exception|flag|human|check/.test(q)){
      if(!F.review.length)return {reply:'Nothing needs your review right now. Every deal your agent made stayed inside your books.',refs:[]};
      const items=F.review.map(c=>`- ${c.id} (${c.status}): ${(c.exceptions||[]).map(x=>x.title).join('; ')||'flagged for a human look'}`);
      return {reply:`${plural(F.review.length,'application needs','applications need')} your review before funding:\n${items.join('\n')}`,refs:ids(F.review)};
    }
    if(/why.*(lose|lost)|lost|lose|losing|beat/.test(q)){
      const lines=[];
      if(F.lost.length){
        const gap=avg(F.lost.filter(c=>c.final&&c.books).map(c=>c.final.apr-c.books.floor_apr));
        lines.push(`You lost ${plural(F.lost.length,'deal')} to another offer. On average your last offer sat ${f2(gap)} points above your floor, so the borrower's agent found a cheaper verified quote. You never learn which lender won.`);
      }
      if(F.nodeal.length)lines.push(`${plural(F.nodeal.length,'session')} ended with no deal: the borrower's agent couldn't find terms inside its mandate.`);
      if(!lines.length)lines.push(`You haven't lost a deal you offered on. ${F.declined.length?`${plural(F.declined.length,'application was','applications were')} declined by your own rules before an offer.`:''}`);
      return {reply:lines.join('\n\n'),refs:ids(F.lost.concat(F.nodeal)).slice(0,8)};
    }
    if(/declin|turn(ed)? down|reject|rule/.test(q)){
      const by={};F.declined.forEach(c=>{const k=c.decline_code||'OTHER';(by[k]=by[k]||[]).push(c)});
      const items=Object.entries(by).sort((a,b)=>b[1].length-a[1].length).map(([k,v])=>`- ${k.replace(/_/g,' ').toLowerCase()}: ${v.length}`);
      return {reply:F.declined.length?`Your rules declined ${plural(F.declined.length,'application')} before an offer:\n${items.join('\n')}`:'Your rules did not decline anyone.',refs:ids(F.declined).slice(0,8)};
    }
    if(/win|won|rate of|conversion/.test(q)){
      const r=F.offered.length?Math.round(100*F.won.length/F.offered.length):0;
      const m=avg(F.won.filter(c=>c.books&&c.final).map(c=>c.final.apr-c.books.break_even_apr));
      const a=avg(F.won.filter(c=>c.final).map(c=>c.final.apr));
      return {reply:F.offered.length?`You won ${F.won.length} of ${plural(F.offered.length,'offer')} (${r}%).${F.won.length?` Average closing rate ${f2(a)}%, about ${f2(m)} points above break-even.`:''}`:'Your agent has not made an offer yet.',refs:ids(F.won).slice(0,8)};
    }
    if(/agent|connect|network|web|talk|rival|competit/.test(q)){
      const s=F.net.stats||{};
      return {reply:`${s.admitted??F.cases.length} borrower agents passed the CRS gate and reached you; ${s.blocked_at_gate??F.s.blocked_at_gate} were stopped first. The market is sealed: you never see other lenders or their conversations.`,refs:[]};
    }
    if(/volume|target|booked|goal|month/.test(q)){
      const v=F.L.volume||{};
      return {reply:`You've booked ${v.booked} of a ${v.target}-loan monthly target (${v.target?Math.round(100*v.booked/v.target):0}%). This exchange added ${plural(F.won.length,'loan')}. ${F.L.motive||''}`,refs:[]};
    }
    if(/margin|floor|break|pric|apr|rate|concess|autopay/.test(q)){
      const o=avg(F.offered.map(c=>c.opening.apr)),fi=avg(F.offered.filter(c=>c.final).map(c=>c.final.apr));
      const ap=F.offered.filter(c=>c.final&&c.final.autopay).length;
      return {reply:F.offered.length?`Your agent opened at ${f2(o)}% on average and finished at ${f2(fi)}%, a ${f2(o-fi)}-point concession. ${ap} of ${F.offered.length} final offers traded rate for autopay. It never went below your floor: the referee's code rejects any offer under it.`:'No offers yet, so no pricing to report.',refs:[]};
    }
    if(/privacy|name|ssn|who is|identity|personal/.test(q))return {reply:(st.data&&st.data.privacy)||'You see the passport only.',refs:[]};
    const v=F.L.volume||{};
    return {reply:`${F.cases.length} borrower agents reached ${F.L.name||'you'} (${F.s.blocked_at_gate} were stopped at the CRS gate first). Your agent offered on ${F.offered.length}, won ${F.won.length}, lost ${F.lost.length}, and ${F.declined.length} were declined by your rules. ${F.review.length?`${plural(F.review.length,'application needs','applications need')} your review.`:'Nothing needs your review.'} Booked ${v.booked} of ${v.target} this month.\n\nAsk me about reviews, win rate, lost deals, declines, pricing, agents, or any APP id.`,refs:ids(F.review)};
  };
})();
