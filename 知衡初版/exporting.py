"""Portable HTML memo and financial CSV, alongside exact JSON process exports."""
import csv
import html
import io
import re
import core
import financials
import workbench

def memo_markdown(run):
    text=run['markdown'];quality=workbench.quality(run)
    text+='\n## 人工核验记录\n'
    if not quality['notes']:text+='尚无人工核验记录；不能把程序检查分当作事实正确率。\n'
    for note in quality['notes']:
        label={'pending':'待核验','confirmed':'人工已核对','refuted':'已有反证'}[note['state']]
        text+=f"- {note['claim_id']}：{label}。{note['note']}；记录时间{note['updated_at']}\n"
    return text

def memo_html(run):
    def esc(text):return html.escape(str(text))
    evidence={e['citation']:e for e in run['evidence']}
    def paragraph(text):
        text=esc(text)
        return re.sub(r'\[(E\d+)\]',lambda m:f'<a href="#ref-{m[1]}">[{m[1]}]</a>' if m[1] in evidence else m[0],text).replace('\n','<br>')
    pieces=[f'<h1>{esc(run["company"])}买方投资备忘录草稿</h1>',f'<p class="meta">知衡 ThesisLens · 研究时点 {esc(run["cutoff"])} · {esc(financials.period_label(run["period"]))} · {esc(run["mode_label"])}</p>',
            '<h2>研究摘要</h2><p>'+paragraph(run['draft']['summary'])+'</p>']
    for key,name in [('thesis','投资论据'),('risks','风险与反向验证'),('invalidation','论据失效条件'),('monitoring','跟踪指标'),('open_questions','待核实问题')]:
        pieces.append('<h2>'+name+'</h2><ul>')
        for row in run['draft'][key]:pieces.append('<li>'+paragraph(row['text'])+' '+''.join(f'<a href="#ref-{esc(c)}">[{esc(c)}]</a> ' for c in row['citations'])+'</li>')
        pieces.append('</ul>')
    if run.get('valuation'):
        pieces.append('<h2>估值情景（用户假设）</h2><ul>')
        for s in run['valuation']['pe_scenarios']:pieces.append(f'<li>{esc(s["label"])}：{esc(s["formula"])} = {esc(s["equity_value_yi"])}亿元</li>')
        pieces.append('</ul><p>情景结果不是目标价，假设与股数仍需核验。</p>')
    pieces.append('<h2>核验记录</h2><p>'+paragraph(run['review']['summary'])+'</p><ul>')
    for issue in run['review'].get('issues',[]):pieces.append('<li>'+esc(issue.get('severity',''))+'：'+esc(issue.get('claim',''))+'；'+esc(issue.get('reason',''))+'</li>')
    pieces.append('</ul><h2>人工核验</h2><ul>')
    for note in workbench.notes(run['id']):pieces.append('<li>'+esc(note['claim_id'])+' · '+esc(note['state'])+' · '+esc(note['note'])+'</li>')
    pieces.append('</ul><h2>证据目录</h2><ol>')
    for e in run['evidence']:
        url=e.get('source_url','')
        href=html.escape(url,quote=True) if url.startswith(('https://','http://')) else '#'
        pieces.append(f'<li id="ref-{esc(e["citation"])}"><b>[{esc(e["citation"])}]</b> {esc(e["title"])} · {esc(e["locator"])} · 披露日期{esc(e["publication_date"])} · <a href="{href}">公开来源</a><br>来源编号：{esc(e["source_id"])}</li>')
    pieces.append('</ol><h2>保留事项</h2><ul>'+''.join('<li>'+esc(w)+'</li>' for w in run['warnings'])+'</ul>')
    style='body{font:15px/1.85 system-ui,"Microsoft YaHei",sans-serif;color:#243b3e;max-width:900px;margin:40px auto;padding:25px}h1{font-size:29px}h2{font-size:20px;border-bottom:1px solid #cbdad6;padding-bottom:8px;margin-top:32px}a{color:#1c7068}.meta{color:#637975}li{margin:9px 0}#toolbar{padding:15px;background:#f0f6f3}button{padding:10px 20px;border:0;background:#1c7068;color:white;cursor:pointer}@media print{#toolbar{display:none}body{margin:0;padding:0;font-size:11pt}h2{break-after:avoid}li{break-inside:avoid}a{color:inherit;text-decoration:none}@page{size:A4;margin:20mm}}'
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>知衡 · 投资备忘录</title><style>'+style+'</style></head><body><div id="toolbar"><button onclick="window.print()">打印 / 保存为PDF</button> 使用浏览器打印功能导出，正文含证据目录。</div>'+''.join(pieces)+'</body></html>'

def financial_csv(code,cutoff):
    output=io.StringIO();writer=csv.writer(output)
    writer.writerow(['公司','代码','期间','披露日期','指标','金额原值','原始单位','人民币亿元','同比%','同比基期','来源编号','物理页码','核验状态'])
    for row in financials.history(code,cutoff)['data']:
        for key,f in row['fields'].items():writer.writerow([row['company'],row['code'],row['period'],row['publication_date'],financials.NAMES[key],f['value'],f['unit'],f.get('amount_yi'),f.get('growth'),f.get('prior'),row['source_id'],f['page'],row['status']])
    return '\ufeff'+output.getvalue()
