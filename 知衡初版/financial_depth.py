"""Registered consolidated pages, exact Decimal calculations and source-bound segments.

Registration is deliberately finite: an unfamiliar/revised report stays pending rather
than borrowing another report's figures. All numbers carry a physical-page source.
"""
from __future__ import annotations
import csv
import io
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

import core
import financials

BALANCE = {
    'cash': ['货币资金'], 'receivables': ['应收账款'], 'inventory': ['存货'],
    'current_assets': ['流动资产合计'], 'assets': ['资产总计'],
    'short_loans': ['短期借款'], 'long_loans': ['长期借款'], 'bonds': ['应付债券'],
    'payables': ['应付账款'], 'contract_liabilities': ['合同负债'],
    'current_liabilities': ['流动负债合计'], 'liabilities': ['负债合计'],
    'parent_equity': ['归属于母公司股东权益合计','归属于母公司所有者权益合计','归属于母公司所有者权益（或股东权益）合计'],
    'equity': ['股东权益合计','所有者权益合计','所有者权益（或股东权益）合计'],
    'goodwill': ['商誉'],
}
NAMES = dict(zip(BALANCE, ['货币资金','应收账款','存货','流动资产','总资产','短期借款','长期借款','应付债券',
                         '应付账款','合同负债','流动负债','总负债','归母权益','所有者权益','商誉']))
AMOUNT = re.compile(r'\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?|\(?-?\d+\.\d+\)?')

def fmt(value, precision='.01'):
    return str(Decimal(value).quantize(Decimal(precision), rounding=ROUND_HALF_UP))

def number(token):
    return Decimal(token.replace(',','').replace('(','-').replace(')',''))

def row_values(text, label):
    """An anchored labelled row only; no next-row fallthrough for blank amounts."""
    pattern = r'(?:^|\n)\s*' + financials.pattern(label)
    match = re.search(pattern, text)
    if not match: return None
    tail = text[match.end():].splitlines()
    if not tail: return None
    content = tail[0]
    # Notes are identifiers, not amounts. Wrapped amounts are allowed, labels are not.
    content = re.sub(r'[一二三四五六七八九十]+(?:、\d+|[（(][^）)]{1,20}[）)])', '', content)
    for line in tail[1:4]:
        if re.search(r'[\u4e00-\u9fffA-Za-z]', line): break
        content += ' ' + line
    values = [number(m.group()) for m in AMOUNT.finditer(content)]
    return (values, text[match.start():match.end()] + content) if values else None

@lru_cache(maxsize=1)
def registry():
    return json.loads((core.APP/'financial_depth_registry.json').read_text('utf-8'))['reports']

@lru_cache(maxsize=1)
def registered_pages():
    ids={r['source_id'] for r in registry()}; pages={}
    with (core.DATASET/'05_可检索文本/逐页语料.jsonl').open(encoding='utf-8') as fp:
        for line in fp:
            p=json.loads(line)
            if p['source_id'] in ids:pages[(p['source_id'],p['pdf_page'])]=p['text']
    return pages

def reference(source, page):
    return {'source_id':source['source_id'],'pdf_page':page,'publication_date':source['publication_date'],
            'source_sha256':source['sha256'],'file_url':f"/api/files/{source['source_id']}#page={page}"}

def field(source, page, value, prior, unit, excerpt, basis):
    factor=Decimal(1000 if unit=='千元' else 1)
    value=Decimal(value); prior=Decimal(prior) if prior is not None else None
    return dict(reference(source,page), value=str(value),prior=str(prior) if prior is not None else None,
                unit=unit,amount_yuan=str(value*factor),amount_yi=fmt(value*factor/100000000),
                prior_yi=fmt(prior*factor/100000000) if prior is not None else None,
                change_pct=fmt((value-prior)/prior*100) if prior is not None and prior>0 else None,
                basis=basis,excerpt=excerpt[:650],verification='登记原页 + 规则复算；仍需团队复审')

def ratio(name, numerator, denominator, formula, unit='%', note=''):
    n=Decimal(numerator['amount_yuan']); d=Decimal(denominator['amount_yuan'])
    refs=[{k:f[k] for k in ['source_id','pdf_page']} for f in [numerator,denominator]]
    return {'name':name,'value':fmt(n/d*(100 if unit=='%' else 1)) if d>0 else None,
            'unit':unit,'formula':formula,'terms':refs,'note':note}

def extract(record, source):
    if source['sha256']!=record['source_sha256']:raise ValueError('登记原件摘要已变化，须重新核对财务解剖数据')
    pages=registered_pages(); fields={}; flags=[]
    for key,labels in BALANCE.items():
        for page in record['balance_pages']:
            text=pages[(source['source_id'],page)]
            # A consolidated page can start the parent-company table at its bottom.
            text=re.split(r'(?:^|\n)\s*母公司资产负债表',text)[0]
            found=next((r for label in labels if (r:=row_values(text,label))),None)
            if found and len(found[0])>=2:
                values,excerpt=found
                fields[key]=field(source,page,values[0],values[1],record['unit'],excerpt,'合并口径；期末对比本报告列示期初')
                break
    required=['assets','liabilities','equity','cash','receivables','inventory','current_assets','current_liabilities']
    if any(k not in fields for k in required):raise ValueError('登记资产负债表未能可靠识别必要字段')
    for index in ['amount_yuan']:
        discrepancy=Decimal(fields['assets'][index])-Decimal(fields['liabilities'][index])-Decimal(fields['equity'][index])
        if abs(discrepancy)>Decimal('.02'):raise ValueError('合并资产负债恒等式未通过，数据隔离')
    prior_diff=Decimal(fields['assets']['prior'])-Decimal(fields['liabilities']['prior'])-Decimal(fields['equity']['prior'])
    if abs(prior_diff)>Decimal('.02'):raise ValueError('期初资产负债恒等式未通过，数据隔离')
    cf_page=record['capex_page'];text=pages[(source['source_id'],cf_page)]
    capex=row_values(text,'购建固定资产、无形资产和其他长期资产支付的现金')
    if not capex or len(capex[0])<2:raise ValueError('资本开支行识别失败')
    fields['capex']=field(source,cf_page,abs(capex[0][0]),abs(capex[0][1]),record['unit'],capex[1],
                         '合并现金流；购建长期资产支付现金的绝对值；不含收购子公司或全部投资支出')
    metrics=next((m for m in financials.metrics(source['report_period'],source['publication_date']) if m['source_id']==source['source_id']),None)
    ratios=[ratio('资产负债率',fields['liabilities'],fields['assets'],'总负债 ÷ 总资产 × 100'),
            ratio('流动比率',fields['current_assets'],fields['current_liabilities'],'流动资产 ÷ 流动负债','倍'),
            ratio('商誉占总资产',fields['goodwill'],fields['assets'],'商誉 ÷ 总资产 × 100')]
    proxy=None
    if metrics:
        cash=Decimal(metrics['cashflow'])*Decimal(metrics['factor_to_yuan']);cap=Decimal(fields['capex']['amount_yuan'])
        proxy={'name':'经营现金流减购建长期资产现金支出','amount_yi':fmt((cash-cap)/100000000),
               'formula':f"{metrics['cashflow_yi']}亿元 - {fields['capex']['amount_yi']}亿元（计算采用未舍入原值）",
               'terms':[{'source_id':source['source_id'],'pdf_page':metrics['calculations']['cashflow']['pdf_page']},
                        {'source_id':source['source_id'],'pdf_page':cf_page}],
               'note':'这是有限口径现金余额指标，未处理净融资、租赁、收购及少数股东分摊，不能直接充当FCFE或FCFF。'}
    total=Decimal(record['operating_revenue']); segments=[]
    for item in record['segments']+record['regions']:
        value=Decimal(item['value']);prior=Decimal(item['prior']) if item.get('prior') is not None else None
        excerpt=pages[(source['source_id'],item['page'])]
        # Curated values must occur on the original page, including line-wrapped decimals.
        compact=re.sub(r'\s+','',excerpt).replace(',','')
        if str(value) not in compact or (prior is not None and str(prior) not in compact):raise ValueError('分部登记金额在原页不存在')
        f=field(source,item['page'],value,prior,record['unit'],item['label']+'；金额核对原页',item.get('basis',record['segment_basis']))
        f.update(label=item['label'],group=item['group'],parent=item.get('parent'),share_pct=fmt(value/total*100),
                 denominator=str(total),denominator_label='本报告营业收入 / 对外收入，非营业总收入')
        segments.append(f)
    for group in ['产品','地区']:
        top=[Decimal(x['value']) for x in segments if x['group']==group and not x.get('parent')]
        if top and abs(sum(top)-total)>Decimal('.02'):raise ValueError('分部或地区合计未匹配营业收入')
    shares=dict(record['shares'],**reference(source,record['shares']['page']))
    share_text=re.sub(r'\s+','',pages[(source['source_id'],shares['page'])]).replace(',','')
    if str(shares['total']) not in share_text:raise ValueError('期末股份总数未匹配登记原页')
    if sum(int(x['count']) for x in shares['classes'])!=int(shares['total']):raise ValueError('股份类别合计不匹配')
    shares.update(total_yi=str(Decimal(shares['total'])/100000000),
                  note='报告期末已发行股份，未扣库存股、未考虑潜在稀释；不等同于EPS加权平均股数或研究日即时股数。不同上市类别不共用同一市场价格。')
    flags+=record['notes']
    flags+=['资产负债变动率是期末对期初，半年度不是同比；季节性和合并范围变化需回看附注。',
            '货币资金包含可能受限的款项，不等于可自由分配现金；借款科目不覆盖全部带息债务。']
    return {'available':True,'company':core.COMPANIES[source['stock_code']],'code':source['stock_code'],
            'period':source['report_period'],'publication_date':source['publication_date'],'source_id':source['source_id'],
            'source_sha256':source['sha256'],'fields':fields,'ratios':ratios,'cash_proxy':proxy,'segments':segments,'shares':shares,
            'operating_revenue_yi':fmt(total*Decimal(1000 if record['unit']=='千元' else 1)/100000000),
            'notes':flags,'verification':'已登记6份财报原页；规则复算，非独立专家认证'}

def snapshot(code, cutoff, period=None):
    if code not in core.COMPANIES:raise ValueError('请选择公司')
    core.validate_cutoff(cutoff)
    period=period or core.available_period(code,cutoff)
    eligible=[s for s in core.manifest()['sources'] if s.get('stock_code')==code and s.get('report_period')==period and s['publication_date']<=cutoff]
    if not eligible:return {'available':False,'code':code,'period':period,'reason':'该研究时点尚未披露所选期间财报'}
    source=max(eligible,key=lambda s:s['publication_date'])
    record=next((r for r in registry() if r['source_id']==source['source_id']),None)
    if not record:return {'available':False,'code':code,'period':period,'reason':'该报告尚未登记资产负债、分部和股本原页；不会套用其他期间数据'}
    return dict(extract(record,source),cutoff=cutoff)

def evidence_locations(pack):
    if not pack.get('available'):return []
    refs=[(f['source_id'],f['pdf_page']) for f in pack['fields'].values()]
    refs += [(f['source_id'],f['pdf_page']) for f in pack['segments']]
    refs.append((pack['source_id'],pack['shares']['page']))
    return list(dict.fromkeys(refs))

def export_csv(code,cutoff,period=None):
    pack=snapshot(code,cutoff,period);out=io.StringIO();writer=csv.writer(out)
    writer.writerow(['公司','期间','披露日期','指标','人民币亿元','期初/同期亿元','变动%','比较口径','来源编号','物理页码','来源SHA256'])
    if pack['available']:
        for key,f in pack['fields'].items():writer.writerow([pack['company'],pack['period'],pack['publication_date'],NAMES.get(key,'购建长期资产现金支出'),f['amount_yi'],f['prior_yi'],f['change_pct'],f['basis'],f['source_id'],f['pdf_page'],f['source_sha256']])
        for f in pack['segments']:writer.writerow([pack['company'],pack['period'],pack['publication_date'],f['group']+'：'+f['label'],f['amount_yi'],f['prior_yi'],f['change_pct'],f['basis'],f['source_id'],f['pdf_page'],f['source_sha256']])
    return '\ufeff'+out.getvalue()
