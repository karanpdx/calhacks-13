/* Agent chat language/accessibility layer. Catalog comes only from exchange/i18n.py. */
(function () {
  'use strict';
  const messages = window.BORROWER_MESSAGES || {en: {}, es: {}};
  let saved = 'en';
  try { saved = localStorage.getItem('borrower-language') || 'en'; } catch (_) {}
  let lang = new URLSearchParams(location.search).get('lang') || saved;
  if (!messages[lang]) lang = 'en';
  let plain = true;
  const originals = new WeakMap(), rendered = new Map(), attrs = new WeakMap();
  const reverse = new Map();
  for (const l of ['en','es']) for (const key of Object.keys(messages[l])) reverse.set(messages[l][key], key);
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const locale = l => l === 'es' ? 'es-ES' : 'en-US';
  const template = (s, values) => s.replace(/\{(\w+)\}/g, (_, k) => values[k] == null ? '' : String(values[k]));
  const patterns = [];
  Object.keys(messages.en).forEach(key => {
    const english = messages.en[key];
    if (!/\{\w+\}/.test(english) || english.replace(/\{\w+\}/g, '').replace(/[^a-z]/gi, '').length < 4) return;
    for (const source of ['en', 'es']) {
      const text = messages[source][key];
      if (!text) continue;
      const names = [];
      const bits = text.split(/(\{\w+\})/).map(p => /^\{/.test(p) ? (names.push(p.slice(1,-1)), '(.+?)') : p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
      patterns.push({key, source, names, regex: new RegExp('^' + bits.join('') + '$', 'i'), prefix: new RegExp('^' + bits.join(''), 'i'), startsLiteral: !text.startsWith('{'), weight: text.replace(/\{\w+\}/g,'').length});
    }
  });
  patterns.sort((a,b) => b.weight-a.weight);
  function formatFor(value, target) {
    if (value == null) return '';
    if (typeof value === 'number') return value.toLocaleString(locale(target), {maximumFractionDigits:12});
    const s=String(value), pair=rendered.get(s);
    if(pair)return pair[target];
    if(reverse.has(s))return messages[target][reverse.get(s)];
    if(target===lang)return s;
    if(/^\$[\d,.]+$/.test(s))return target==='es'?s.slice(1).replace(/,/g,'\0').replace(/\./g,',').replace(/\0/g,'.')+' USD':s;
    if(/^[\d.,]+ USD$/.test(s))return target==='en'?'$'+s.slice(0,-4).replace(/\./g,'\0').replace(/,/g,'.').replace(/\0/g,','):s;
    if(/^\d+(?:[.,]\d+)?%?$/.test(s))return target==='es'?s.replace('.',','):s.replace(',','.');
    return s;
  }
  function message(key, values = {}) {
    const pair = {};
    for (const l of ['en','es']) pair[l] = template(messages[l][key] || key, Object.fromEntries(Object.entries(values).map(([k,v])=>[k,formatFor(v,l)])));
    rendered.set(pair.en, pair); rendered.set(pair.es, pair);
    return pair[lang];
  }
  function localNumber(value, source) {
    let str = String(value);
    if (source === lang) return str;
    if (/^\$[\d,.]+$/.test(str)) return lang === 'es' ? str.slice(1).replace(/,/g,'\0').replace(/\./g,',').replace(/\0/g,'.') + ' USD' : str;
    if (/^[\d.,]+ USD$/.test(str)) return lang === 'en' ? '$' + str.slice(0,-4).replace(/\./g,'\0').replace(/,/g,'.').replace(/\0/g,',') : str;
    if (/^\d+(?:[.,]\d+)?%?$/.test(str)) return lang === 'es' ? str.replace('.',',') : str.replace(',','.');
    return str;
  }
  function text(value, depth = 0) {
    if (value == null) return '';
    const s = String(value);
    for (const l of ['en','es']) if (s.startsWith(messages[l].Simulated + ': ')) return message('Simulated') + ': ' + text(s.slice(messages[l].Simulated.length + 2), depth + 1);
    const known = rendered.get(s);
    if (known) return known[lang];
    if (/^•\s/.test(s)) return '• ' + text(s.slice(2), depth + 1);
    if (messages[lang][s] != null) return message(s);
    const trim = s.trim();
    if (trim !== s && messages[lang][trim] != null) return s.slice(0,s.indexOf(trim)) + message(trim) + s.slice(s.indexOf(trim)+trim.length);
    if (reverse.has(s)) return message(reverse.get(s));
    if (depth < 8) for (const p of patterns) {
      const match = s.match(p.regex);
      if (!match) continue;
      const values = {};
      p.names.forEach((name,i) => values[name] = localNumber(text(match[i+1], depth+1), p.source));
      return message(p.key, values);
    }
    if (depth < 8) {
      const pieces=s.split(/([.!?])\s+(?=[A-ZÁÉÍÓÚ¿¡])/u),sentences=[];
      if(pieces.length>1){for(let i=0;i<pieces.length;i+=2)sentences.push(pieces[i]+(pieces[i+1]||''));return sentences.map(part=>text(part,depth+1)).join(' ');}
      for(const p of patterns){
        if(!p.startsLiteral)continue;
        const match=s.match(p.prefix);
        if(!match||match[0].length<12||match[0].length===s.length)continue;
        const values={};p.names.forEach((name,i)=>values[name]=localNumber(text(match[i+1],depth+1),p.source));
        return message(p.key,values)+text(s.slice(match[0].length),depth+1);
      }
      for(const join of [' and ',' y '])if(s.includes(join))return s.split(join).map(part=>text(part,depth+1)).join(message(' and '));
    }
    return localNumber(s, lang === 'en' ? 'es' : 'en');
  }
  function ignored(el) { return el && el.closest('script,style,svg,option[data-code],.me,.says,[data-source-record],.a11y-status'); }
  function translateTree(root) {
    if (!root || ignored(root.nodeType === 1 ? root : root.parentElement)) return;
    const nodes = [];
    if (root.nodeType === 3) nodes.push(root);
    else { const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT); while (walk.nextNode()) nodes.push(walk.currentNode); }
    for (const n of nodes) {
      if (!n.nodeValue.trim() || ignored(n.parentElement)) continue;
      let entry = originals.get(n);
      if (!entry || n.nodeValue !== entry.last) entry = {source:n.nodeValue,last:n.nodeValue};
      const next = text(entry.source);
      if (n.nodeValue !== next) n.nodeValue = next;
      entry.last = next; originals.set(n,entry);
    }
    const elements = root.nodeType === 1 ? [root,...root.querySelectorAll('[aria-label],[placeholder],[title]')] : [];
    for (const el of elements) {
      if (ignored(el)) continue;
      const state = attrs.get(el) || {};
      for (const key of ['aria-label','placeholder','title']) if (el.hasAttribute(key)) {
        let item = state[key]; const val = el.getAttribute(key);
        if (!item || item.last !== val) item = {source:val};
        const next = text(item.source); if (val !== next) el.setAttribute(key,next);
        item.last = next; state[key] = item;
      }
      attrs.set(el,state);
    }
  }
  function money(n, digits) {
    const num = Number(n), cents = digits == null ? (Math.abs(num-Math.round(num)) > .004 ? 2 : 0) : digits;
    const value = num.toLocaleString(locale(lang), {minimumFractionDigits:cents,maximumFractionDigits:cents});
    return lang === 'es' ? value + ' USD' : '$' + value;
  }
  const terms = {rate:'Yearly rate',fee:'Fee',autopay:'Autopay',length:'Loan length',score:'Credit score',soft:'Soft check',hard:'Hard check',total:'Total repayment',bureau:'Credit bureau',collection:'Debt collection',writeoff:'Unpaid write-off',bankruptcy:'Bankruptcy'};
  let speaking = null;
  function stopReading() { if (window.speechSynthesis) speechSynthesis.cancel(); if(speaking){speaking.setAttribute('aria-pressed','false');speaking.textContent=message('Read this to me');speaking=null;} }
  function narrationButton(region, getText) {
    const b=document.createElement('button'); b.type='button'; b.className='a11y-read btn'; b.textContent=message('Read this to me'); b.setAttribute('aria-pressed','false');
    b.onclick=()=>{
      if(speaking===b){stopReading();announce(message('Reading stopped.'));return;}
      stopReading();
      if(!window.speechSynthesis || !window.SpeechSynthesisUtterance){announce(message('Reading is unavailable in this browser.'));return;}
      translateTree(region);
      const copy = getText ? getText() : region.cloneNode(true);
      if(copy.nodeType) copy.querySelectorAll('button,input,select,[data-source-record],[hidden]').forEach(el=>el.remove());
      const value=typeof copy==='string'?copy:copy.textContent;
      const chunks=(value||'').match(/.{1,180}(?:\s|$)|.{1,180}/g)||[];
      if(!chunks.length)return;
      speaking=b;b.textContent=message('Stop reading');b.setAttribute('aria-pressed','true');
      const voice=speechSynthesis.getVoices().find(v=>v.lang.toLowerCase().startsWith(lang));
      let index=0;
      const next=()=>{if(speaking!==b)return;if(index>=chunks.length){stopReading();return;}const u=new SpeechSynthesisUtterance(chunks[index++]);u.lang=locale(lang);if(voice)u.voice=voice;u.onend=next;u.onerror=()=>{stopReading();announce(message('Reading stopped.'));};speechSynthesis.speak(u);};next();
    }; return b;
  }
  function announce(value){const el=document.getElementById('a11y-status');if(el)el.textContent=value;}
  function resultText(person) {
    const parts=[]; if(person&&person.outcome==='awaiting_approval')parts.push(message('Waiting for your approval. Nothing is signed.'));
    const walk=v=>{if(typeof v==='string'){if(!['deal','blocked','no_deal','awaiting_approval','high','medium'].includes(v))parts.push(text(v));}else if(Array.isArray(v))v.forEach(walk);else if(v&&typeof v==='object')Object.values(v).forEach(walk);};
    const d=person&&person.deal;if(d)parts.push(message('Simulated lender'),d.lender,message('Monthly payment'),money(d.monthly_payment),message('Yearly rate'),Number(d.apr).toLocaleString(locale(lang))+'%',message('Total repayment'),money(d.total_paid));
    walk(person);return parts.join('. ');
  }
  function termButton(key,label) { const b=document.createElement('button');b.type='button';b.className='term-help';b.textContent=label||message(terms[key]);if(key==='rate'){const jargon=document.createElement('span');jargon.dataset.jargon='true';jargon.hidden=plain;jargon.textContent=' (APR)';b.append(jargon);}b.setAttribute('aria-expanded','false');b.onclick=()=>{let p=b.nextElementSibling;if(p&&p.classList.contains('term-explanation')){p.remove();b.setAttribute('aria-expanded','false');return;}p=document.createElement('span');p.className='term-explanation';p.id='term-'+Math.random().toString(36).slice(2);p.textContent=message('term.'+key);b.after(p);b.setAttribute('aria-controls',p.id);b.setAttribute('aria-expanded','true');};return b; }
  function enhanceTerms(root) {
    if(!root.querySelectorAll)return;
    for(const el of root.querySelectorAll('.drow > span,.plan .r > span,.ios-row > .k')){
      if(el.closest('button,[role="button"]')||el.querySelector('button'))continue;
      const str=el.textContent.trim();
      const aliases={rate:['Yearly rate (APR)','Highest rate','Rate'],fee:['Highest one-time fee','Fees'],autopay:['Automatic payments'],length:['Length'],score:['credit score'],total:["Total you'd repay","Total you'll pay"]};
      const key=Object.keys(terms).find(k=>[terms[k],...(aliases[k]||[])].some(label=>str===label||str===messages.es[label]));
      if(key){el.replaceChildren(termButton(key,str));}
    }
  }
  function mount(){
    document.documentElement.lang=lang;document.body.classList.toggle('plain-language',plain);
    const tools=document.createElement('div');tools.className='borrower-tools';
    const group=document.createElement('div');group.setAttribute('role','group');group.setAttribute('aria-label',message('Language'));
    const label=document.createElement('span');label.textContent=message('Language');group.append(label);
    for(const l of ['en','es']){const b=document.createElement('button');b.type='button';b.textContent=l.toUpperCase();b.lang=l;b.setAttribute('aria-label',l==='en'?'English':'Español');b.setAttribute('aria-pressed',String(lang===l));b.onclick=()=>{stopReading();lang=l;document.documentElement.lang=l;try{localStorage.setItem('borrower-language',l);}catch(_){}const url=new URL(location.href);url.searchParams.set('lang',l);history.replaceState(null,'',url);group.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x.lang===l)));translateTree(document.body);window.dispatchEvent(new CustomEvent('borrower-language',{detail:l}));};group.append(b);}
    const plainLabel=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=true;check.onchange=()=>{plain=check.checked;document.body.classList.toggle('plain-language',plain);document.querySelectorAll('[data-jargon]').forEach(el=>el.hidden=plain);};plainLabel.append(check,document.createTextNode(message('Plain language')));
    const glossary=document.createElement('details');glossary.className='borrower-glossary';const summary=document.createElement('summary');summary.textContent=message('Explain a term');glossary.append(summary);const list=document.createElement('div');for(const key of Object.keys(terms))list.append(termButton(key));glossary.append(list);tools.append(group,plainLabel,glossary);document.body.prepend(tools);
    const skip=document.createElement('a');skip.className='a11y-skip';skip.href='#app';skip.textContent=message('Skip to borrower flow');document.body.prepend(skip);
    const footer=document.createElement('footer');footer.className='borrower-translation';footer.textContent=message('Machine-assisted Spanish translation.');footer.hidden=lang!=='es';document.body.append(footer);window.addEventListener('borrower-language',e=>{footer.hidden=e.detail!=='es';});
    const status=document.createElement('div');status.id='a11y-status';status.className='sr-only a11y-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');document.body.append(status);
    if(window.ResizeObserver)new ResizeObserver(()=>document.body.style.setProperty('--borrower-tools-height',tools.offsetHeight+'px')).observe(tools);
    translateTree(document.body);enhanceTerms(document.body);
    let queued=false;new MutationObserver(records=>{if(queued)return;const roots=[];for(const r of records){if(r.type==='characterData')roots.push(r.target);else if(r.type==='attributes')roots.push(r.target);else r.addedNodes.forEach(n=>roots.push(n));}queued=true;queueMicrotask(()=>{roots.forEach(n=>{translateTree(n);if(n.nodeType===1)enhanceTerms(n);});queued=false;});}).observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['aria-label','title','placeholder']});
  }
  function value(v){const key='value.'+v;return messages[lang][key] ? message(key) : text(v);}
  function reason(code){return message(messages[lang]['reason.'+code] ? 'reason.'+code : 'reason.default');}
  function matches(value,key){return ['en','es'].some(l=>messages[l][key]===value);}
  window.BorrowerUI={get lang(){return lang;},message,text,money,reduced,narrationButton,resultText,announce,translateTree,value,reason,matches,stopReading};
  window.addEventListener('pagehide',stopReading);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.querySelectorAll('.borrower-glossary[open]').forEach(d=>d.open=false);stopReading();}});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
