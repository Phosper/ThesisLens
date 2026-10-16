"""Finite physical-page locators and evidence delivery state; never infer non-disclosure."""
import json,re
import core

INTENTS=[
 (r'应收|欠款|货款|客户.{0,8}(?:欠|没付)|回款','应收账款','receivables'),
 (r'存货|库存|压货|钱压|货上','存货','inventory'),
 (r'限售|普通股|股份|发行','股份总数 股本','shares'),
 (r'设备|长期资产|资本开支','购建固定资产、无形资产和其他长期资产支付的现金','capex'),
 (r'中国以外|国外|境外|外销|海外','中国境外 外销 海外 营业收入 营业成本','foreign'),
 (r'经营收支|现金流|经营现金','经营活动产生的现金流量净额','cashflow'),
 (r'总负债|所有者权益|资产负债|总资产','资产总计 负债合计 所有者权益合计','balance'),
 (r'收入结构|烟机|灶具|分产品','分产品 营业收入','segments'),
]

def intents(query):return [key for pattern,terms,key in INTENTS if re.search(pattern,query)]

def expand(query):return query+' '+' '.join(terms for pattern,terms,key in INTENTS if re.search(pattern,query))

def registered(code,cutoff,period):
    eligible=[s for s in core.manifest()['sources'] if s.get('stock_code')==code and s.get('report_period')==period and s['publication_date']<=cutoff]
    if not eligible:return None
    latest=max(eligible,key=lambda s:s['publication_date'])
    records=json.loads((core.APP/'financial_note_registry.json').read_text('utf-8'))['reports']
    row=next((r for r in records if r['source_id']==latest['source_id']),None)
    return row if row and row['source_sha256']==latest['sha256'] else None

def locations(code,cutoff,period):
    r=registered(code,cutoff,period)
    return list(dict.fromkeys((r['source_id'],p) for topic in r['topics'] for p in topic['pages'])) if r else []

def coverage(code,cutoff,period,evidence):
    r=registered(code,cutoff,period);rows=[]
    for topic in (r or {}).get('topics',[]):
        found=[{'pdf_page':p,'citations':[e['citation'] for e in evidence if e['source_id']==r['source_id'] and e.get('pdf_page')==p]} for p in topic['pages']]
        complete=all(p['citations'] for p in found)
        rows.append({'name':topic['name'],'source_id':r['source_id'],'source_sha256':r['source_sha256'],'pages':found,
                     'status':'已定位并取回原页' if complete else '已定位，部分原页本次未取回','scope':topic['scope']})
    return {'registered':bool(r),'rows':rows,'note':'原页金额与结论支持关系仍待核验；未登记或本次未取回不能表述为公司未披露。'}

def search_priority(query):
    import financial_depth
    wanted=intents(query);targets=set()
    for r in financial_depth.registry():
        if any(k in wanted for k in ['receivables','inventory','balance']):targets.update((r['source_id'],p) for p in r['balance_pages'])
        if 'capex' in wanted or 'cashflow' in wanted:targets.add((r['source_id'],r['capex_page']))
        if 'shares' in wanted:targets.add((r['source_id'],r['shares']['page']))
        if 'foreign' in wanted or 'segments' in wanted:targets.update((r['source_id'],s['page']) for s in r['segments']+r['regions'])
    return targets
