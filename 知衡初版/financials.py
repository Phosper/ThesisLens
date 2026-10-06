"""Rule extraction of primary financial tables, with explicit verification states."""
from __future__ import annotations
import hashlib
import json
import re
import threading
from decimal import Decimal, ROUND_HALF_UP

import core

LABELS = {
    'revenue': ['营业收入'],
    'profit': ['归属于上市公司股东的净利润', '归属于上市公司股东的净利润'],
    'core_profit': ['归属于上市公司股东的扣除非经常性损益的净利润'],
    'cashflow': ['经营活动产生的现金流量净额'],
    'basic_eps': ['基本每股收益'],
    'equity': ['归属于上市公司股东的净资产', '归属于上市公司股东的所有者权益'],
    'assets': ['总资产'],
}
NAMES = {'revenue':'营业收入','profit':'归母净利润','core_profit':'扣非净利润','cashflow':'经营现金流净额',
         'basic_eps':'基本每股收益','equity':'归母净资产','assets':'总资产'}
FLOWS = ['revenue','profit','core_profit','cashflow']
NUMBER = re.compile(r'[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-−]?\d+\.\d+|[-−]?\d+')
_lock = threading.RLock()
_cache = None
_signature = None

def pattern(label):
    return r'\s*'.join(map(re.escape,label))

def period_label(period):
    if not period: return '未指定'
    year,part=period.split('-')
    return year+{'FY':'年度','H1':'年上半年','Q1':'年一季度','Q3':'年前三季度'}.get(part,'年'+part)

def period_end(period):
    return period[:4]+{'FY':'-12-31','H1':'-06-30','Q1':'-03-31','Q3':'-09-30'}[period[5:]]

def row_for(text,key):
    matches=[]
    for label in LABELS[key]:
        match=re.search(pattern(label),text)
        if match: matches.append(match)
    if not matches: return None
    match=min(matches,key=lambda m:m.start())
    end=len(text)
    # Stop before the next labelled financial row, even when labels wrap across lines.
    for labels in list(LABELS.values())+[['利润总额','稀释每股收益','加权平均净资产收益率','非经常性损益项目','追溯调整或重述原因']]:
        for label in labels:
            nxt=re.search(pattern(label),text[match.end():])
            if nxt: end=min(end,match.end()+nxt.start())
    content=text[match.end():end]
    # Remove units and page headers so 元/股 and years cannot become table values.
    content=re.sub(r'[（(][^）)]{0,35}[）)]',' ',content)
    content=re.split(r'公司最近|公司报告期|本报告期末|本年末比|本报告期比|本报告期末比',content)[0]
    nums=[Decimal(m.group().replace(',','').replace('−','-')) for m in NUMBER.finditer(content)]
    return match,nums,text[match.start():min(end,match.start()+650)]

def extract_source(source,pages):
    period=source['report_period']; rows={}; flags=[]; chosen=None
    candidates=[]
    for page in pages:
        if page['pdf_page']>20: continue
        text=page['text']
        previous=next((p for p in pages if p['pdf_page']==page['pdf_page']-1),None)
        heading=re.sub(r'\s+','',text+(previous['text'][-1600:] if previous else ''))
        if not any(x in heading for x in ['主要会计数据','主要财务数据','主要财务指标']): continue
        count=sum(bool(row_for(text,key)) for key in FLOWS)
        if count>=3: candidates.append((count,-page['pdf_page'],page))
    if not candidates:
        return {'code':source['stock_code'],'period':period,'source_id':source['source_id'],'status':'待人工核对',
                'fields':{},'publication_date':source['publication_date'],'period_end':period_end(period),
                'flags':['未定位完整的主要会计数据表，未把缺失字段补成零。']}
    chosen=max(candidates,key=lambda x:x[:2])[2]
    next_page=next((p for p in pages if p['pdf_page']==chosen['pdf_page']+1),None)
    compact=re.sub(r'\s+','',chosen['text'])
    adjusted='调整后' in compact and '调整前' in compact
    q3=period.endswith('Q3') and '年初至报告期末' in compact
    # Header positions matter: Haier Q3 columns can be 调整前/调整后 or 调整后/调整前.
    prefix=compact[:compact.find('营业收入')] if '营业收入' in compact else compact[:650]
    after_first=prefix.rfind('调整后')>prefix.rfind('调整前')
    for key in LABELS:
        page=chosen; row=row_for(page['text'],key)
        if not row and next_page:
            page=next_page; row=row_for(page['text'],key)
        if not row: continue
        match,nums,excerpt=row
        if len(nums)<2: continue
        unit_match=re.search(r'[（(]\s*(千\s*元|万\s*元|元)',excerpt)
        unit=re.sub(r'\s+','',unit_match.group(1)) if unit_match else ('千元' if source['stock_code']=='000333' and '千元' in page['text'] else '元')
        factor={'元':Decimal(1),'千元':Decimal(1000),'万元':Decimal(10000)}[unit]
        current,prior,growth=nums[0],nums[1],None
        basis='报告列示的上年同期'; method='current-prior-yoy'
        if q3 and key in FLOWS+['basic_eps']:
            if adjusted and len(nums)>=8:
                current=nums[4];prior=nums[6] if after_first else nums[5];growth=nums[7]
            elif adjusted and len(nums)>=4 and key=='cashflow':
                current=nums[0];prior=nums[2] if after_first else nums[1];growth=nums[3]
            elif len(nums)>=4:
                current,prior,growth=nums[2],None,nums[3]
            elif key=='cashflow' and len(nums)==2:
                current,prior,growth=nums[0],None,nums[1]
            else:
                flags.append(NAMES[key]+'的三季度累计列未可靠识别');continue
            basis='年初至报告期末累计；同比来自报告列示';method='q3-cumulative'
        else:
            if adjusted and len(nums)>=4:
                # Most annual/half-year tables explicitly present 调整后 then 调整前.
                current=nums[0];prior=nums[1] if not after_first else nums[2];growth=nums[3]
                basis='报告列示的调整后上年同期' if key in FLOWS+['basic_eps'] else '调整后上年度末'
            elif len(nums)>=3: growth=nums[2]
        if key in ['assets','equity'] and current<Decimal('100000'):
            flags.append(NAMES[key]+'金额过小，需核对表头');continue
        if key in FLOWS and abs(current)<Decimal('10000'):
            flags.append(NAMES[key]+'金额或列位置异常');continue
        if key=='basic_eps':unit='元/股';factor=Decimal(1)
        recomputed=None
        if prior is not None and prior>0 and key in FLOWS+['basic_eps']:
            recomputed=((current-prior)/prior*100).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
            if growth is not None and abs(recomputed-growth)>Decimal('.06') and key!='basic_eps':
                flags.append(NAMES[key]+'同比重算与披露值不一致，字段隔离');continue
        elif prior is not None and prior<=0:
            basis+='；非正基期未进行常规同比校验'
        if growth is not None and key in FLOWS and abs(growth)>Decimal('5000'):
            flags.append(NAMES[key]+'同比列异常');continue
        rows[key]={'value':str(current),'prior':str(prior) if prior is not None else None,
                   'growth':str(growth) if growth is not None else None,'recomputed_growth':str(recomputed) if recomputed is not None else None,
                   'unit':unit,'factor_to_yuan':str(factor),'yuan':str(current*factor),
                   'amount_yi':str((current*factor/100000000).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if key!='basic_eps' else None,
                   'basis':basis,'method':method,'source_id':source['source_id'],'page':page['pdf_page'],'excerpt':excerpt,
                   'ocr': 'OCR' in page.get('text_origin','')}
    complete=all(key in rows for key in FLOWS)
    if adjusted: flags.append('存在调整前/调整后列；采用标记为调整后的同比基期，仍需回看表头。')
    if any(f['ocr'] for f in rows.values()):flags.append('含OCR文字，规则校验不能替代原页核对。')
    return {'code':source['stock_code'],'period':period,'source_id':source['source_id'],'page':chosen['pdf_page'],
            'fields':rows,'status':'规则提取通过' if complete else '部分字段待核对','flags':flags,
            'publication_date':source['publication_date'],'period_end':period_end(period),'flow_basis':'累计期间'}

def catalogue():
    global _cache,_signature
    sources=[s for s in core.manifest()['sources'] if s.get('report_period')]
    signature=hashlib.sha256(core.json_dump([(s['source_id'],s.get('sha256')) for s in sources]).encode()).hexdigest()
    with _lock:
        if _cache is not None and signature==_signature:return _cache
        pages={s['source_id']:[] for s in sources}
        with (core.DATASET/'05_可检索文本/逐页语料.jsonl').open(encoding='utf-8') as fp:
            for line in fp:
                p=json.loads(line)
                if p['source_id'] in pages and p['pdf_page']<=21:pages[p['source_id']].append(p)
        if hasattr(core,'imported_pages'):
            for p in core.imported_pages():
                if p['source_id'] in pages and p['pdf_page']<=21:pages[p['source_id']].append(p)
        result=[extract_source(s,pages[s['source_id']]) for s in sources]
        curated=json.loads((core.APP/'metrics.json').read_text('utf-8'))['metrics']
        curated+=json.loads((core.APP/'metrics_supplement.json').read_text('utf-8'))['metrics']
        for row in result:
            original=next((m for m in curated if m['source_id']==row['source_id']),None)
            if not original:continue
            for key in FLOWS:
                old=row['fields'].get(key,{})
                row['fields'][key]=dict(old,value=original[key],prior=original[key+'_prior'],growth=original[key+'_growth'],
                    recomputed_growth=original[key+'_growth'],unit=original['unit'],factor_to_yuan=original['factor_to_yuan'],
                    yuan=str(Decimal(original[key])*Decimal(original['factor_to_yuan'])),
                    amount_yi=str((Decimal(original[key])*Decimal(original['factor_to_yuan'])/100000000).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),
                    source_id=original['source_id'],page=original.get('field_pages',{}).get(key,original['page']),basis='人工登记；同比基期采用本报告列示值',
                    excerpt=old.get('excerpt',''),ocr=False)
            row['status']='人工登记 + 规则复算';row['page']=original['page'];row['note']=original['note']
        _cache=result;_signature=signature
        return result

def history(code='',cutoff='2026-10-06',kind=''):
    core.validate_cutoff(cutoff)
    if code and code not in core.COMPANIES:raise ValueError('请选择公司')
    rows=[dict(r,company=core.COMPANIES[r['code']],label=period_label(r['period'])) for r in catalogue()
          if (not code or r['code']==code) and r.get('publication_date',core.source(r['source_id'])['publication_date'])<=cutoff
          and (not kind or r['period'].endswith(kind))]
    rows.sort(key=lambda r:(r.get('period_end',period_end(r['period'])),r['code'],r['publication_date']))
    return {'data':rows,'coverage':{'reports':len(rows),'complete':sum(all(k in r['fields'] for k in FLOWS) for r in rows),
                                  'manual':sum(r['status'].startswith('人工') for r in rows)},
            'note':'四项流量指标采用报告期累计口径，三季度为1—9月；规则校验通过不等于人工审核通过。'}

def metrics(period,cutoff):
    output=[]
    latest={}
    for r in history(cutoff=cutoff)['data']:
        if r['period']==period and all(k in r['fields'] for k in FLOWS):latest[r['code']]=r
    for r in latest.values():
        if r['period']!=period or not all(k in r['fields'] for k in FLOWS):continue
        f=r['fields'];first=f['revenue'];s=core.source(r['source_id'])
        row={'code':r['code'],'company':r['company'],'period':period,'source_id':r['source_id'],'page':r['page'],
             'unit':first['unit'],'factor_to_yuan':first['factor_to_yuan'],'publication_date':s['publication_date'],
             'source_title':s['title'],'file_url':f"/api/files/{r['source_id']}#page={r['page']}",
             'note':r.get('note','规则提取四项累计指标，需结合原始表头和附注核验。'),
             'verification':r['status'],'flags':r['flags'],'calculation_basis':'合并口径；报告期累计；人民币亿元',
             'calculations':{}}
        for key in FLOWS:
            field=f[key]
            row[key]=field['value'];row[key+'_prior']=field['prior'];row[key+'_growth']=field['growth'];row[key+'_yi']=field['amount_yi']
            row['calculations'][key]={'original_value':field['value'],'prior_value':field['prior'],'original_unit':field['unit'],
                'to_yi_formula':f"{field['value']} × {field['factor_to_yuan']} ÷ 100000000",'amount_yi':field['amount_yi'],
                'yoy_formula':f"({field['value']} - {field['prior']}) ÷ {field['prior']} × 100" if field['prior'] else '原报告未列上年累计金额；只显示报告披露的同比，不倒推基期。',
                'computed_yoy':field['recomputed_growth'],'reported_yoy':field['growth'],'source_id':r['source_id'],'pdf_page':field['page']}
        row['cash_profit_ratio']=str((Decimal(f['cashflow']['yuan'])/Decimal(f['profit']['yuan'])).quantize(Decimal('.01'))) if Decimal(f['profit']['yuan']) else None
        if 'basic_eps' in f:row['basic_eps']=f['basic_eps']
        output.append(row)
    return output

def latest_period(code,cutoff):
    rows=[r for r in history(code,cutoff)['data'] if all(k in r['fields'] for k in FLOWS)]
    return rows[-1]['period'] if rows else None

def rolling(code,cutoff,field='profit'):
    latest_by_period={r['period']:r for r in history(code,cutoff)['data'] if field in r['fields']}
    rows=list(latest_by_period.values())
    if not rows:return {'available':False,'reason':'缺少可识别的财务数据'}
    latest=rows[-1];year=int(latest['period'][:4]);part=latest['period'][5:]
    if part=='FY':pieces=[(latest,1)]
    else:
        annual=next((r for r in rows if r['period']==f'{year-1}-FY'),None)
        # Use the current report's restated comparable base whenever explicitly available.
        prior=latest['fields'][field].get('prior')
        previous=next((r for r in rows if r['period']==f'{year-1}-{part}'),None)
        if not annual or (prior is None and not previous):return {'available':False,'reason':'TTM需要上年度、当期累计和上年同期间三项数据'}
        pieces=[(annual,1),(latest,1)]
        if prior is None:pieces.append((previous,-1))
    amount=sum(Decimal(r['fields'][field]['yuan'])*sign for r,sign in pieces)
    terms=[{'source_id':r['source_id'],'page':r['fields'][field]['page'],'period':r['period'],
            'value_yuan':r['fields'][field]['yuan'],'sign':sign} for r,sign in pieces]
    if part!='FY' and prior is not None:
        previous_yuan=Decimal(prior)*Decimal(latest['fields'][field]['factor_to_yuan'])
        amount-=previous_yuan
        terms.append({'source_id':latest['source_id'],'page':latest['fields'][field]['page'],
                      'period':f'{year-1}-{part}（本期列示基期）','value_yuan':str(previous_yuan),'sign':-1})
    return {'available':True,'field':field,'amount_yuan':str(amount),'amount_yi':str((amount/100000000).quantize(Decimal('.01'))),
            'latest_period':latest['period'],'period_end':latest['period_end'],'terms':terms,
            'formula':'上年度全年 + 当期累计 - 上年同期间累计' if part!='FY' else '最新年度全年',
            'note':'使用研究时点之前披露的数据；基期调整并不保证所有跨报告会计口径完全一致，仍需核对附注。'}
