"""Local supplemental documents; dates, provenance, hashes and reversible disabling."""
import base64
import datetime
import hashlib
import gzip
import io
import ipaddress
import json
import re
import socket
import sqlite3
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import core
import audit

DB=core.DATA/'library.sqlite3'
ALLOWED=['gov.cn','cninfo.com.cn','sse.com.cn','midea.com','gree.com','gree.com.cn','haier.com','haier.net','sina.com.cn']

def connect():
    db=sqlite3.connect(DB,factory=core.ClosingConnection);db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,metadata TEXT,enabled INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS passages(id INTEGER PRIMARY KEY,source_id TEXT,pdf_page INTEGER,locator TEXT,text TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS passage_fts USING fts5(tokens);''')
    return db

def sources(include_disabled=False):
    with connect() as db:
        rows=db.execute('SELECT metadata,enabled FROM documents'+('' if include_disabled else ' WHERE enabled=1')).fetchall()
    return [dict(json.loads(r['metadata']),enabled=bool(r['enabled'])) for r in rows]

def source(source_id):
    with connect() as db:r=db.execute('SELECT metadata,enabled FROM documents WHERE id=?',(source_id,)).fetchone()
    return dict(json.loads(r['metadata']),enabled=bool(r['enabled'])) if r else None

def pages():
    with connect() as db:
        rows=db.execute('SELECT p.*,d.metadata FROM passages p JOIN documents d ON d.id=p.source_id WHERE d.enabled=1 AND p.pdf_page IS NOT NULL').fetchall()
    output=[]
    for r in rows:
        m=json.loads(r['metadata']);output.append({'source_id':r['source_id'],'pdf_page':r['pdf_page'],'text':r['text'],'text_origin':'原生文字',
                                                  'company':m.get('company')})
    return output

def passage(source_id,page=None):
    with connect() as db:
        rows=db.execute('SELECT * FROM passages WHERE source_id=?'+(' AND pdf_page=?' if page is not None else '')+' ORDER BY id',
                        (source_id,page) if page is not None else (source_id,)).fetchall()
    return [decorate(dict(r)) for r in rows]

def decorate(r):
    s=source(r['source_id'])
    return dict(r,stock_code=s.get('stock_code'),publication_date=s['publication_date'],report_period=s.get('report_period'),
                title=s['title'],company=s.get('company'),publisher=s['publisher'],source_url=s.get('url',''),ocr=0,
                kind='financial' if s.get('report_period') else 'industry' if s['category']=='04_行业数据与政策' else 'announcement',date_conflict=bool(s.get('official_metadata',{}).get('date_conflict')),revision_flag=False,
                user_imported=True,score=r.get('score',0),
                file_url='/api/files/'+s['source_id']+(f"#page={r['pdf_page']}" if r.get('pdf_page') else ''))

def search(query,code,cutoff,limit,kind='',period='',include_industry=True):
    match=' OR '.join('"'+t+'"' for t in list(dict.fromkeys(core.tokens(query)))[:45])
    if not match:return []
    # Filter before LIMIT: excluded documents must not crowd out valid passages.
    filters=['passage_fts MATCH ?','d.enabled=1',"json_extract(d.metadata,'$.publication_date')<=?"];params=[match,cutoff]
    if code:
        filters.append("(json_extract(d.metadata,'$.stock_code')=? OR json_extract(d.metadata,'$.stock_code') IS NULL)" if include_industry else "json_extract(d.metadata,'$.stock_code')=?")
        params.append(code)
    if period:filters.append("json_extract(d.metadata,'$.report_period')=?");params.append(period)
    if kind:
        filters.append("(CASE WHEN json_extract(d.metadata,'$.report_period') IS NOT NULL THEN 'financial' WHEN json_extract(d.metadata,'$.category')='04_行业数据与政策' THEN 'industry' ELSE 'announcement' END)=?")
        params.append(kind)
    with connect() as db:
        rows=db.execute('''SELECT p.*,d.metadata,bm25(passage_fts) rank FROM passage_fts
            JOIN passages p ON p.id=passage_fts.rowid JOIN documents d ON d.id=p.source_id
            WHERE '''+' AND '.join(filters)+' ORDER BY rank LIMIT 180',params).fetchall()
    output=[]
    for raw in rows:
        r=dict(raw);s=json.loads(r.pop('metadata'))
        if s['publication_date']>cutoff or (code and s.get('stock_code') not in [code,None,'']):continue
        if period and s.get('report_period')!=period:continue
        inferred='financial' if s.get('report_period') else 'industry' if s['category']=='04_行业数据与政策' else 'announcement'
        if kind and inferred!=kind:continue
        if code and not include_industry and s.get('stock_code')!=code:continue
        terms=set(core.tokens(query)[:45])
        coverage=20*len(terms&set(core.tokens(r['text'])))/max(len(terms),1)
        r['score']=sum(min(r['text'].count(t),3)*3 for t in core.TOPICS if t in query)+coverage+min(-r.pop('rank')*2,10)+(12 if query in r['text'] else 0)+(1 if s['publication_date'][:4]=='2026' else 0)
        output.append(decorate(r))
    return sorted(output,key=lambda r:-r['score'])[:limit]

class TextHTML(HTMLParser):
    def __init__(self):super().__init__();self.items=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ['script','style','noscript']:self.skip+=1
        if tag in ['p','div','br','tr','h1','h2','h3'] and not self.skip:self.items.append('\n')
        if tag in ['td','th'] and not self.skip:self.items.append(' | ')
    def handle_endtag(self,tag):
        if tag in ['script','style','noscript']:self.skip=max(0,self.skip-1)
        if tag in ['p','div','tr'] and not self.skip:self.items.append('\n')
    def handle_data(self,data):
        if not self.skip:self.items.append(data)

def allowed_url(url):
    u=urllib.parse.urlparse(url)
    if u.scheme!='https' or u.username or u.password or not u.hostname or u.port not in [None,443]:
        raise ValueError('请输入公开来源的HTTPS地址')
    if not any(u.hostname==d or u.hostname.endswith('.'+d) for d in ALLOWED):
        raise ValueError('网址导入支持政府网站、巨潮资讯、三家公司官网和新浪财经；其他资料请上传本地文件并记录出处。')
    for result in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(result[4][0]).is_global:raise ValueError('资料网址不能指向内网地址')
    return url

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        allowed_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch_document(url):
    allowed_url(url)
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 ThesisLens/0.3 PublicResearch',
            'Referer':'https://www.sse.com.cn/' if urllib.parse.urlparse(url).hostname.endswith('sse.com.cn') else 'https://www.cninfo.com.cn/' if urllib.parse.urlparse(url).hostname.endswith('cninfo.com.cn') else url})
        with urllib.request.build_opener(SafeRedirect()).open(req,timeout=35) as fp:
            raw=fp.read(20*1024*1024+1);ctype=fp.headers.get('Content-Type','')
        if raw.startswith(b'\x1f\x8b'):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:raw=compressed.read(20*1024*1024+1)
    except (OSError,ValueError) as exc:
        if isinstance(exc,ValueError):raise
        raise ValueError('公开网址暂时无法读取。可以从发布方下载后上传，系统不会绕过访问验证。') from None
    is_pdf=raw.startswith(b'%PDF-')
    if (urllib.parse.urlparse(url).path.lower().endswith('.pdf') or 'pdf' in ctype.lower()) and not is_pdf:
        raise ValueError('来源没有返回PDF原件，可能是访问提示。请从发布方手动下载后上传，未将提示网页存为证据。')
    return raw,'pdf' if is_pdf else 'html'

def import_document(body,on_step=None,verified_metadata=None):
    title=str(body.get('title','')).strip()[:200]
    if not title:raise ValueError('请填写资料标题')
    date=str(body.get('publication_date',''))
    try:d=datetime.date.fromisoformat(date)
    except ValueError:raise ValueError('请填写有效的披露日期') from None
    if d>datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date():raise ValueError('披露日期不能晚于今天')
    code=str(body.get('code',''))
    if code and code not in core.COMPANIES:raise ValueError('请选择公司或行业资料')
    period=str(body.get('period',''))
    if period and (not code or not re.fullmatch(r'20\d{2}-(FY|H1|Q1|Q3)',period)):raise ValueError('财报期间应为2026-H1、2025-FY等格式，并选择公司')
    if period:
        import financials
        if financials.period_end(period)>date:raise ValueError('财报期末不能晚于披露日期，预测报告请按补充资料导入')
    url=str(body.get('url','')).strip()
    suffix=str(body.get('filename','')).lower().rsplit('.',1)[-1]
    if body.get('content_base64'):
        try:raw=base64.b64decode(body['content_base64'],validate=True)
        except (ValueError,TypeError):raise ValueError('文件编码无效') from None
    elif body.get('text'):
        raw=str(body['text']).encode('utf-8');suffix='txt'
    elif url:
        raw,suffix=fetch_document(url)
    else:raise ValueError('请上传文件、粘贴正文或填写公开网址')
    if not raw or len(raw)>20*1024*1024:raise ValueError('单份资料限20MB')
    if raw.startswith(b'%PDF-'):suffix='pdf'
    if suffix not in ['pdf','txt','md','html','htm']:raise ValueError('支持PDF、TXT、Markdown和HTML资料')
    pages_data=[]
    if suffix=='pdf':
        try:
            from pypdf import PdfReader
        except ImportError:raise ValueError('PDF导入需要pypdf，请按使用说明安装可选依赖；TXT资料可以直接导入。') from None
        try:
            reader=PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:raise ValueError('请先提供可读取的PDF')
            if len(reader.pages)>1000:raise ValueError('单份PDF限1000页')
            for i,p in enumerate(reader.pages,1):pages_data.append((i,(p.extract_text() or '')[:30000]))
        except ValueError:raise
        except Exception:raise ValueError('PDF内容无法解析，请检查文件或提供文本版本') from None
        if sum(len(t.strip()) for _,t in pages_data)<100:raise ValueError('PDF主要为扫描图片，需要先提供OCR文本；系统未把空白提取当作有效证据。')
    else:
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            try:text=raw.decode('gb18030')
            except UnicodeDecodeError:raise ValueError('文本需为UTF-8或GB18030编码') from None
        if suffix in ['html','htm']:
            parser=TextHTML();parser.feed(text);text=''.join(parser.items)
        if len(text.strip())<30:raise ValueError('有效正文至少30字')
        pages_data=[(None,text[:1000000])]
    digest=hashlib.sha256(raw).hexdigest();sid='CUSTOM_'+digest[:16]
    base_duplicate=next((s for s in core.base_manifest()['sources'] if s.get('sha256')==digest),None)
    if base_duplicate:
        audit.cache_hit('import_duplicate',source_id=base_duplicate['source_id'],sha256=digest)
        return {'source_id':base_duplicate['source_id'],'title':base_duplicate['title'],'duplicate':True,'note':'原件摘要与基础资料相同，复用已有原件。'}
    existing=source(sid)
    if existing:
        audit.cache_hit('import_duplicate',source_id=sid,sha256=digest)
        if not existing['enabled']:set_enabled(sid,True)
        return {'source_id':sid,'title':existing['title'],'duplicate':True}
    folder=core.DATA/'library';folder.mkdir(exist_ok=True)
    file=folder/(sid+'.'+suffix);file.write_bytes(raw)
    audit.event('source_import',source_id=sid,purpose='user_import',status='success',sha256=digest,bytes=len(raw))
    record={'source_id':sid,'title':title,'stock_code':code or None,'company':core.COMPANIES.get(code),'report_period':period or None,
            'publisher':str(body.get('publisher','用户补充资料'))[:100],'publication_date':date,'url':url,
            'relative_path':file.relative_to(core.APP).as_posix(),'storage':'user-library','category':'01_公司财报' if period else '03_经营公告与调研' if code else '04_行业数据与政策',
            'sha256':digest,'page_count':len(pages_data) if suffix=='pdf' else None,'imported_at':core.now(),
            'provenance_note':'官方公告列表提供标题、公司和披露日期；正文与原页仍需核验。' if verified_metadata else '用户补充的来源与披露日期，仍需人工核对元数据。'}
    if verified_metadata:record['official_metadata']=dict(verified_metadata)
    with connect() as db:
        db.execute('INSERT INTO documents(id,metadata) VALUES (?,?)',(sid,core.json_dump(record)))
        for page,text in pages_data:
            if page is not None:
                # Financial extraction needs the complete physical page.
                cursor=db.execute('INSERT INTO passages(source_id,pdf_page,locator,text) VALUES (?,?,?,?)',(sid,page,f'PDF第{page}页',text))
                db.execute('INSERT INTO passage_fts(rowid,tokens) VALUES (?,?)',(cursor.lastrowid,' '.join(core.tokens(text))))
            else:
                for i,part in enumerate(core.split_text(text),1):
                    cursor=db.execute('INSERT INTO passages(source_id,locator,text) VALUES (?,?,?)',(sid,f'正文片段{i}',part))
                    db.execute('INSERT INTO passage_fts(rowid,tokens) VALUES (?,?)',(cursor.lastrowid,' '.join(core.tokens(part))))
    return {'source_id':sid,'title':title,'pages':len(pages_data),'sha256':digest,'duplicate':False,
            'note':'已加入本机资料库；披露日期与原文数字需人工核验。'}

def set_enabled(sid,enabled):
    if not source(sid):raise ValueError('补充资料不存在')
    with connect() as db:db.execute('UPDATE documents SET enabled=? WHERE id=?',(int(bool(enabled)),sid))
    return {'source_id':sid,'enabled':bool(enabled),'note':'禁用后停止用于新研究，原件保留供历史引用回看。'}
