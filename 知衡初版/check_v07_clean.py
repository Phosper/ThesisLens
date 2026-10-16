"""Fresh local install: private boundary and three saved public cases, no model or public network."""
import argparse,datetime,json,os,shutil,subprocess,sys,threading,urllib.request,urllib.parse
from pathlib import Path
from unittest.mock import patch
import core

def worker():
    import check_v07,demo_case,exporting,server
    assert not core.INDEX.exists() and not core.RUNS.exists()
    core.ensure_index();original=urllib.request.urlopen
    def local(request,*args,**kwargs):
        url=request.full_url if isinstance(request,urllib.request.Request) else str(request)
        if urllib.parse.urlparse(url).hostname not in ['127.0.0.1','localhost']:raise AssertionError('公网请求不允许')
        return original(request,*args,**kwargs)
    def no_model(*args,**kwargs):raise AssertionError('恢复不调用模型')
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);http.daemon_threads=True
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        restored=[]
        with patch('urllib.request.urlopen',side_effect=local),patch('model.complete',side_effect=no_model),patch.object(sys,'argv',['check_v07','--base-url','http://127.0.0.1:'+str(http.server_port),'--private-test']):
            check_v07.main()
            for version in ['v07','v07_boss','v07_hisense']:
                result=demo_case.restore(version);r=exporting.prepare_run(core.get_run(result['run_id']))
                assert r['demo_original']['version']=='0.7.0'
                assert any(r['draft'][key] for key in ['thesis','risks','invalidation','monitoring','open_questions'])
                assert r['financial_depth']['available'] and len(r['disclosure_coverage']['rows'])==5
                assert all(core.file_for(core.source(e['source_id'])).is_file() for e in r['evidence'])
                assert '金额附注取回状态' in exporting.memo_html(r)
                restored.append({'version':version,'original':r['demo_original']['id'],'historical_calls':len(r['model_calls'])})
        record={'passed':True,'private_checks':json.loads((core.DATA/'v07_private_acceptance.json').read_text('utf-8'))['passed'],
                'restored':restored,'new_model_calls':0,'public_network_calls':0,'scope':'同机干净安装，不代表另一实体电脑。'}
        (core.APP.parent/'clean_acceptance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(record,ensure_ascii=False))
    finally:http.shutdown();http.server_close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');args=parser.parse_args()
    if args.worker:return worker()
    target=core.ROOT/'tmp/v07_clean'/datetime.datetime.now().strftime('%Y%m%d_%H%M%S');target.mkdir(parents=True)
    shutil.copytree(core.APP,target/'知衡初版',ignore=shutil.ignore_patterns('data','exports','__pycache__','*.pyc','*.log','.env','.env.*','config.local.json'))
    env=dict(os.environ,ZHIHENG_DATASET=str(core.DATASET),PYTHONIOENCODING='utf-8')
    for key in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','DASHSCOPE_API_KEY','ZHIHENG_API_KEY']:env.pop(key,None)
    subprocess.run([sys.executable,'-X','utf8',str(target/'知衡初版/check_v07_clean.py'),'--worker'],cwd=target/'知衡初版',env=env,check=True)
    record=json.loads((core.APP/'V0.7验收记录.json').read_text('utf-8'));record['clean_install']=json.loads((target/'clean_acceptance.json').read_text('utf-8'))
    (core.APP/'V0.7验收记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'retained_copy':str(target)},ensure_ascii=False))
if __name__=='__main__':main()
