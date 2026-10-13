"""Saved assumptions, human claim checks and dated monitoring rules."""
import json
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
import core
import financials
import valuation
import decision

DB=core.DATA/'workbench.sqlite3'
METRICS={'revenue_growth':'营收同比','profit_growth':'归母利润同比','core_profit_growth':'扣非利润同比',
         'cashflow_growth':'经营现金流同比','cash_profit_ratio':'经营现金流/归母利润','price':'A股参考收盘价'}

def connect():
    db=sqlite3.connect(DB,factory=core.ClosingConnection);db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS valuations(id TEXT PRIMARY KEY,created_at TEXT,result TEXT);
        CREATE TABLE IF NOT EXISTS notes(run_id TEXT,claim_id TEXT,state TEXT,note TEXT,updated_at TEXT,PRIMARY KEY(run_id,claim_id));
        CREATE TABLE IF NOT EXISTS watches(id TEXT PRIMARY KEY,created_at TEXT,spec TEXT,enabled INTEGER DEFAULT 1);''')
    return db

def save_valuation(body):
    result=valuation.calculate(body);result['id']=uuid.uuid4().hex[:12];result['created_at']=core.now()
    with connect() as db:db.execute('INSERT INTO valuations VALUES (?,?,?)',(result['id'],result['created_at'],core.json_dump(result)))
    return result

def get_valuation(value_id):
    with connect() as db:r=db.execute('SELECT result FROM valuations WHERE id=?',(value_id,)).fetchone()
    if not r:raise ValueError('估值情景不存在')
    return json.loads(r['result'])

def claims(run):
    output=[]
    for section in ['thesis','risks','invalidation','monitoring','open_questions']:
        for i,row in enumerate(run['draft'].get(section,[])):
            output.append(dict(row,claim_id=f'{section}:{i}',section=section))
    return output

def notes(run_id):
    with connect() as db:return [dict(r) for r in db.execute('SELECT * FROM notes WHERE run_id=?',(run_id,))]

def annotate(run_id,body):
    run=core.get_run(run_id);allowed={r['claim_id'] for r in claims(run)}
    claim_id=body.get('claim_id');state=body.get('state','pending')
    if claim_id not in allowed or state not in ['pending','confirmed','refuted']:raise ValueError('请选择有效论据和核验状态')
    note=str(body.get('note','')).strip()[:1500]
    if state in ['confirmed','refuted'] and len(note)<3:raise ValueError('请记录核对依据或反证，不能只有状态')
    with connect() as db:db.execute('INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?)',(run_id,claim_id,state,note,core.now()))
    return quality(run)

def quality(run):
    rows=claims(run);evidence=run['evidence'];refs={e['citation'] for e in evidence}
    complete=sum(bool(run['draft'].get(k)) for k in ['thesis','risks','invalidation','monitoring','open_questions'])
    cited=sum(bool(r.get('citations')) and all(c in refs for c in r['citations']) for r in rows)
    date_pass=all(e['publication_date']<=run['cutoff'] for e in evidence)
    metrics=run.get('metrics',[]);financial=bool(metrics) and all(len(m.get('calculations',{}))==4 for m in metrics)
    review=run['review']
    model_issues=review['model_review'].get('issues',[]) if isinstance(review.get('model_review'),dict) else [i for i in review.get('issues',[]) if i.get('source')!='deterministic']
    checks=decision.comparison_checks(run)
    issues=model_issues+checks;high=sum(i.get('severity')=='高' for i in issues)
    dimensions=[{'name':'章节完整度','score':complete*4,'maximum':20,'detail':f'{complete}/5个章节'},
                {'name':'引用编号覆盖','score':round(cited/max(len(rows),1)*30),'maximum':30,'detail':f'{cited}/{len(rows)}条目有有效编号；未证明语义支持关系'},
                {'name':'披露时点检查','score':20 if date_pass else 0,'maximum':20,'detail':'所有已选证据披露日期不晚于研究时点' if date_pass else '存在越过时点的证据'},
                {'name':'财务计算可回看','score':20 if financial else 0,'maximum':20,'detail':'四项指标有原值和公式' if financial else '缺少完整财务计算'},
                {'name':'复核过程留存','score':10 if run.get('review') and run.get('mode')!='development_revision' else 0,'maximum':10,'detail':('开发侧逻辑修订，尚未新作模型复核；' if run.get('mode')=='development_revision' else f'{len(model_issues)}项模型复核、')+f'{len(checks)}项口径/推论规则问题'}]
    annotations=notes(run['id'])
    return {'run_id':run['id'],'score':sum(d['score'] for d in dimensions),'dimensions':dimensions,'claims':rows,'notes':annotations,
            'high_issues':high,'review_issues':issues,'comparison_checks':checks,'confirmed':sum(n['state']=='confirmed' for n in annotations),
            'refuted':sum(n['state']=='refuted' for n in annotations),
            'label':'结构与可追溯性检查分；不代表事实正确率或投资价值','scope':'引用的语义充分性、表头归属和因果仍需人工核对。'}

def create_watch(body):
    code=body.get('code');metric=body.get('metric');operator=body.get('operator','lt')
    if code not in core.COMPANIES or metric not in METRICS or operator not in ['lt','le','gt','ge']:raise ValueError('请选择有效的公司、指标和比较条件')
    try:threshold=Decimal(str(body.get('threshold')))
    except (InvalidOperation,TypeError):raise ValueError('阈值需要数字') from None
    if not threshold.is_finite() or abs(threshold)>100000:raise ValueError('阈值超出范围')
    run_id=body.get('run_id','')
    if run_id and core.get_run(run_id)['code']!=code:raise ValueError('跟踪公司与研究记录不一致')
    spec={'id':uuid.uuid4().hex[:12],'code':code,'company':core.COMPANIES[code],'metric':metric,'operator':operator,
          'threshold':str(threshold),'title':str(body.get('title',METRICS[metric]+'跟踪'))[:150],'run_id':run_id,
          'hypothesis':str(body.get('hypothesis','阈值触发后重新核验相关论据'))[:800]}
    with connect() as db:db.execute('INSERT INTO watches VALUES (?,?,?,1)',(spec['id'],core.now(),core.json_dump(spec)))
    return spec

def set_watch_enabled(watch_id,enabled):
    if not isinstance(enabled,bool):raise ValueError('启用状态需要布尔值')
    with connect() as db:
        cur=db.execute('UPDATE watches SET enabled=? WHERE id=?',(int(enabled),watch_id))
        if not cur.rowcount:raise ValueError('跟踪规则不存在')
    return {'id':watch_id,'enabled':enabled}

def watchlist(cutoff):
    core.validate_cutoff(cutoff)
    with connect() as db:rows=db.execute('SELECT * FROM watches ORDER BY created_at DESC').fetchall()
    output=[]
    for r in rows:
        spec=json.loads(r['spec']);code=spec['code'];metric=spec['metric'];value=None;source_id=None;page=None;period=None;date=None
        if metric=='price':
            prices=core.prices(code,cutoff)
            if prices['data']:
                last=prices['data'][-1];value=last['close'];date=last['day'][:10];source_id=prices['metadata']['source_id']
        else:
            period=financials.latest_period(code,cutoff)
            m=next((m for m in financials.metrics(period,cutoff) if m['code']==code),None) if period else None
            if m:
                value=m.get(metric);source_id=m['source_id'];date=m['publication_date']
                field='cashflow' if metric=='cash_profit_ratio' else metric.removesuffix('_growth')
                page=m['calculations'].get(field,{}).get('pdf_page',m['page'])
        triggered=None
        if value is not None:
            a=Decimal(str(value));b=Decimal(spec['threshold'])
            triggered={'lt':a<b,'le':a<=b,'gt':a>b,'ge':a>=b}[spec['operator']]
        output.append(dict(spec,enabled=bool(r['enabled']),current_value=str(value) if value is not None else None,
                           triggered=triggered if r['enabled'] else None,period=period,publication_date=date,source_id=source_id,page=page,
                           metric_name=METRICS[metric],file_url='/api/files/'+source_id+(f'#page={page}' if page else '') if source_id else None))
    return {'data':output,'cutoff':cutoff,'triggered_count':sum(r['triggered'] is True for r in output),
            'note':'按本机已有、研究时点之前披露的最新数据计算；阈值是用户假设，触发意味着需要复核，不是交易信号。未触发也不证明论据正确。'}
