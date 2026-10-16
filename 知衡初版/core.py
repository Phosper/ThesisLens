"""Local corpus indexing, dated retrieval and auditable financial calculations."""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import audit
import companies

APP = Path(__file__).resolve().parent
ROOT = APP.parent
DATASET = Path(os.environ.get('ZHIHENG_DATASET', str(ROOT/'知衡数据资料/家电行业_截至2026-10-06'))).resolve()
MANIFEST = DATASET/'00_来源与索引/资料总索引.json'
DATA = APP/'data'
INDEX = DATA/'index.sqlite3'
RUNS = DATA/'runs.sqlite3'
OVERRIDES = APP/'source_overrides.json'
DATA.mkdir(exist_ok=True)
COMPANIES = companies.names(include_local=False)
COMPANIES.update(companies.names())
EXPANSION = APP/'company_sources.json'
MARKET_EXPANSION = APP/'market_sources.json'
ALIASES = {'营收':'营业收入','收入':'营业收入','净利':'净利润','利润':'净利润','现金':'现金流',
           '扣非':'扣除非经常性损益','海外':'境外','外销':'境外','汇率':'汇兑','补贴':'以旧换新'}
TOPICS = ['营业收入','净利润','现金流','扣除非经常性损益','汇兑','衍生金融工具','存货','应收账款',
          '海外','境外','风险','回购','分红','以旧换新','家用电器','审计','关联交易','智能','工业']

class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

def json_dump(obj):
    return json.dumps(obj,ensure_ascii=False,separators=(',',':'))

def now():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec='seconds')

SOURCE_OVERRIDES = json.loads(audit.read_text(OVERRIDES,purpose='initialization_source_overrides'))['sources'] if OVERRIDES.exists() else {}

def normalize_source(s):
    correction=SOURCE_OVERRIDES.get(s['source_id'])
    return dict(s,publication_date=correction['publication_date'],date_correction=correction) if correction else s

def base_manifest():
    m=json.loads(audit.read_text(MANIFEST,purpose='manifest_read'))
    m['sources']=[normalize_source(s) for s in m['sources']]
    if EXPANSION.exists():
        extra=json.loads(audit.read_text(EXPANSION,purpose='company_expansion_manifest'))
        seen={s['source_id'] for s in m['sources']}
        additions=[normalize_source(s) for s in extra['sources'] if s['source_id'] not in seen]
        m['sources']+=additions
        m['stats']['downloaded_sources']+=len(additions)
        m['stats']['pdf_pages']+=sum(s.get('page_count',0) for s in additions)
        pdfs=[s for s in additions if str(s.get('relative_path','')).lower().endswith('.pdf')]
        m['stats']['pdf_count']+=len(pdfs)
        m['stats']['company_pdfs']+=sum(bool(s.get('stock_code')) for s in pdfs)
        m['stats']['financial_reports']+=sum(s.get('category')=='01_公司财报' for s in additions)
        for source in pdfs:
            if source.get('company') and source.get('stock_code'):
                company=source['company']
                m['stats']['by_company'][company]=m['stats']['by_company'].get(company,0)+1
        m['stats']['expanded_company_sources']=len(additions)
        m['research_cutoff']=max(m['research_cutoff'],extra['research_cutoff'])
    if MARKET_EXPANSION.exists():
        extra=json.loads(audit.read_text(MARKET_EXPANSION,purpose='market_expansion_manifest'))
        seen={s['source_id'] for s in m['sources']}
        additions=[s for s in extra['sources'] if s['source_id'] not in seen]
        m['sources']+=additions
        m['stats']['downloaded_sources']+=len(additions)
        m['stats']['market_rows']+=sum(s['row_count'] for s in additions)
        m['stats']['market_series']+=len(additions)
        m['stats']['expanded_market_sources']=len(additions)
    return m

def corpus_pages():
    paths=[DATASET/'05_可检索文本/逐页语料.jsonl']
    if EXPANSION.exists():
        extra=json.loads(audit.read_text(EXPANSION,purpose='company_expansion_corpus_registry'))
        path=(DATASET/extra['corpus_relative_path']).resolve()
        if not path.is_relative_to(DATASET.resolve()):raise ValueError('扩展语料路径无效')
        paths.append(path)
    for path in paths:
        for line in audit.read_text(path,purpose='registered_pdf_corpus').splitlines():
            if line.strip():yield json.loads(line)

def manifest():
    m=base_manifest()
    import knowledge
    additions=knowledge.sources()
    m['sources']+=additions
    m['stats']['supplemental_sources']=len(additions)
    m['stats']['total_sources']=m['stats']['downloaded_sources']+len(additions)
    m['research_cutoff']=max([m['research_cutoff']]+[s['publication_date'] for s in additions])
    return m

def imported_pages():
    import knowledge
    return knowledge.pages()

def file_for(record):
    if record.get('storage')=='user-library':
        file=(APP/record['relative_path']).resolve()
        if not file.is_relative_to(DATA.resolve()):raise ValueError('补充资料路径无效')
    else:
        file=(DATASET/record['relative_path']).resolve()
        if not file.is_relative_to(DATASET):raise ValueError('资料路径无效')
    return file

def tokens(text):
    """Chinese bigrams + Latin words; no online embeddings or tokenizer service."""
    parts = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+',text.lower())
    out = []
    for p in parts:
        if re.fullmatch(r'[\u4e00-\u9fff]+',p):
            out.extend(p[i:i+2] for i in range(len(p)-1))
        elif len(p)>1: out.append(p)
    return out

def split_text(text,size=1600,overlap=180):
    text = text.strip()
    start = 0
    while start<len(text):
        end = min(start+size,len(text))
        if end<len(text):
            boundary = text.rfind('\n',start+size//2,end)
            if boundary>start: end=boundary
        yield text[start:end]
        if end==len(text): break
        start = max(start+1,end-overlap)

def build_index():
    DATA.mkdir(exist_ok=True)
    staging = DATA/'index.build.sqlite3'
    if staging.exists(): staging.unlink()
    db = sqlite3.connect(staging)
    db.executescript('''
        CREATE TABLE sources(source_id TEXT PRIMARY KEY, metadata TEXT NOT NULL);
        CREATE TABLE chunks(id INTEGER PRIMARY KEY,source_id TEXT,stock_code TEXT,publication_date TEXT,
          report_period TEXT,kind TEXT,locator TEXT,pdf_page INTEGER,text TEXT,ocr INTEGER);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(tokens);
        CREATE INDEX date_company ON chunks(stock_code,publication_date);
        CREATE INDEX by_source ON chunks(source_id,pdf_page);
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
    ''')
    m = base_manifest()
    sources = {r['source_id']:r for r in m['sources']}
    db.executemany('INSERT INTO sources VALUES (?,?)',[(k,json_dump(v)) for k,v in sources.items()])
    counter = 0
    def add(source_id,text,locator,pdf_page=None,ocr=False):
        nonlocal counter
        source = sources[source_id]
        if len(re.sub(r'\s+','',text))<25: return
        kind = 'financial' if source.get('report_period') else 'market' if source['category']=='06_市场行情' else 'industry' if source['category']=='04_行业数据与政策' else 'announcement'
        for part in split_text(text):
            counter += 1
            db.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (counter,source_id,source.get('stock_code'),source['publication_date'],source.get('report_period'),kind,locator,pdf_page,part,int(ocr)))
            db.execute('INSERT INTO chunks_fts(rowid,tokens) VALUES (?,?)',(counter,' '.join(tokens(part))))
    for p in corpus_pages():
        add(p['source_id'],p['text'],f"PDF第{p['pdf_page']}页",p['pdf_page'],'OCR' in p.get('text_origin',''))
    web = collections.defaultdict(list)
    for line in audit.read_text(DATASET/'05_可检索文本/网页语料.jsonl',purpose='index_web_text_corpus').splitlines():
        p = json.loads(line);web[p['source_id']].append(p)
    for source_id,paragraphs in web.items():
        buffer,first,last = [],None,None
        for p in paragraphs:
            if first is None: first=p['paragraph_number']
            last=p['paragraph_number'];buffer.append(p['text'])
            if len('\n'.join(buffer))>=1200:
                add(source_id,'\n'.join(buffer),f'网页段落{first}—{last}')
                buffer=[];first=None
        if buffer: add(source_id,'\n'.join(buffer),f'网页段落{first}—{last}')
    for source in sources.values():
        if source['category']!='06_市场行情': continue
        rows = json.loads(audit.read_text(DATASET/source['relative_path'],source_id=source['source_id'],purpose='index_market_source'))['data']
        tail = rows[-1]
        add(source['source_id'],f"{source['company']}A股未复权日线。末个交易日{tail['day']}，开盘{tail['open']}元，最高{tail['high']}元，最低{tail['low']}元，收盘{tail['close']}元。共{len(rows)}条历史记录，起始日期{rows[0]['day']}。成交量原始单位待核验；不代表含分红的总收益。",'日线记录')
    db.executemany('INSERT INTO meta VALUES (?,?)',[
        ('built_at',now()),('chunk_count',str(counter)),('source_count',str(len(sources))),
        ('dataset_sha256',hashlib.sha256(audit.read_bytes(MANIFEST,purpose='index_manifest_hash')).hexdigest()),('cutoff',m['research_cutoff'])])
    db.execute('INSERT INTO meta VALUES (?,?)',('source_overrides_sha256',hashlib.sha256(audit.read_bytes(OVERRIDES,purpose='index_source_overrides_hash')).hexdigest() if OVERRIDES.exists() else ''))
    db.execute('INSERT INTO meta VALUES (?,?)',('company_expansion_sha256',hashlib.sha256(audit.read_bytes(EXPANSION,purpose='index_expansion_hash')).hexdigest() if EXPANSION.exists() else ''))
    db.execute('INSERT INTO meta VALUES (?,?)',('market_expansion_sha256',hashlib.sha256(audit.read_bytes(MARKET_EXPANSION,purpose='index_market_expansion_hash')).hexdigest() if MARKET_EXPANSION.exists() else ''))
    db.commit();db.close()
    staging.replace(INDEX)
    print(f'Indexed {len(sources)} sources, {counter} chunks',flush=True)
    return counter

def connect():
    db = sqlite3.connect(INDEX,factory=ClosingConnection)
    db.row_factory=sqlite3.Row
    return db

def ensure_index():
    if not INDEX.exists():return build_index()
    audit.cache_hit('sqlite_fts_index')
    with connect() as db:
        row=db.execute("SELECT value FROM meta WHERE key='source_overrides_sha256'").fetchone()
    expected=hashlib.sha256(audit.read_bytes(OVERRIDES,purpose='index_version_check')).hexdigest() if OVERRIDES.exists() else ''
    if not row or row[0]!=expected:return build_index()
    with connect() as db:
        expansion=db.execute("SELECT value FROM meta WHERE key='company_expansion_sha256'").fetchone()
    expected_expansion=hashlib.sha256(audit.read_bytes(EXPANSION,purpose='index_expansion_version_check')).hexdigest() if EXPANSION.exists() else ''
    if (not expansion and expected_expansion) or (expansion and expansion[0]!=expected_expansion):return build_index()
    with connect() as db:
        market=db.execute("SELECT value FROM meta WHERE key='market_expansion_sha256'").fetchone()
    expected_market=hashlib.sha256(audit.read_bytes(MARKET_EXPANSION,purpose='index_market_version_check')).hexdigest() if MARKET_EXPANSION.exists() else ''
    if (not market and expected_market) or (market and market[0]!=expected_market):return build_index()

def validate_cutoff(cutoff):
    try: dt.date.fromisoformat(cutoff)
    except (ValueError,TypeError): raise ValueError('研究日期格式应为 YYYY-MM-DD')
    today=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    if not '2021-01-01'<=cutoff<=max(manifest()['research_cutoff'],today):
        raise ValueError('研究日期应在2021年1月1日至今天之间')
    return cutoff

def source(source_id):
    with connect() as db:
        r=db.execute('SELECT metadata FROM sources WHERE source_id=?',(source_id,)).fetchone()
    if not r:
        import knowledge
        custom=knowledge.source(source_id)
        if custom:return custom
        raise KeyError('资料不存在')
    return normalize_source(json.loads(r[0]))

def decorate(row):
    r=dict(row);s=source(r['source_id'])
    r.update(title=s['title'],company=s.get('company'),publisher=s['publisher'],source_url=s['url'],
             file_url='/api/files/'+r['source_id']+(f"#page={r['pdf_page']}" if r.get('pdf_page') else ''),
             report_period=s.get('report_period'),revision_flag=s.get('revision_flag',False),date_conflict=s.get('date_conflict',False),date_correction=s.get('date_correction'))
    return r

def search(query,code='',cutoff='2026-10-06',limit=12,kind='',period='',include_industry=True):
    validate_cutoff(cutoff)
    if code and code not in COMPANIES: raise ValueError('请选择资料包中的公司')
    query=query.strip()[:500]
    if not query: return []
    import financial_notes
    expanded=financial_notes.expand(query)
    priority=financial_notes.search_priority(query)
    for alias,full in ALIASES.items():
        if alias in query and full not in expanded: expanded+=' '+full
    requested_terms=[w for w in TOPICS if w in expanded]
    term_tokens=list(dict.fromkeys(tokens(expanded)))[:45]
    if not term_tokens: return []
    match=' OR '.join('"'+t.replace('"','')+'"' for t in term_tokens)
    filters=['c.publication_date<=?'];args=[cutoff]
    if code:
        filters.append('(c.stock_code=? OR c.stock_code IS NULL)' if include_industry else 'c.stock_code=?');args.append(code)
    if kind: filters.append('c.kind=?');args.append(kind)
    if period: filters.append('c.report_period=?');args.append(period)
    sql='''SELECT c.*,bm25(chunks_fts) AS rank FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid
        WHERE chunks_fts MATCH ? AND '''+' AND '.join(filters)+' ORDER BY rank LIMIT 180'
    with connect() as db: rows=[dict(r) for r in db.execute(sql,[match]+args)]
    year=re.search(r'20\d{2}',query)
    for r in rows:
        hits=sum(min(r['text'].count(w),3)*3 for w in requested_terms)
        hits+=20*len(set(term_tokens)&set(tokens(r['text'])))/max(len(term_tokens),1)
        if query in r['text']:hits+=12
        if (r['source_id'],r['pdf_page']) in priority:hits+=18
        if year and year.group() in (r['report_period'] or ''): hits+=3
        if any(w in query for w in ['上半年','半年']) and (r['report_period'] or '').endswith('H1'): hits+=3
        if any(w in r['text'][:250] for w in ['主要会计政策','分类和计量','遵循企业会计准则']) and not any(w in query for w in ['会计政策','准则','计量']): hits-=10
        r['score']=round(hits+min(-float(r['rank'])*2,10)+(1 if r['publication_date'][:4]=='2026' else 0),3)
    rows.sort(key=lambda r:(-r['score'],r['rank']))
    import knowledge
    custom=knowledge.search(expanded,code,cutoff,max(1,min(int(limit),30)),kind,period,include_industry)
    if custom:
        rows+=custom;rows.sort(key=lambda r:-r['score'])
    result=[];locations=set()
    for r in rows:
        key=(r['source_id'],r['locator'])
        if key in locations: continue
        locations.add(key);result.append(r if r.get('user_imported') else decorate(r))
        if len(result)>=max(1,min(int(limit),30)): break
    audit.event('index_query',purpose='keyword_search',cache_name='sqlite_fts_index',cache_hit=True,count=len(result),status='success')
    return result

def page_evidence(source_id,page):
    with connect() as db:
        rows=db.execute('SELECT * FROM chunks WHERE source_id=? AND pdf_page=? ORDER BY id',(source_id,page)).fetchall()
    if not rows:
        import knowledge
        custom=knowledge.passage(source_id,page)
        audit.event('index_query',purpose='supplemental_page_text',source_id=source_id,page=page,cache_name='knowledge_sqlite_passages',cache_hit=True,status='success',count=len(custom))
        return custom[0] if custom else None
    r=dict(rows[0]);text=r['text']
    for part in rows[1:]:
        overlap=next((n for n in range(min(300,len(text),len(part['text'])),30,-1) if text[-n:]==part['text'][:n]),0)
        text+=part['text'][overlap:]
    r['text']=text[:12000]
    audit.event('index_query',purpose='physical_page_text',source_id=source_id,page=page,cache_name='sqlite_fts_index',cache_hit=True,status='success',bytes=len(r['text'].encode()))
    return decorate(r)

def source_evidence(source_id,contains='',limit=1):
    """Pinned authoritative releases, useful when a known monthly release is required."""
    with connect() as db:
        rows=db.execute('SELECT * FROM chunks WHERE source_id=? ORDER BY id',(source_id,)).fetchall()
    if not rows:
        import knowledge
        rows=knowledge.passage(source_id)
        result=[r for r in rows if not contains or contains in r['text']][:limit]
        audit.event('index_query',purpose='supplemental_source_text',source_id=source_id,cache_name='knowledge_sqlite_passages',cache_hit=True,status='success',count=len(result))
        return result
    if contains:
        matches=[r for r in rows if contains in r['text']]
        if matches: rows=matches
    result=[decorate(r) for r in rows[:limit]]
    audit.event('index_query',purpose='source_text',source_id=source_id,cache_name='sqlite_fts_index',cache_hit=True,status='success',count=len(result))
    return result

def curated_metric_rows(period='2026-H1',cutoff='2026-10-06'):
    validate_cutoff(cutoff)
    definitions=json.loads(audit.read_text(APP/'metrics.json',purpose='curated_metrics'))['metrics']
    output=[]
    for m in definitions:
        if m['period']!=period: continue
        s=source(m['source_id'])
        if s['publication_date']>cutoff: continue
        r=dict(m);factor=Decimal(m['factor_to_yuan'])
        r.update(company=COMPANIES[m['code']],publication_date=s['publication_date'],source_title=s['title'],
                 file_url=f"/api/files/{m['source_id']}#page={m['page']}",
                 calculation_basis='合并口径；人民币亿元；同比基期以本报告列示数据为准',calculations={})
        for key in ['revenue','profit','core_profit','cashflow']:
            current=Decimal(m[key]);prior=Decimal(m[key+'_prior'])
            yi=current*factor/Decimal('100000000')
            growth=(current-prior)/prior*100 if prior else None
            computed=growth.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP) if growth is not None else None
            reported=Decimal(m[key+'_growth'])
            if computed is not None and abs(computed-reported)>Decimal('0.02'):
                raise ValueError(f"{m['code']} {period} {key} 同比校验失败")
            r[key+'_yi']=format(yi.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP),'f')
            r['calculations'][key]={'original_value':m[key],'prior_value':m[key+'_prior'],'original_unit':m['unit'],
                  'to_yi_formula':f"{m[key]} × {m['factor_to_yuan']} ÷ 100000000",'amount_yi':r[key+'_yi'],
                  'yoy_formula':f"({m[key]} - {m[key+'_prior']}) ÷ {m[key+'_prior']} × 100",'computed_yoy':str(computed),
                  'reported_yoy':m[key+'_growth'],'source_id':m['source_id'],'pdf_page':m['page']}
        r['cash_profit_ratio']=format((Decimal(m['cashflow'])/Decimal(m['profit'])).quantize(Decimal('0.01')),'f')
        output.append(r)
    return output

def metric_rows(period='2026-H1',cutoff='2026-10-06'):
    import financials
    return financials.metrics(period,cutoff)

def available_period(code,cutoff):
    import financials
    return financials.latest_period(code,cutoff)

def list_sources(query='',code='',category='',cutoff='2026-10-06'):
    validate_cutoff(cutoff)
    m=manifest()
    return [dict(r,file_url='/api/files/'+r['source_id']) for r in m['sources']
            if r['publication_date']<=cutoff and (not code or r.get('stock_code')==code)
            and (not category or r['category']==category) and (not query or query.lower() in (r['title']+' '+r.get('company','') if r.get('company') else r['title']).lower())]

def prices(code,cutoff='2026-10-06'):
    validate_cutoff(cutoff)
    s=next((r for r in manifest()['sources'] if r['category']=='06_市场行情' and r.get('stock_code')==code),None)
    if not s: return {'data':[]}
    package=json.loads(audit.read_text(DATASET/s['relative_path'],source_id=s['source_id'],purpose='market_source_read'))
    package['data']=[r for r in package['data'] if r['day'][:10]<=cutoff]
    package['metadata']=dict(s)
    if package['data']:
        package['metadata']['last_trading_date']=package['data'][-1]['day'][:10]
    return package

def run_db():
    db=sqlite3.connect(RUNS,factory=ClosingConnection);db.row_factory=sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,created_at TEXT,code TEXT,question TEXT,mode TEXT,result TEXT)')
    return db

def save_run(result):
    with run_db() as db:
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?)',(result['id'],result['created_at'],result['code'],result['question'],result['mode'],json_dump(result)))

def get_run(run_id):
    with run_db() as db: r=db.execute('SELECT result FROM runs WHERE id=?',(run_id,)).fetchone()
    if not r: raise KeyError('运行记录不存在')
    return json.loads(r[0])

def list_runs():
    with run_db() as db:
        return [dict(r) for r in db.execute("SELECT id,created_at,code,question,mode,json_extract(result,'$.mode_label') mode_label FROM runs ORDER BY created_at DESC LIMIT 50")]

if __name__=='__main__': build_index()
