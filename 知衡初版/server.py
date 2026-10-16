"""Local-only application server. Python standard library, no package installation."""
from __future__ import annotations
import argparse
import json
import mimetypes
import re
import threading
import urllib.parse
import uuid
import hashlib
import importlib.util
import companies
import research_requirements
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import core
import model
import research
import financials
import financial_depth
import valuation
import workbench
import knowledge
import questions
import exporting
import retrieval
import announcements
import audit

JOBS={};JOBS_LOCK=threading.Lock();RESEARCH_GATE=threading.BoundedSemaphore(1)

def job_work(job_id,body,operation='research'):
    with audit.context(job_id=job_id,run_id=uuid.uuid4().hex[:12]):
        return audited_job_work(job_id,body,operation)

def audited_job_work(job_id,body,operation='research'):
    def progress(trace):
        with JOBS_LOCK: JOBS[job_id]['trace']=trace
    try:
        audit.event('job',operation=operation,status='started')
        with JOBS_LOCK:JOBS[job_id]['audit_run_id']=audit.current()['run_id']
        if operation=='research':
            result=research.run(body.get('code','000333'),body.get('cutoff','2026-10-06'),body.get('question',''),body.get('mode','local'),progress,body.get('options'))
            payload={'run_id':result['id']}
        elif operation=='import':payload={'result':knowledge.import_document(body,progress)}
        elif operation=='retrieval':payload={'result':retrieval.search(body.get('question',''),body.get('code',''),body.get('cutoff','2026-10-06'),body.get('limit',14),period=body.get('period',''),semantic=bool(body.get('semantic',True)),on_step=progress)}
        elif operation=='discover':payload={'result':announcements.discover(body,progress)}
        elif operation=='official_import':payload={'result':announcements.import_selected(body,progress)}
        else:payload={'result':questions.answer(body)}
        with JOBS_LOCK: JOBS[job_id].update(status='complete',**payload)
        audit.event('job',operation=operation,status='success')
    except Exception as exc:
        try:audit.event('job',operation=operation,status='failed',error_kind=type(exc).__name__)
        except Exception:pass
        with JOBS_LOCK:
            JOBS[job_id].update(status='failed',error=str(exc) if isinstance(exc,(ValueError,KeyError)) else '本次研究未完成，请检查资料或模型服务。')
    finally: RESEARCH_GATE.release()

class Handler(BaseHTTPRequestHandler):
    server_version='Zhiheng/0.6'

    def log_message(self,*args):
        pass  # No URLs, user questions or credentials in access logs.

    def valid_host(self):
        return self.headers.get('Host','') in [f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}']

    def reply(self,obj,status=200):
        data=core.json_dump(obj).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

    def send_file(self,path,download_name=None,trusted_html=False,source=None):
        path=Path(path)
        def access(status,http_status,bytes=0,error_kind=None,**extra):
            if source:audit.event('original_http',source_id=source['source_id'],source_sha256=source.get('sha256'),purpose='original_file_http',status=status,http_status=http_status,bytes=bytes,error_kind=error_kind,**extra)
        if not path.is_file():
            access('failed',404,error_kind='not_found');return self.reply({'error':'文件不存在'},404)
        mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if path.suffix.lower()=='.html' and path.parent!=core.APP/'static' and not trusted_html:
            mime='application/octet-stream';download_name=path.name
        size=path.stat().st_size;start=0;end=size-1;status=200
        range_header=self.headers.get('Range')
        if range_header:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header)
            if not match:
                access('failed',416,error_kind='invalid_range');return self.reply({'error':'不支持的文件范围'},416)
            if not match.group(1):
                suffix=int(match.group(2) or 0);start=max(0,size-suffix)
            else: start=int(match.group(1));end=min(int(match.group(2) or size-1),size-1)
            if not 0<=start<=end<size:
                access('failed',416,error_kind='invalid_range');return self.reply({'error':'文件范围越界'},416)
            status=206
        self.send_response(status);self.send_header('Content-Type',mime+('; charset=utf-8' if mime.startswith('text/') else ''))
        self.send_header('Accept-Ranges','bytes');self.send_header('X-Content-Type-Options','nosniff')
        if status==206: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        if download_name: self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+urllib.parse.quote(download_name))
        self.send_header('Content-Length',str(end-start+1));self.end_headers()
        transferred=0;digest=hashlib.sha256();failure=None
        try:
            with path.open('rb') as fp:
                fp.seek(start);remaining=end-start+1
                while remaining>0:
                    part=fp.read(min(65536,remaining))
                    if not part:failure='unexpected_eof';break
                    try:self.wfile.write(part)
                    except (BrokenPipeError,ConnectionResetError):failure='connection_closed';break
                    remaining-=len(part);transferred+=len(part);digest.update(part)
        except OSError as error:
            failure=type(error).__name__;raise
        finally:
            access('failed' if failure else 'success',status,bytes=transferred,error_kind=failure,transfer_sha256=digest.hexdigest(),range_start=start,range_end=end)

    def do_GET(self):
        if not self.valid_host(): return self.reply({'error':'仅允许本机访问'},403)
        core.LOCAL_BASE_URL=f'http://127.0.0.1:{self.server.server_port}'
        parts=urllib.parse.urlparse(self.path);path=parts.path
        query=urllib.parse.parse_qs(parts.query)
        def get(key,default=''): return query.get(key,[default])[0]
        try:
            if path=='/api/status':
                with core.connect() as db: index=dict(db.execute('SELECT key,value FROM meta').fetchall())
                return self.reply({'version':'0.7.0','name':'知衡','today':announcements.today(),'instance_id':hashlib.sha256(str(core.APP).encode()).hexdigest()[:16],
                      'companies':core.COMPANIES,'dataset':core.manifest()['stats'],
                      'company_profiles':companies.profiles(),
                      'cutoff':core.manifest()['research_cutoff'],'index':index,'model':model.get_config(),
                      'financial_coverage':financials.history(cutoff=core.manifest()['research_cutoff'])['coverage'],
                      'periods':sorted({r['period'] for r in financials.history(cutoff=core.manifest()['research_cutoff'])['data']},key=financials.period_end,reverse=True),
                      'pdf_import_available':importlib.util.find_spec('pypdf') is not None})
            if path=='/api/companies':
                sources=core.manifest()['sources'];history=financials.history(cutoff=get('cutoff','2026-10-06'))['data']
                return self.reply({'data':[dict(profile,reports=sum(s.get('stock_code')==profile['code'] and bool(s.get('report_period')) for s in sources),
                    financial_period=next((r['period'] for r in reversed(history) if r['code']==profile['code']),None)) for profile in companies.profiles()]})
            if path=='/api/research/requirements':return self.reply(research_requirements.context(get('code','000333')))
            if path=='/api/audit':return self.reply(audit.snapshot(get('run_id') or None,get('job_id') or None,int(get('limit','1000'))))
            if path=='/api/financial/history':return self.reply(financials.history(get('code'),get('cutoff','2026-10-06'),get('kind')))
            if path=='/api/financial/depth':return self.reply(financial_depth.snapshot(get('code','000333'),get('cutoff','2026-10-06'),get('period') or None))
            if path=='/api/financial/depth/export':
                text=financial_depth.export_csv(get('code','000333'),get('cutoff','2026-10-06'),get('period') or None)
                folder=core.APP/'exports';folder.mkdir(exist_ok=True)
                file=folder/'知衡_财务解剖.csv';file.write_text(text,encoding='utf-8');return self.send_file(file,file.name)
            if path=='/api/financial/export':
                text=exporting.financial_csv(get('code'),get('cutoff','2026-10-06'));folder=core.APP/'exports';folder.mkdir(exist_ok=True)
                file=folder/f"知衡_财务指标_{core.COMPANIES.get(get('code'),'全部公司')}.csv";file.write_text(text,encoding='utf-8')
                return self.send_file(file,file.name)
            if path=='/api/valuation/context':return self.reply(valuation.context(get('code','000333'),get('cutoff','2026-10-06')))
            if path.startswith('/api/valuations/'):return self.reply(workbench.get_valuation(path.rsplit('/',1)[-1]))
            if path=='/api/watchlist':return self.reply(workbench.watchlist(get('cutoff','2026-10-06')))
            if path=='/api/knowledge':return self.reply({'data':knowledge.sources(True),'allowed_domains':knowledge.ALLOWED})
            if path=='/api/announcements':return self.reply(announcements.list_candidates(get('code'),get('start'),get('end'),get('keyword')))
            if path.startswith('/api/retrieval/'):return self.reply(retrieval.get(path.rsplit('/',1)[-1]))
            if path=='/api/questions':return self.reply({'data':questions.history(get('run_id'))})
            if path=='/api/metrics': return self.reply({'data':core.metric_rows(get('period','2026-H1'),get('cutoff','2026-10-06'))})
            if path=='/api/search': return self.reply({'data':core.search(get('q'),get('code'),get('cutoff','2026-10-06'),int(get('limit','12')),get('kind'),get('period'))})
            if path=='/api/sources': return self.reply({'data':core.list_sources(get('q'),get('code'),get('category'),get('cutoff','2026-10-06'))})
            if path=='/api/prices': return self.reply(core.prices(get('code','000333'),get('cutoff','2026-10-06')))
            if path=='/api/runs': return self.reply({'data':core.list_runs()})
            if path=='/api/config': return self.reply(model.get_config())
            if path.startswith('/api/jobs/'):
                with JOBS_LOCK: job=dict(JOBS.get(path.rsplit('/',1)[-1],{}))
                if not job: return self.reply({'error':'任务不存在'},404)
                return self.reply(job)
            if path.startswith('/api/runs/'):
                suffix=path[len('/api/runs/'):];run_id=suffix.split('/')[0]
                result=exporting.prepare_run(core.get_run(run_id))
                if suffix.endswith('/quality'):return self.reply(result['human_review'])
                if suffix.endswith('/print'):
                    view=exporting.report_view(get('view','full'))
                    folder=core.APP/'exports';folder.mkdir(exist_ok=True)
                    tail='_简略版' if view=='brief' else ''
                    file=folder/f"知衡_{result['company']}_{result['id']}{tail}.html";file.write_text(exporting.memo_html(result,view),encoding='utf-8')
                    return self.send_file(file,trusted_html=True)
                if suffix.endswith('/export'):
                    fmt=get('format','md')
                    if fmt not in ['md','json','html']: raise ValueError('导出格式应为md、json或html')
                    view=exporting.report_view(get('view','full'))
                    export=core.APP/'exports';export.mkdir(exist_ok=True)
                    tail='_简略版' if view=='brief' and fmt!='json' else ''
                    file=export/f"知衡_{result['company']}_{result['id']}{tail}.{fmt}"
                    content=exporting.memo_markdown(result,view) if fmt=='md' else exporting.memo_html(result,view) if fmt=='html' else json.dumps(result,ensure_ascii=False,indent=2)
                    file.write_text(content,encoding='utf-8')
                    return self.send_file(file,file.name)
                return self.reply(result)
            if path.startswith('/api/files/'):
                source_id=urllib.parse.unquote(path[len('/api/files/'):])
                with audit.context(run_id=get('run_id') or None):
                    try:
                        record=core.source(source_id);file=core.file_for(record)
                    except (ValueError,KeyError) as error:
                        audit.event('original_http',source_id=source_id,purpose='original_file_http',status='failed',http_status=400,error_kind=type(error).__name__)
                        raise
                    return self.send_file(file,file.name if get('download')=='1' else None,source=record)
            static=core.APP/'static'
            file=(static/('index.html' if path=='/' else urllib.parse.unquote(path).lstrip('/'))).resolve()
            if not file.is_relative_to(static): return self.reply({'error':'路径无效'},403)
            return self.send_file(file)
        except (ValueError,KeyError) as exc: return self.reply({'error':str(exc)},400)
        except Exception: return self.reply({'error':'请求未完成，请检查本地资料与服务。'},500)

    def do_POST(self):
        expected=[f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}']
        if not self.valid_host() or (self.headers.get('Origin') and self.headers['Origin'] not in expected):
            return self.reply({'error':'拒绝跨站请求'},403)
        if not self.headers.get('Content-Type','').startswith('application/json'):
            return self.reply({'error':'需要JSON请求'},415)
        try:
            size=int(self.headers.get('Content-Length','0'))
            maximum=30*1024*1024 if self.path=='/api/knowledge/import' else 65536
            if not 1<=size<=maximum: raise ValueError('请求大小无效')
            body=json.loads(self.rfile.read(size))
            if not isinstance(body,dict): raise ValueError('请求格式无效')
            if self.path=='/api/companies':
                if not RESEARCH_GATE.acquire(blocking=False):return self.reply({'error':'研究进行中，请稍后登记企业'},409)
                try:return self.reply(companies.register(body))
                finally:RESEARCH_GATE.release()
            if self.path=='/api/config':
                if not RESEARCH_GATE.acquire(blocking=False):return self.reply({'error':'研究进行中，请完成后再修改模型连接'},409)
                try:return self.reply(model.configure(body))
                finally:RESEARCH_GATE.release()
            if self.path=='/api/config/test':
                if not RESEARCH_GATE.acquire(blocking=False):return self.reply({'error':'已有任务进行中'},409)
                try:
                    result,log=model.complete('仅返回JSON对象：{"ok":true}。','验证模型连接',max_tokens=60)
                    return self.reply({'ok':result.get('ok') is True,'provider':log['provider'],'model':log['model'],'usage':log.get('usage',{})})
                finally:RESEARCH_GATE.release()
            if self.path=='/api/valuation':return self.reply(workbench.save_valuation(body))
            if self.path=='/api/watchlist':return self.reply(workbench.create_watch(body))
            if self.path.startswith('/api/watchlist/'):return self.reply(workbench.set_watch_enabled(self.path.rsplit('/',1)[-1],body.get('enabled')))
            if self.path.startswith('/api/knowledge/') and self.path.endswith('/enabled'):
                if not isinstance(body.get('enabled'),bool):raise ValueError('启用状态需要布尔值')
                return self.reply(knowledge.set_enabled(self.path.split('/')[-2],body['enabled']))
            if self.path.startswith('/api/runs/') and self.path.endswith('/annotations'):
                return self.reply(workbench.annotate(self.path.split('/')[-2],body))
            if self.path in ['/api/research','/api/knowledge/import','/api/questions','/api/retrieval','/api/announcements/check','/api/announcements/import']:
                if not RESEARCH_GATE.acquire(blocking=False): return self.reply({'error':'已有研究正在进行，请等它完成'},409)
                job_id=uuid.uuid4().hex[:12]
                with JOBS_LOCK:
                    if len(JOBS)>100:
                        done=next((k for k,v in JOBS.items() if v['status']!='running'),None)
                        if done: JOBS.pop(done)
                    JOBS[job_id]={'id':job_id,'status':'running','trace':[]}
                operation={'/api/research':'research','/api/knowledge/import':'import','/api/questions':'questions','/api/retrieval':'retrieval','/api/announcements/check':'discover','/api/announcements/import':'official_import'}[self.path]
                threading.Thread(target=job_work,args=(job_id,body,operation),daemon=True).start()
                return self.reply({'job_id':job_id},202)
            return self.reply({'error':'接口不存在'},404)
        except (ValueError,KeyError,json.JSONDecodeError) as exc: return self.reply({'error':str(exc)},400)
        except Exception: return self.reply({'error':'请求未完成'},500)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args();core.ensure_index()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.daemon_threads=True
    print(f'Zhiheng ready at http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
