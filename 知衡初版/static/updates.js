'use strict';
views.updates=['官方公告','让新的披露，成为新的证据。','检查巨潮资讯与上交所公告，回看原件后选取需要的资料。'];
state.announcements=[];
function initializeUpdates(){
  const end=state.status.today||new Date().toLocaleDateString('en-CA');const start=new Date(end+'T12:00:00');start.setDate(start.getDate()-60);
  if(!$('#announcement-end').value){$('#announcement-end').value=end;$('#announcement-start').value=start.toLocaleDateString('en-CA');$('#announcement-code').value=state.code;}
  $('#announcement-end').max=end;$('#import-date').max=end;$('#cutoff').max=end;
  updateSemanticOption();
}
function updateSemanticOption(){const enabled=$('input[name="mode"]:checked').value==='llm'&&state.status?.model.configured;
  $('#semantic-retrieval').disabled=!enabled||state.busy;$('#semantic-option').classList.toggle('muted',!enabled);
}
function semanticEnabled(){return $('input[name="mode"]:checked').value==='llm'&&$('#semantic-retrieval').checked;}
function retrievalHtml(r){if(!r)return '';return `<details class="retrieval-detail"><summary>${r.mode==='semantic'?'语义重排':'关键词召回'} · ${Number(r.candidate_count)}个候选 · 检索记录 ${esc(r.id)}</summary><p>${esc(r.intent)}</p><ul>${r.queries.map(q=>`<li>${esc(q)}</li>`).join('')}</ul><p class="footnote">${esc(r.method)}</p>${r.warnings.map(w=>`<p class="notice subtle">${esc(w)}</p>`).join('')}</details>`;}
function showRetrieval(r){$('#retrieval-summary').innerHTML=retrievalHtml(r);}
function announcementScope(){return {code:$('#announcement-code').value,start:$('#announcement-start').value,end:$('#announcement-end').value,keyword:$('#announcement-keyword').value.trim()};}
async function loadAnnouncements(){const p=await api('/api/announcements?'+query(announcementScope()));state.announcements=p.data;renderAnnouncements(p);}
function renderAnnouncements(p){const rows=$('#announcement-new-only').checked?p.data.filter(r=>r.status!=='available'):p.data;
  $('#announcement-count').textContent=`${p.data.length}份候选 · ${p.data.filter(r=>r.status==='new').length}份尚未加入`;
  const last=p.checks[0];$('#announcement-check-summary').innerHTML=last?`<div class="notice subtle"><b>最近检查：${esc(last.start)} 至 ${esc(last.end)} · ${esc(last.code?names[last.code]:'三家公司')}</b><p>${last.companies.map(c=>`${esc(c.company)}：有效${c.valid_count}份 / 官方${c.official_total}份 · ${esc(c.note)}`).join('<br>')}</p>${last.complete?'':'<p>此查询尚未完整覆盖。请查看原因，并缩小范围或重试。</p>'}</div>`:'<p class="footnote">尚未执行官方检查。候选资料不会自动加入研究。</p>';
  $('#announcement-list').innerHTML=rows.length?rows.map(r=>`<article class="announcement-card"><label class="announcement-select"><input type="checkbox" data-announcement-id="${esc(r.id)}" ${r.status==='available'?'disabled':''}><span class="sr-only">选择 ${esc(r.title)}</span></label><div class="announcement-content"><div class="announcement-tags"><span class="small-tag">${esc(r.company)}</span><span class="muted">${esc(r.publication_date)} · ${esc(r.publisher)}</span><span class="status-pill">${r.status==='available'?'已有资料':r.status==='paused'?'已暂停，可启用':'待加入'}</span>${r.period?`<span class="small-tag">${esc(periodLabel(r.period))}</span>`:''}</div><h3>${esc(r.title)}</h3><p class="footnote">${esc(r.metadata_method)}${r.date_conflict?'；文件路径日期与列表日期不同，需核验。':''}</p><div class="announcement-actions"><a href="${esc(safeUrl(r.download_url||r.url))}" target="_blank" rel="noopener">查看官方原件 ↗</a>${r.existing_source?fileLink(r.existing_source,null,'查看资料库原件'):''}</div></div></article>`).join(''):'<div class="empty-message">当前条件下没有候选公告。点击“检查官方公告”取回列表，或调整筛选条件。</div>';
  $('#announcement-selection').textContent='每次最多选择5份；重复原件按文件摘要复用。';
}
async function checkAnnouncements(event){event.preventDefault();if(state.busy)return;busy(true);const b=$('#check-announcements');b.disabled=true;$('#announcement-progress').textContent='正在连接官方公告列表…';try{
  const task=await post('/api/announcements/check',announcementScope());const job=await pollTask(task,j=>{$('#announcement-progress').textContent=j.trace.at(-1)?.detail||'正在查询…';});
  await loadAnnouncements();$('#announcement-progress').textContent=job.result.complete?`检查完成：取回${job.result.count}份有效公告。`:'已取回部分结果，请查看查询范围与未完成原因。';
}finally{busy(false);b.disabled=false;}}
async function importAnnouncements(){if(state.busy)return;const ids=$$('[data-announcement-id]:checked').map(el=>el.dataset.announcementId);if(!ids.length||ids.length>5)throw new Error('每次请选择1至5份公告。');busy(true);const b=$('#import-announcements');b.disabled=true;try{
  const task=await post('/api/announcements/import',{ids});const job=await pollTask(task,j=>{$('#announcement-progress').textContent=j.trace.at(-1)?.detail||'正在保存官方原件…';});
  await refreshDatasetStatus();await loadAnnouncements();$('#announcement-progress').textContent=`成功${job.result.succeeded}份，失败${job.result.failed}份。`;
  $('#announcement-import-result').innerHTML=job.result.data.map(r=>`<p class="${r.ok?'footnote':'notice'}">${esc(r.title)}：${r.ok?(r.duplicate?'复用已有原件':'已加入资料库'):esc(r.error)}${r.ok?' · '+fileLink(r.source_id,null,'回看原件'):''}</p>`).join('');
  toast('所选公告处理完成，结果与原件可回看。');
}finally{busy(false);b.disabled=false;}}
async function refreshDatasetStatus(){state.status=await api('/api/status');$('#nav-source-count').textContent=state.status.dataset.total_sources;$('#coverage-stats').innerHTML=`${state.status.dataset.total_sources}个可用来源 · 基础${Number(state.status.dataset.pdf_pages).toLocaleString()}页PDF<br>${Number(state.status.index.chunk_count).toLocaleString()}个基础片段 · ${state.status.dataset.market_rows}条日线`;initializeFeatures();}
$('#announcement-form').addEventListener('submit',catchTask(checkAnnouncements));$('#announcement-filter').addEventListener('click',catchTask(loadAnnouncements));$('#import-announcements').addEventListener('click',catchTask(importAnnouncements));$('#announcement-new-only').addEventListener('change',catchTask(loadAnnouncements));
$$('input[name="mode"]').forEach(el=>el.addEventListener('change',updateSemanticOption));
