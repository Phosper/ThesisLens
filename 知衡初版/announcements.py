"""Bounded official announcement discovery, persisted provenance and explicit selected import."""
import datetime as dt
import gzip
import hashlib
import html
import json
import re
import sqlite3
import urllib.parse
import urllib.request
import uuid

import core
import knowledge
import companies as company_registry

DB=core.DATA/'announcements.sqlite3'
TZ=dt.timezone(dt.timedelta(hours=8))
CNINFO='https://www.cninfo.com.cn/new/hisAnnouncement/query'
SSE='https://query.sse.com.cn/security/stock/queryCompanyBulletin.do'
ORGS={r['code']:r['org_id'] for r in company_registry.DEFAULTS}
MAX_PAGES=5;PAGE_SIZE=30

def connect():
    db=sqlite3.connect(DB,factory=core.ClosingConnection);db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS checks(id TEXT PRIMARY KEY,created_at TEXT,result TEXT);
        CREATE TABLE IF NOT EXISTS candidates(id TEXT PRIMARY KEY,metadata TEXT,first_seen TEXT,last_seen TEXT,imported_source TEXT);''')
    return db

def today():return dt.datetime.now(TZ).date().isoformat()

def request_json(url,data=None):
    knowledge.allowed_url(url)
    req=urllib.request.Request(url,data=data,headers={'User-Agent':'Mozilla/5.0 ThesisLens/0.3 PublicResearch',
        'Referer':'https://www.sse.com.cn/' if 'sse.com.cn' in url else 'https://www.cninfo.com.cn/',
        'Content-Type':'application/x-www-form-urlencoded'})
    try:
        with urllib.request.build_opener(knowledge.SafeRedirect()).open(req,timeout=35) as fp:raw=fp.read(4*1024*1024+1)
        if len(raw)>4*1024*1024:raise ValueError('官方公告响应超过读取上限')
        if raw.startswith(b'\x1f\x8b'):raw=gzip.decompress(raw)
        if len(raw)>8*1024*1024:raise ValueError('官方公告解压结果超过读取上限')
        result=json.loads(raw)
        if not isinstance(result,dict):raise ValueError('官方公告响应格式变化，请通过官方网站复核')
        return result
    except (OSError,UnicodeError,json.JSONDecodeError):raise ValueError('官方公告接口暂时不可用，请稍后重试或从发布方手动导入') from None

def report_period(title):
    if any(t in title for t in ['摘要','英文','审计','评价','评估','董事','监事','履职','实施','持续','H股','D股']):return ''
    # Report announcements/earnings meetings may mention a report in their title.
    match=re.search(r'(20\d{2})年(半年度报告|第一季度报告|一季度报告|第三季度报告|三季度报告|年度报告)(?:全文)?(?:[（(](?:修订|修订版|更正|更正版|更新|更新后|修订后)[）)])?$',re.sub(r'\s','',title))
    if not match:return ''
    return match.group(1)+'-'+{'半年度报告':'H1','第一季度报告':'Q1','一季度报告':'Q1','第三季度报告':'Q3','三季度报告':'Q3','年度报告':'FY'}[match.group(2)]

def normalize(code,row,provider):
    if provider=='cninfo':
        if row.get('secCode')!=code:return None
        aid=str(row.get('announcementId',''));title=row.get('announcementTitle','')
        timestamp=row.get('announcementTime')
        if not aid or not isinstance(timestamp,(int,float)):return None
        date=dt.datetime.fromtimestamp(timestamp/1000,TZ).date().isoformat()
        adjunct=str(row.get('adjunctUrl',''))
        if not re.fullmatch(r'finalpage/\d{4}-\d{2}-\d{2}/[\w.-]+\.pdf',adjunct,re.I):return None
        url='https://static.cninfo.com.cn/'+adjunct;publisher='巨潮资讯'
        detail='https://www.cninfo.com.cn/new/disclosure/detail?'+urllib.parse.urlencode({'plate':'sse' if code.startswith('6') else 'szse','orgId':ORGS[code],
            'stockCode':code,'announcementId':aid,'announcementTime':date})
    else:
        if row.get('SECURITY_CODE')!=code:return None
        title=row.get('TITLE','');date=str(row.get('SSEDATE',''))[:10];adjunct=str(row.get('URL',''))
        if not re.fullmatch(r'/disclosure/listedinfo/announcement/[^?#]+\.pdf',adjunct,re.I):return None
        url='https://static.sse.com.cn'+adjunct;aid=adjunct.rsplit('/',1)[-1];publisher='上海证券交易所';detail=url
    title=html.unescape(re.sub(r'<[^>]*>','',str(title))).strip()[:200]
    if not title:return None
    try:dt.date.fromisoformat(date)
    except ValueError:return None
    sid=provider+'_'+hashlib.sha256((code+'|'+aid).encode()).hexdigest()[:20]
    file_date=re.search(r'/((?:20)\d{2}-\d{2}-\d{2})/',url)
    period=report_period(title)
    if period:
        import financials
        if financials.period_end(period)>date:period=''
    return {'id':sid,'announcement_id':aid,'provider':provider,'code':code,'company':core.COMPANIES[code],
        'title':title,'publication_date':date,'period':period,'url':url,'detail_url':detail,'publisher':publisher,
        'date_conflict':bool(file_date and file_date.group(1)!=date),'metadata_method':'官方公告列表登记的公司、标题和披露日期，正文仍需核验'}

def fetch_page(code,start,end,keyword,page):
    if code not in ORGS:raise ValueError('本企业尚未配置官方证券机构标识，请从发布方原件手动导入')
    if not code.startswith('6'):
        params={'pageNum':page,'pageSize':PAGE_SIZE,'column':'szse','tabName':'fulltext','stock':code+','+ORGS[code],
            'searchkey':keyword,'seDate':start+'~'+end,'sortName':'time','sortType':'desc','isHLtitle':'false'}
        result=request_json(CNINFO,urllib.parse.urlencode(params).encode())
        if 'announcements' not in result or 'totalAnnouncement' not in result:raise ValueError('巨潮公告查询返回结构变化，未把它当成零条公告')
        rows=result.get('announcements') or [];total=int(result['totalAnnouncement']);more=bool(result.get('hasMore'))
        provider='cninfo';endpoint=CNINFO
    else:
        params={'isPagination':'true','productId':code,'keyWord':keyword,'securityType':'0101,120100,020100,020200,120200',
            'pageHelp.pageSize':PAGE_SIZE,'beginDate':start,'endDate':end,'pageHelp.pageNo':page}
        endpoint=SSE+'?'+urllib.parse.urlencode(params);result=request_json(endpoint)
        if 'result' not in result or not isinstance(result.get('pageHelp'),dict):raise ValueError('上交所公告查询返回结构变化，未把它当成零条公告')
        rows=result.get('result') or [];total=int(result['pageHelp'].get('total',0));more=page*PAGE_SIZE<total
        provider='sse'
    if not isinstance(rows,list):raise ValueError('公告列表格式无效')
    return rows,total,more,provider,{'endpoint':endpoint,'parameters':params,'response_sha256':hashlib.sha256(core.json_dump(result).encode()).hexdigest()}

def verified_mirror(candidate):
    """Read an independently published official copy; never solve/bypass a site's challenge."""
    code=candidate['code'];date=candidate['publication_date']
    params={'pageNum':1,'pageSize':PAGE_SIZE,'column':'sse' if code.startswith('6') else 'szse','tabName':'fulltext',
        'stock':code+','+ORGS[code],'searchkey':title_key(candidate['title'],code)[:80],
        'seDate':date+'~'+date,'sortName':'time','sortType':'desc','isHLtitle':'false'}
    result=request_json(CNINFO,urllib.parse.urlencode(params).encode());matches=[]
    for row in result.get('announcements') or []:
        normalized=normalize(code,row,'cninfo')
        if normalized and normalized['publication_date']==date and title_key(normalized['title'],code)==title_key(candidate['title'],code):matches.append(normalized)
    if len(matches)!=1:raise ValueError('上交所原件暂不可读取，巨潮资讯未找到唯一同日同名公告。请回看发布方并手动下载后上传。')
    match=matches[0]
    return match,{'provider':'cninfo','announcement_id':match['announcement_id'],'url':match['url'],'publication_date':date,
        'title':match['title'],'query_endpoint':CNINFO,'parameters':params,'response_sha256':hashlib.sha256(core.json_dump(result).encode()).hexdigest()}

def title_key(title,code):
    t=re.sub(r'[\s:：\-—_（）()]','',title)
    for prefix in [core.COMPANIES[code]+'股份有限公司',core.COMPANIES[code], '广东'+core.COMPANIES[code]+'股份有限公司']:
        if t.startswith(prefix):t=t[len(prefix):];break
    return t

def decorate(candidate,known=None):
    known=known if known is not None else core.base_manifest()['sources']+knowledge.sources(True)
    exact=next((s for s in known if s.get('url')==candidate['url'] or
        (s.get('stock_code')==candidate['code'] and s['publication_date']==candidate['publication_date'] and
         title_key(s['title'],candidate['code'])==title_key(candidate['title'],candidate['code']))),None)
    imported=candidate.get('imported_source')
    if not exact and imported:exact=next((s for s in known if s['source_id']==imported),None)
    return dict(candidate,status='paused' if exact and exact.get('enabled') is False else 'available' if exact else 'new',
        existing_source=exact['source_id'] if exact else None,download_url=exact.get('url') if exact and exact.get('official_metadata') else candidate['url'])

def list_candidates(code='',start='',end='',keyword=''):
    if code and code not in core.COMPANIES:raise ValueError('请选择公司')
    with connect() as db:
        rows=db.execute('SELECT * FROM candidates ORDER BY last_seen DESC').fetchall()
        checks=db.execute('SELECT result FROM checks ORDER BY created_at DESC LIMIT 8').fetchall()
    known=core.base_manifest()['sources']+knowledge.sources(True);output=[]
    for r in rows:
        c=dict(json.loads(r['metadata']),imported_source=r['imported_source'],last_seen=r['last_seen'])
        if code and c['code']!=code or start and c['publication_date']<start or end and c['publication_date']>end:continue
        if keyword and keyword not in c['title']:continue
        output.append(decorate(c,known))
    output.sort(key=lambda c:(c['publication_date'],c['id']),reverse=True)
    return {'data':output[:500],'checks':[json.loads(r[0]) for r in checks],'today':today()}

def discover(body,on_step=None):
    start=str(body.get('start',''));end=str(body.get('end',today()));code=str(body.get('code',''));keyword=str(body.get('keyword','')).strip()
    try:a=dt.date.fromisoformat(start);b=dt.date.fromisoformat(end)
    except ValueError:raise ValueError('请选择有效的公告查询日期') from None
    if a>b or b>dt.date.fromisoformat(today()) or (b-a).days>366 or a<dt.date(2021,1,1):raise ValueError('查询限2021年起、最长366天，结束日期不能晚于今天')
    if code and code not in core.COMPANIES:raise ValueError('请选择公司')
    if len(keyword)>80:raise ValueError('公告关键词最多80字')
    if code and code not in ORGS:raise ValueError('本企业未配置官方公告查询，请按资料研究导入原件')
    companies=[code] if code else list(ORGS);trace=[];queries=[];found={};summaries=[]
    for c in companies:
        count=0;total=0;complete=False;error=None;seen=set()
        try:
            for page in range(1,MAX_PAGES+1):
                trace.append({'step':len(trace)+1,'title':'检查官方公告','detail':f'{core.COMPANIES[c]} · 第{page}页'})
                if on_step:on_step(list(trace))
                rows,total,more,provider,record=fetch_page(c,start,end,keyword,page);queries.append(dict(record,code=c,page=page))
                fresh=0
                for row in rows:
                    candidate=normalize(c,row,provider)
                    if not candidate or not start<=candidate['publication_date']<=end:continue
                    if candidate['id'] in seen:continue
                    seen.add(candidate['id']);fresh+=1;count+=1
                    candidate['discovered_at']=core.now();candidate['query_endpoint']=CNINFO if provider=='cninfo' else SSE
                    found[candidate['id']]=candidate
                if not more:complete=True;break
                if not fresh:error='接口分页没有返回新的有效公告，结果可能不完整';break
        except (ValueError,OverflowError,TypeError) as exc:error=str(exc)
        summaries.append({'code':c,'company':core.COMPANIES[c],'official_total':total,'valid_count':count,'complete':complete,
            'error':error,'note':'查询完整' if complete else error or f'达到每家公司{MAX_PAGES}页上限，请缩小日期或关键词继续检查'})
    stamp=core.now();result={'id':uuid.uuid4().hex[:12],'created_at':stamp,'start':start,'end':end,'code':code,'keyword':keyword,
        'count':len(found),'companies':summaries,'queries':queries,'candidate_ids':list(found),'complete':all(s['complete'] for s in summaries),'trace':trace}
    with connect() as db:
        for cid,candidate in found.items():
            db.execute('INSERT INTO candidates(id,metadata,first_seen,last_seen) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata,last_seen=excluded.last_seen',
                (cid,core.json_dump(candidate),stamp,stamp))
        db.execute('INSERT INTO checks VALUES (?,?,?)',(result['id'],stamp,core.json_dump(result)))
    result['data']=[decorate(c) for c in found.values()]
    return result

def import_selected(body,on_step=None):
    ids=body.get('ids')
    if not isinstance(ids,list) or not 1<=len(ids)<=5 or any(not isinstance(i,str) for i in ids):raise ValueError('每次请选择1至5份公告导入')
    output=[];trace=[]
    for cid in dict.fromkeys(ids):
        with connect() as db:r=db.execute('SELECT metadata,imported_source FROM candidates WHERE id=?',(cid,)).fetchone()
        if not r:raise ValueError('公告候选不存在，请先检查官方公告')
        candidate=decorate(dict(json.loads(r['metadata']),imported_source=r['imported_source']))
        trace.append({'step':len(trace)+1,'title':'导入官方公告','detail':candidate['title']})
        if on_step:on_step(list(trace))
        try:
            if candidate['status']=='available':
                result={'source_id':candidate['existing_source'],'duplicate':True}
            elif candidate['status']=='paused':
                result=knowledge.set_enabled(candidate['existing_source'],True)
            else:
                document={'title':candidate['title'],'publication_date':candidate['publication_date'],
                    'code':candidate['code'],'period':candidate['period'],'publisher':candidate['publisher'],'url':candidate['url']}
                metadata={'announcement_id':candidate['announcement_id'],'discovery_id':cid,'provider':candidate['provider'],
                    'query_endpoint':candidate['query_endpoint'],'detail_url':candidate['detail_url'],'discovered_at':candidate['discovered_at'],
                    'date_conflict':candidate['date_conflict'],'original_url':candidate['url']}
                try:result=knowledge.import_document(document,verified_metadata=metadata)
                except ValueError as exc:
                    if candidate['provider']!='sse' or not any(t in str(exc) for t in ['来源没有返回PDF原件','公开网址暂时无法读取']):raise
                    trace.append({'step':len(trace)+1,'title':'交叉核对另一官方原件','detail':'上交所原件未返回有效PDF，核对巨潮资讯同公司、同日、同名公告'})
                    if on_step:on_step(list(trace))
                    mirror,proof=verified_mirror(candidate);metadata['file_verification']=proof
                    document.update(url=mirror['url'],publisher='巨潮资讯；上交所列表交叉核对')
                    result=knowledge.import_document(document,verified_metadata=metadata)
            with connect() as db:db.execute('UPDATE candidates SET imported_source=? WHERE id=?',(result['source_id'],cid))
            output.append({'id':cid,'title':candidate['title'],'ok':True,**result})
        except ValueError as exc:output.append({'id':cid,'title':candidate['title'],'ok':False,'error':str(exc)})
    return {'data':output,'succeeded':sum(bool(r['ok']) for r in output),'failed':sum(not r['ok'] for r in output),'trace':trace}
