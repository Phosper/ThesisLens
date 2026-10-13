"""Independent offline acceptance: real local reads, mocked model failures and HTTP streams."""
import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import tempfile
import urllib.error
from unittest.mock import patch
import audit
import core
import exporting
import knowledge
import model
import research
import server
import workbench


class Response:
    def __init__(self,raw):self.raw=raw
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,*args):return self.raw


def main():
    report={'version':'0.5.0','checked_at':core.now(),'scope':'同机离线独立检查：真实本地文件读取、模型失败模拟与HTTP处理器字节输出，不使用服务端口或实际模型/外网。','checks':[],'real_model_calls':0,'external_network_calls':0}
    def check(name,ok):
        report['checks'].append({'name':name,'passed':bool(ok)})
        if not ok:raise AssertionError(name)
    marker='private_audit_fixture_'+('x'*22)
    with tempfile.TemporaryDirectory(dir=core.DATA) as raw_folder:
        folder=Path(raw_folder)
        with patch.object(core,'DATA',folder),patch.object(core,'RUNS',folder/'runs.sqlite3'),patch.object(knowledge,'DB',folder/'library.sqlite3'),patch.object(workbench,'DB',folder/'workbench.sqlite3'):
            file=folder/'sample.txt';file.write_text(marker,encoding='utf-8')
            with audit.context(run_id='independent-source'):
                text=audit.read_text(file,source_id='TEST-SOURCE',purpose='independent_source')
                audit.cache_hit('independent_cache',source_id='TEST-SOURCE')
                try:audit.read_bytes(folder/'missing.txt',source_id='MISSING')
                except FileNotFoundError:pass
            s=audit.snapshot('independent-source')
            check('实际素材读取记录字节与实际SHA',text==marker and any(e.get('sha256')==hashlib.sha256(marker.encode()).hexdigest() and e.get('bytes')==len(marker.encode()) for e in s['events']))
            check('缓存与实读明确区分',any(e.get('cache_hit') is True for e in s['events']) and any(e.get('cache_hit') is False for e in s['events']))
            check('素材读取失败不丢失',any(e.get('status')=='failed' and e.get('error_kind')=='FileNotFoundError' for e in s['events']))
            check('审计不复制素材正文或本机绝对路径',marker not in json.dumps(s) and str(folder) not in json.dumps(s))
            cfg={'provider':'test','model':'test-alias','base_url':'https://example.invalid','key_env':'ZHIHENG_API_KEY'}
            successful={'model':'test-response-version','choices':[{'message':{'content':'{"ok": true}'},'finish_reason':'stop'}],'usage':{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5}}
            with audit.context(run_id='independent-success'),patch('model.credentials',return_value=(cfg,marker)),patch('urllib.request.urlopen',return_value=Response(json.dumps(successful).encode())):
                result,log=model.complete(marker,marker)
            s=audit.snapshot('independent-success');attempt=s['model_attempts'][0]
            check('成功请求持久记录含独立编号与用量',result=={'ok':True} and attempt['status']=='success' and attempt['usage']['total_tokens']==5 and log['attempt_id']==attempt['attempt_id'])
            check('请求模型别名与实际响应名称分开',attempt.get('response_model')=='test-response-version' and log['response_model']=='test-response-version')
            failures=[('http',urllib.error.HTTPError('https://example.invalid',402,marker,{},io.BytesIO(marker.encode())),None,'http_error'),
                      ('timeout',TimeoutError(marker),None,'connection_or_timeout'),
                      ('json',None,b'{"private_body":','invalid_response_json'),
                      ('length',None,json.dumps({'choices':[{'finish_reason':'length','message':{'content':marker}}]}).encode(),'length_limit')]
            for name,error,body,kind in failures:
                with audit.context(run_id='independent-'+name),patch('model.credentials',return_value=(cfg,marker)),patch('urllib.request.urlopen',side_effect=error,return_value=Response(body or b'')):
                    try:model.complete(marker,marker)
                    except ValueError:pass
                    else:raise AssertionError('Expected a failed model attempt')
                s=audit.snapshot('independent-'+name)
                check('模型'+name+'失败独立持久留痕',len(s['model_attempts'])==1 and s['model_attempts'][0]['status']=='failed' and s['model_attempts'][0]['error_kind']==kind and marker not in json.dumps(s))
            with audit.context(run_id='independent-credentials'),patch('model.credentials',side_effect=ValueError(marker)),patch('urllib.request.urlopen',side_effect=AssertionError('No actual network allowed')):
                try:model.complete(marker,marker)
                except ValueError:pass
            s=audit.snapshot('independent-credentials')
            check('缺少凭据亦保留失败尝试',len(s['model_attempts'])==1 and s['model_attempts'][0]['status']=='failed' and marker not in json.dumps(s))
            @audit.operation('independent-failure')
            def fail_operation():
                audit.event('progress',purpose='step-completed',status='success')
                raise ValueError(marker)
            with audit.context(run_id='independent-failure',job_id='independent-job'):
                try:fail_operation()
                except ValueError:pass
            s=audit.snapshot(job_id='independent-job')
            check('没有研究结果也保留失败任务与已完成过程',any(e.get('purpose')=='step-completed' for e in s['events']) and any(e.get('operation')=='independent-failure' and e.get('status')=='failed' for e in s['events']) and marker not in json.dumps(s))
            def thread(name):
                with audit.context(run_id=name):
                    aid=audit.begin_attempt('test','test',marker,marker)
                    audit.finish_attempt(aid,'success',1)
                    return aid
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:ids=list(executor.map(thread,['parallel-a','parallel-b']))
            check('并行尝试编号独立且关联正确',len(set(ids))==2 and all(len(audit.snapshot(name)['model_attempts'])==1 for name in ['parallel-a','parallel-b']))
            def stream(run_id,range_header=None,missing=False):
                handler=server.Handler.__new__(server.Handler)
                handler.headers={} if range_header is None else {'Range':range_header}
                handler.wfile=io.BytesIO();statuses=[]
                handler.send_response=lambda value:statuses.append(value)
                handler.send_header=lambda *args:None;handler.end_headers=lambda:None
                with audit.context(run_id=run_id):
                    handler.send_file(folder/'missing.txt' if missing else file,source={'source_id':'TEST-SOURCE','sha256':hashlib.sha256(marker.encode()).hexdigest()})
                return statuses,handler.wfile.getvalue(),audit.snapshot(run_id)
            statuses,body,s=stream('stream-range','bytes=2-5')
            check('HTTP206真实分片与传输摘要一致',statuses==[206] and body==marker.encode()[2:6] and any(e.get('http_status')==206 and e.get('bytes')==4 and e.get('transfer_sha256')==hashlib.sha256(body).hexdigest() and e.get('source_sha256')==hashlib.sha256(marker.encode()).hexdigest() for e in s['events']))
            statuses,body,s=stream('stream-full')
            check('HTTP200实际字节访问完整留痕',statuses==[200] and body==marker.encode() and any(e.get('bytes')==len(body) and e.get('status')=='success' for e in s['events']))
            statuses,body,s=stream('stream-bad','bytes=999-1000')
            check('无效Range失败仍可回查',statuses==[416] and any(e.get('http_status')==416 and e.get('status')=='failed' for e in s['events']))
            statuses,body,s=stream('stream-missing',missing=True)
            check('原件不存在失败仍可回查',statuses==[404] and any(e.get('http_status')==404 and e.get('source_id')=='TEST-SOURCE' for e in s['events']))
            with patch('model.complete',side_effect=AssertionError('No live model allowed')),patch('urllib.request.urlopen',side_effect=AssertionError('No network allowed')):
                run=research.run('000333','2026-10-06','2026年上半年应收与存货的证据核验','local')
                saved=core.get_run(run['id']);shown=exporting.prepare_run(saved)
                check('实际资料模式生成与访问过程关联',shown['audit']['available'] and shown['audit']['event_count']>0 and shown['audit']['model_attempts']==[])
                check('典型研究日志未截断且原输出保存不变',not shown['audit']['truncated'] and saved['draft']==run['draft'])
                check('旧模型记录不追补生成审计',not audit.snapshot('c30a0bb56179')['available'] and bool(audit.snapshot('c30a0bb56179')['historical_note']))
                report['local_research_event_count']=shown['audit']['event_count']
            all_safe=audit.snapshot(limit=5000)
            check('全体安全元数据不泄露原文密钥路径',marker not in json.dumps(all_safe) and str(folder) not in json.dumps(all_safe))
    report.update(passed=len(report['checks']),failed=0)
    (core.DATA/'audit_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['passed','failed','real_model_calls','external_network_calls','local_research_event_count']},ensure_ascii=False))


if __name__=='__main__':main()
