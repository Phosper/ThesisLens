'use strict';
views.scope=['企业与研究方法','企业与研究方法','查看企业资料覆盖和研究要求，登记新的研究对象。'];
state.companyProfiles=[];state.operatingBaseline=null;

function initializeCompanies(){
  Object.assign(names,state.status.companies);state.companyProfiles=state.status.company_profiles||[];
  const groups=[['company',null],['library-company','全部公司与行业'],['import-code','行业与政策'],['announcement-code','全部已配置企业']];
  for(const [id,empty] of groups){
    const element=$('#'+id);if(!element)continue;const selected=element.value;
    const profiles=state.companyProfiles.filter(p=>id!=='announcement-code'||(p.listed&&p.org_id));
    element.innerHTML=(empty?`<option value="">${esc(empty)}</option>`:'')+profiles.map(p=>`<option value="${esc(p.code)}">${esc(p.name)}${id==='company'?' · '+esc(p.segment):''}</option>`).join('');
    if(profiles.some(p=>p.code===selected)||empty&&selected==='')element.value=selected;
    if(id==='company')element.value=state.code;
  }
  renderCompanyScope();
}

async function renderCompanyScope(){
  const code=state.code,profile=state.companyProfiles.find(p=>p.code===code);if(!profile)return;
  const requirement=await api('/api/research/requirements?'+query({code}));if(state.code!==code)return;
  $('#company-scope').innerHTML=`<span>${esc(profile.segment)} · ${profile.listed?'上市企业研究':'非上市资料研究'}</span><p>${esc(requirement.focus)}</p><button type="button" class="text-button" data-view="scope">企业资料与研究要求</button>`;
}

async function loadCompanyMethods(){
  const code=state.code;
  const [registry,requirement]=await Promise.all([api('/api/companies?'+query({cutoff:state.cutoff})),api('/api/research/requirements?'+query({code}))]);
  if(state.code!==code)return;
  $('#company-coverage').innerHTML=`<div class="table-wrap"><table class="method-table"><thead><tr><th>研究对象</th><th>企业类型</th><th>已登记报告</th><th>财务期间</th></tr></thead><tbody>${registry.data.map(p=>`<tr><td><b>${esc(p.name)}</b><span class="sub">${esc(p.listed?p.code:'非上市资料研究')}</span></td><td>${esc(p.segment)}</td><td>${esc(p.reports)}份</td><td>${esc(periodLabel(p.financial_period))}</td></tr>`).join('')}</tbody></table></div><p class="footnote">报告数量是已登记原件的覆盖，不代表每份财务与论据都已人工核验。用户登记企业需再导入真实资料。</p>`;
  $('#research-method').innerHTML=`<h3>${esc(names[code])} · ${esc(requirement.focus)}</h3><p class="footnote">${esc(requirement.owner)}。${esc(requirement.comparison_note)}</p><div class="table-wrap"><table class="method-table"><thead><tr><th>研究内容与输入</th><th>核对要求</th></tr></thead><tbody>${requirement.requirements.map(r=>`<tr><td><b>${esc(r.name)}</b><span class="sub">${esc(r.input)}</span></td><td>${esc(r.check)}</td></tr>`).join('')}</tbody></table></div><p class="footnote">${esc(requirement.quality_boundary)}</p>`;
}

const loadFeatureViewWithMethods=loadFeatureView;
loadFeatureView=async function(view){if(view==='scope')return loadCompanyMethods();return loadFeatureViewWithMethods(view);};
const renderReportWithMethods=renderReport;
renderReport=function(run){
  renderReportWithMethods(run);
  const r=run.research_requirements,c=run.research_coverage;if(!r||!c)return;
  const content=`<details class="trace-details research-method-details"><summary>企业研究要求与数据覆盖</summary><p>${esc(r.company_profile.segment)} · ${esc(r.focus)}</p><p class="footnote">${esc(r.owner)}</p><div class="table-wrap"><table class="method-table"><thead><tr><th>研究内容</th><th>数据与核验状态</th></tr></thead><tbody>${c.rows.map(row=>`<tr><td>${esc(row.name)}</td><td><b>${esc(row.status)}</b><span class="sub">${esc(row.detail)}</span></td></tr>`).join('')}</tbody></table></div><ul class="plain-list">${r.requirements.map(row=>`<li><b>${esc(row.name)}</b>：${esc(row.check)}</li>`).join('')}</ul><p class="footnote">${esc(r.comparison_note)} ${esc(c.investment_effect)}</p></details>`;
  const body=$('#report-panel .report-body');if(body)body.insertAdjacentHTML('afterbegin',content);
};

const renderDecisionWithMethods=renderDecision;
renderDecision=function(run){
  const d=run.decision;if(!d?.document_mode)return renderDecisionWithMethods(run);
  return `<section class="decision-card"><div class="section-heading"><h3>资料研究与核验</h3><span class="small-tag">${esc(d.status)}</span></div><p>${esc(d.reason)}</p><h4>资料核验要求</h4>${decisionRows(d.entry_conditions,'先补充本企业原文。')}<h4>信息缺口</h4>${decisionRows(d.missing,'继续核对资料支持关系。')}<h4>相反证据复核</h4>${decisionRows(d.exit_conditions,'尚未提出可被后续数据验证的经营假设。')}</section>`;
};

function updateOperatingInputs(){
  const baseline=state.operatingBaseline,toggle=$('#overseas-scenario-enabled');
  toggle.disabled=!baseline?.available;if(toggle.disabled)toggle.checked=false;
  for(const id of ['overseas-revenue-change','overseas-margin-change','overseas-scenario-basis']){
    const input=$('#'+id);input.disabled=!toggle.checked;input.required=toggle.checked&&id!=='overseas-scenario-basis';
  }
  $('#operating-baseline').innerHTML=baseline?.available?`<p>${esc(periodLabel(baseline.period))}海外收入 ${number(baseline.revenue_yi)}亿元，海外毛利 ${number(baseline.gross_profit_yi)}亿元 · ${fileLink(baseline.source_id,baseline.pdf_page)}<br>毛利率按收入与成本原值复算，原报告显示 ${esc(baseline.reported_margin_pct)}%。</p>`:`<p>${esc(baseline?.reason||'请先加载企业的经营基数。')}</p>`;
}

const renderValuationWithOperating=renderValuation;
renderValuation=function(v){
  renderValuationWithOperating(v);const o=v.operating_scenario;if(!o?.available)return;
  $('#valuation-result').insertAdjacentHTML('beforeend',`<section class="panel valuation-output"><div class="section-heading"><h2>海外经营压力情景</h2><span class="small-tag">用户假设</span></div><p>${esc(periodLabel(o.baseline.period))} · ${fileLink(o.baseline.source_id,o.baseline.pdf_page)}<br>收入变化 ${esc(o.inputs.revenue_change_pct)}%，毛利率变化 ${esc(o.inputs.margin_change_pp)}个百分点。</p><div class="scenario-grid"><article class="scenario-card"><span>情景海外收入</span><b>${number(o.revenue_yi)}<small>亿元</small></b></article><article class="scenario-card"><span>情景海外毛利</span><b>${number(o.gross_profit_yi)}<small>亿元</small></b></article><article class="scenario-card"><span>海外毛利变化</span><b>${number(o.gross_profit_change_yi)}<small>亿元</small></b></article></div><p class="footnote">${esc(o.formula)}</p><p>${esc(o.inputs.basis||'情景背景未填写，保留为用户设定。')}</p><div class="notice subtle">${esc(o.note)}</div></section>`);
};

$('#overseas-scenario-enabled').addEventListener('change',updateOperatingInputs);
$('#register-listed').addEventListener('change',()=>{$('#register-code').disabled=!$('#register-listed').checked;$('#register-code').required=$('#register-listed').checked;if(!$('#register-listed').checked)$('#register-code').value='';});
$('#company-register').addEventListener('submit',catchTask(async event=>{
  event.preventDefault();if(state.busy)return;const button=$('#register-company');button.disabled=true;
  try{
    const registered=await post('/api/companies',{name:$('#register-name').value,listed:$('#register-listed').checked,code:$('#register-code').value,note:$('#register-note').value});
    state.status=await api('/api/status');initializeCompanies();await loadCompanyMethods();$('#company-register').reset();$('#register-code').disabled=true;
    $('#registration-result').textContent=`${registered.name}已登记。请在“补充资料”选择这家企业并导入真实原件；登记本身不产生财务数字。`;toast('企业已加入研究对象。');
  }finally{button.disabled=false;}
}));
$('#company').addEventListener('change',catchTask(async()=>{
  await renderCompanyScope();const p=state.companyProfiles.find(p=>p.code===state.code);
  if(p&&!p.listed)$('#question').value=`${p.name}的业务结构、竞争格局与经营风险有哪些可核对的证据？`;
  if(state.view==='scope')await loadCompanyMethods();
}));
