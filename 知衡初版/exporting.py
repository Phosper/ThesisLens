"""Portable HTML memo and financial CSV, alongside exact JSON process exports."""
import csv
import html
import io
import re
import core
import financials
import workbench
import decision
import research
import audit
import research_requirements
import operating_scenarios

def report_view(view):
    if view not in ['brief','full']:raise ValueError('报告展示应为brief或full')
    return view

def prepare_run(run):
    """Refresh presentation without changing the saved model response or historical record."""
    result=dict(run)
    result['human_review']=workbench.quality(run)
    result['comparison_checks']=decision.comparison_checks(run)
    original=run.get('decision_at_generation') if 'decision_at_generation' in run else run.get('decision')
    result['decision_at_generation']=original
    result['decision']=decision.build(result,historical=not bool(original))
    result['audit_at_generation']=run.get('audit_at_generation',run.get('audit'))
    result['audit']=audit.snapshot(run['id'])
    if run.get('demo_original') and result['audit_at_generation']:
        result['audit']['historical_note']='当前恢复没有发起新的模型请求；原保存记录的审计快照另存于audit_at_generation，不追补历史日志。'
    return result

def memo_markdown(run,view='full'):
    report_view(view);run=prepare_run(run);quality=run['human_review']
    if view=='full':text=research.markdown(run)
    else:
        label='资料研究简略版' if run['decision'].get('document_mode') else '投资判断简略版'
        text=f"# 知衡 · {run['company']}{label}\n\n研究截止日：{run['cutoff']}；财务期间：{run['period'] or '待核对'}；运行编号：{run['id']}\n\n"
        text+=decision.markdown(run['decision'],run['comparison_checks'])
        text+='\n## 研究摘要\n\n'+run['draft']['summary']+'\n\n## 关键风险与保留事项\n\n'
        text+=research_requirements.markdown(run)
        text+=operating_scenarios.markdown((run.get('valuation') or {}).get('operating_scenario'))
        for row in run['draft'].get('risks',[]):text+='- '+row['text']+' '+''.join(f'[{c}]' for c in row.get('citations',[]))+'\n'
        for issue in run['review'].get('issues',[]):text+=f"- 模型复核 {issue.get('severity','待核验')}：{issue.get('claim','')}。{issue.get('reason','')}\n"
        for warning in run.get('warnings',[]):text+='- '+warning+'\n'
        valuation=run.get('valuation') or {}
        basis=valuation.get('pe_basis') or {}
        reference=valuation.get('market_pe') or {}
        if valuation:
            text+='\n## 估值依据与参考PE\n\n倍数依据：'+str(basis.get('text') or '尚未提供，仍为演示假设')+'；'+('用户声明已人工复核，仍需核对来源。' if basis.get('reviewed') is True else '尚未完成人工复核。')+'\n'
            if reference.get('available'):
                text+=f"保存日期A股参考PE：{reference['pe']}倍；价格日期{reference.get('price_date')}，人民币{reference.get('price_yuan')}元/股。{reference.get('shares_basis','')} {reference.get('note','')}\n"
            else:text+='参考PE尚不可计算：'+str(reference.get('reason') or '旧记录未保存此项计算，需重新核对估值。')+'\n'
        text+='\n## 证据目录\n\n'
        for e in run['evidence']:
            source=core.source(e['source_id']);local=core.file_for(source).as_posix()
            original=audit.original_url(e['source_id'],run['id'],e.get('pdf_page'))
            text+=f"- [{e['citation']}] {e['title']} · {e['locator']} · 披露日期{e['publication_date']} · [本机原页]({original}) · [本地原件](<{local}>) · [公开来源]({e.get('source_url','')})\n"
    text+='\n## 人工核验记录\n'
    if not quality['notes']:text+='尚无人工核验记录；不能把程序检查分当作事实正确率。\n'
    for note in quality['notes']:
        label={'pending':'待核验','confirmed':'人工已核对','refuted':'已有反证'}[note['state']]
        text+=f"- {note['claim_id']}：{label}。{note['note']}；记录时间{note['updated_at']}\n"
    text+=audit.markdown(run['audit'])
    return text

def memo_html(run,view='full'):
    report_view(view);run=prepare_run(run)
    def esc(text):return html.escape(str(text))
    evidence={e['citation']:e for e in run['evidence']}
    def paragraph(text):
        text=esc(text)
        return re.sub(r'\[(E\d+)\]',lambda m:f'<a href="#ref-{m[1]}">[{m[1]}]</a>' if m[1] in evidence else m[0],text).replace('\n','<br>')
    document_mode=run['decision'].get('document_mode')
    label=('资料研究简略版' if view=='brief' else '资料研究备忘录草稿') if document_mode else ('投资判断简略版' if view=='brief' else '买方投资备忘录草稿')
    pieces=[f'<h1>{esc(run["company"])}{label}</h1>',f'<p class="meta">知衡 ThesisLens · 研究时点 {esc(run["cutoff"])} · {esc(financials.period_label(run["period"]))} · {esc(run["mode_label"])}</p>']
    d=run['decision'];profile=d.get('profile',{})
    pieces.append('<section class="decision"><h2>'+('资料研究与核验' if document_mode else '投资判断')+'</h2><h3>'+esc(d['status'])+'</h3><p>'+paragraph(d['reason'])+'</p>')
    if not document_mode:
        pieces.append('<p>研究目标：'+esc(d['objective'])+'；观察期限：'+esc(d['horizon_months'])+'个月（研究假设）。</p>')
        pieces.append('<p>投入上限：'+(esc(profile['budget_yuan'])+'元' if profile.get('budget_yuan') is not None else '尚未提供')+'；可接受损失上限：'+(esc(profile['max_loss_pct'])+'%' if profile.get('max_loss_pct') is not None else '尚未提供')+'。这些约束不代表系统建议仓位或保证损失上限。</p>')
    state=d.get('review_status',{})
    pieces.append('<p class="meta">'+esc(state.get('label','待人工核验'))+'。'+esc(state.get('scope',''))+'</p>')
    if state.get('compatibility_view'):pieces.append('<p class="notice">历史记录补充视图：本页依据保存资料整理，不代表原模型已输出或人工已核验。</p>')
    sections=[('basis','判断依据'),('entry_conditions','资料核验' if document_mode else '进入研究候选的条件'),('exit_conditions','相反证据复核' if document_mode else '重新评估与退出条件')]
    for key,title in sections:
        pieces.append('<h3>'+title+'</h3><ul>')
        for row in d.get(key,[]):
            pieces.append('<li>'+paragraph(row['text'])+' '+''.join(f'<a href="#ref-{esc(c)}">[{esc(c)}]</a> ' for c in row.get('citations',[]))+('；关联论据 '+esc(','.join(row['thesis_ids'])) if row.get('thesis_ids') else '')+'</li>')
        pieces.append('</ul>')
    pieces.append('<h3>'+('财务与估值适用性' if document_mode else '情景回报与下行空间')+'</h3><ul>')
    for row in d.get('return_scenarios',[]):
        price_return=row.get('price_return_pct');total=row.get('total_return_pct')
        pieces.append('<li>'+esc(row['label'])+'：价格空间 '+(esc(price_return)+'%' if price_return is not None else '尚未计算')+'；含股利及费用的情景回报 '+(esc(total)+'%' if total is not None else '股利或费率假设尚未补齐')+'。'+esc(row.get('note',''))+'</li>')
    if not d.get('return_scenarios'):pieces.append('<li>'+('非上市资料研究，不套用上市公司PE或交易条件。' if document_mode else '尚未附带可计算的估值情景，无法给出回报范围。')+'</li>')
    pieces.append('</ul>'+('' if document_mode else '<p>情景结果依赖用户输入，可能收益与损失均非保证；不是目标价或自动买卖评级。</p>'))
    if d.get('missing'):pieces.append('<h3>尚需补齐</h3><ul>'+''.join('<li>'+esc(m)+'</li>' for m in d['missing'])+'</ul>')
    pieces.append('</section>')
    checks=run.get('comparison_checks',[])
    if checks:
        pieces.append('<section class="notice"><h2>口径与推断检查</h2><ul>')
        for c in checks:pieces.append('<li>'+esc(c['severity'])+'：'+paragraph(c['claim'])+'。'+paragraph(c['reason'])+'</li>')
        pieces.append('</ul></section>')
    pieces.append('<h2>研究摘要</h2><p>'+paragraph(run['draft']['summary'])+'</p>')
    for key,name in [('thesis','投资论据'),('risks','风险与反向验证'),('invalidation','论据失效条件'),('monitoring','跟踪指标'),('open_questions','待核实问题')]:
        if view=='brief' and key!='risks':continue
        pieces.append('<h2>'+name+'</h2><ul>')
        for row in run['draft'][key]:
            label='<b>'+esc(row['id'])+'</b> ' if row.get('id') else ''
            links='；关联论据 '+esc(','.join(row['thesis_ids'])) if row.get('thesis_ids') else ''
            pieces.append('<li>'+label+paragraph(row['text'])+' '+''.join(f'<a href="#ref-{esc(c)}">[{esc(c)}]</a> ' for c in row['citations'])+links+'</li>')
        pieces.append('</ul>')
    if view=='full' and run.get('financial_depth',{}).get('available'):
        import financial_depth
        d=run['financial_depth'];pieces.append('<h2>财务解剖与口径</h2><ul>')
        for k,f in d['fields'].items():pieces.append(f'<li>{esc(financial_depth.NAMES.get(k,"购建长期资产现金支出"))}：{esc(f["amount_yi"])}亿元；期初/同期{esc(f["prior_yi"])}亿元；{esc(f["basis"])}；物理第{f["pdf_page"]}页。</li>')
        for r in d['ratios']:pieces.append(f'<li>{esc(r["name"])}：{esc(r["value"])}{esc(r["unit"])}；{esc(r["formula"])}。</li>')
        for s in d['segments']:pieces.append(f'<li>{esc(s["group"])} · {esc(s["label"])}：{esc(s["amount_yi"])}亿元；同比{esc(s["change_pct"] if s["change_pct"] is not None else "未取得")}%；分母{esc(s.get("denominator_label","营业收入"))} {esc(s.get("denominator_yi",d["operating_revenue_yi"]))}亿元；{esc(s.get("growth_basis","按本报告同口径原值复算"))}；{esc(s["source_id"])}物理第{s["pdf_page"]}页；{esc(s["basis"])}。</li>')
        if d.get('segment_note'):pieces.append('<li>'+esc(d['segment_note'])+'</li>')
        sh=d['shares'];pieces.append(f'<li>报告期末股份：{sh["total"]}股；{esc(sh["source_id"])}物理第{sh["pdf_page"]}页。{esc(sh["note"])}<ul>')
        pieces.extend(f'<li>{esc(c["label"])}：{c["count"]}股。</li>' for c in sh['classes'])
        pieces.append('</ul></li></ul><p>'+esc(d['cash_proxy']['name'])+'：'+esc(d['cash_proxy']['amount_yi'])+'亿元。'+esc(d['cash_proxy']['note'])+'</p>')
        pieces.extend('<p>'+esc(n)+'</p>' for n in d['notes'])
    requirement=run.get('research_requirements')
    if run.get('disclosure_coverage'):
        pieces.append('<h2>金额附注取回状态</h2><ul>')
        for row in run['disclosure_coverage']['rows']:pieces.append('<li>'+esc(row['name'])+'：'+esc(row['status'])+'；'+esc(row['source_id'])+'；物理页'+','.join(str(p['pdf_page']) for p in row['pages'])+'</li>')
        pieces.append('</ul><p>'+esc(run['disclosure_coverage']['note'])+'</p>')
    if requirement:
        pieces.append('<h2>研究要求与数据覆盖</h2><p>'+esc(requirement['focus'])+'。'+esc(requirement['owner'])+'</p><ul>')
        for row in requirement['requirements']:pieces.append('<li>'+esc(row['name'])+'：'+esc(row['input'])+'。'+esc(row['check'])+'</li>')
        for row in (run.get('research_coverage') or {}).get('rows',[]):pieces.append('<li>'+esc(row['name'])+'：'+esc(row['status'])+'。'+esc(row['detail'])+'</li>')
        pieces.append('</ul><p>'+esc(requirement['comparison_note'])+'</p>')
    operating=(run.get('valuation') or {}).get('operating_scenario')
    if operating and operating.get('available'):
        pieces.append('<h2>海外经营压力情景</h2><p>'+paragraph(operating_scenarios.markdown(operating).split('\n',2)[2])+'</p>')
    if run.get('valuation'):
        v=run['valuation'];market=v.get('market_pe',{});basis=v.get('pe_basis',{})
        pieces.append('<h2>估值依据与参考市盈率</h2><p>倍数依据：'+esc(basis.get('text') or '尚未提供，仍为演示假设')+'；'+('用户声明已人工复核，仍需核对原件与适用范围' if basis.get('reviewed') is True else '尚未完成人工复核')+'。</p>')
        if market.get('available'):
            pieces.append('<p>A股报价对应的参考PE：'+esc(market['pe'])+'倍；价格日期 '+esc(market.get('price_date'))+'，人民币 '+esc(market.get('price_yuan'))+'元/股。'+esc(market.get('basis',''))+'。'+esc(market.get('note',''))+'</p>')
        else:pieces.append('<p>参考PE尚不可计算：'+esc(market.get('reason','旧记录尚未保存该计算，请重新核对估值'))+'</p>')
        pieces.append('<h2>估值情景（用户假设）</h2><ul>')
        for s in v['pe_scenarios']:pieces.append(f'<li>{esc(s["label"])}：{esc(s["formula"])} = {esc(s["equity_value_yi"])}亿元；每股情景 '+(esc(s['per_share_yuan'])+'元' if s.get('per_share_yuan') is not None else '未选股数，无法计算')+'</li>')
        pieces.append('</ul><p>情景结果不是目标价，假设与股数仍需核验。</p>')
    if view=='full' and run.get('retrieval'):
        r=run['retrieval'];pieces.append('<h2>检索方法</h2><p>'+esc(r['method'])+' · 检索记录 '+esc(r['id'])+'</p><ul>')
        for q in r['queries']:pieces.append('<li>'+esc(q)+'</li>')
        pieces.append('</ul>')
    pieces.append('<h2>核验记录</h2><p>'+paragraph(run['review']['summary'])+'</p><ul>')
    for issue in run['review'].get('issues',[]):pieces.append('<li>'+esc(issue.get('severity',''))+'：'+esc(issue.get('claim',''))+'；'+esc(issue.get('reason',''))+'</li>')
    pieces.append('</ul><h2>人工核验</h2><ul>')
    human_notes=run['human_review']['notes']
    if not human_notes:pieces.append('<li>尚无人工核验记录。</li>')
    for note in human_notes:pieces.append('<li>'+esc(note['claim_id'])+' · '+esc({'pending':'待核验','confirmed':'人工已核对','refuted':'已有反证'}.get(note['state'],note['state']))+' · '+esc(note['note'])+'</li>')
    pieces.append('</ul><h2>请求与资料访问审计</h2>')
    summary=run['audit'];attempts=summary['model_attempts']
    pieces.append('<p>'+esc(summary['scope'])+'</p><p>已登记事件 '+esc(summary['event_count'])+' 条；模型请求成功 '+esc(sum(row.get('status')=='success' for row in attempts))+' 次，失败 '+esc(sum(row.get('status')=='failed' for row in attempts))+' 次。</p>')
    if summary.get('historical_note'):pieces.append('<p>'+esc(summary['historical_note'])+'</p>')
    if summary.get('truncated'):pieces.append('<p>当前快照已截断，返回最近 '+esc(summary['returned_events'])+' 条；完整记录保存在本机审计库。</p>')
    pieces.append('<h2>证据目录</h2><ol>')
    for e in run['evidence']:
        url=e.get('source_url','')
        href=html.escape(url,quote=True) if url.startswith(('https://','http://')) else '#'
        original=html.escape(audit.original_url(e['source_id'],run['id'],e.get('pdf_page')),quote=True)
        pieces.append(f'<li id="ref-{esc(e["citation"])}"><b>[{esc(e["citation"])}]</b> {esc(e["title"])} · {esc(e["locator"])} · 披露日期{esc(e["publication_date"])} · <a href="{original}">查看本机原页</a> · <a href="{href}">公开来源</a><br>来源编号：{esc(e["source_id"])}</li>')
    pieces.append('</ol><h2>保留事项</h2><ul>'+''.join('<li>'+esc(w)+'</li>' for w in run['warnings'])+'</ul>')
    style='body{font:15px/1.85 system-ui,"Microsoft YaHei",sans-serif;color:#243b3e;max-width:900px;margin:40px auto;padding:25px}h1{font-size:26px}h2{font-size:20px;border-bottom:1px solid #cbdad6;padding-bottom:8px;margin-top:32px}h3{font-size:16px}a{color:#1c7068}.meta{color:#637975}.decision{background:#f5f8f3;padding:16px 22px}.notice{background:#fff5e7;padding:12px 18px}li{margin:9px 0}#toolbar{padding:15px;background:#f0f6f3}button{padding:10px 20px;border:0;background:#1c7068;color:white;cursor:pointer}@media print{#toolbar{display:none}body{margin:0;padding:0;font-size:11pt}.decision{background:transparent;padding:0}h2,h3{break-after:avoid}li{break-inside:avoid}a{color:inherit;text-decoration:none}@page{size:A4;margin:20mm}}'
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>知衡 · 投资备忘录</title><style>'+style+'</style></head><body><div id="toolbar"><button onclick="window.print()">打印 / 保存为PDF</button> 使用浏览器打印功能导出，正文含证据目录。</div>'+''.join(pieces)+'</body></html>'

def financial_csv(code,cutoff):
    output=io.StringIO();writer=csv.writer(output)
    writer.writerow(['公司','代码','期间','披露日期','指标','金额原值','原始单位','人民币亿元','同比%','同比基期','来源编号','物理页码','核验状态'])
    for row in financials.history(code,cutoff)['data']:
        for key,f in row['fields'].items():writer.writerow([row['company'],row['code'],row['period'],row['publication_date'],financials.NAMES[key],f['value'],f['unit'],f.get('amount_yi'),f.get('growth'),f.get('prior'),row['source_id'],f['page'],row['status']])
    return '\ufeff'+output.getvalue()
