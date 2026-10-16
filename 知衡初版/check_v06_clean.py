"""Retained clean app copy; zero models/public requests, synthetic private fixture."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from unittest.mock import patch

import core


def worker():
    import check_v06
    import demo_case
    import exporting
    import server
    public_attempts=[];model_attempts=[]
    original=urllib.request.urlopen
    def local(request,*args,**kwargs):
        url=request.full_url if isinstance(request,urllib.request.Request) else str(request)
        if urllib.parse.urlparse(url).hostname not in ['127.0.0.1','localhost']:
            public_attempts.append(True);raise AssertionError('Public network not allowed in clean test')
        return original(request,*args,**kwargs)
    def no_model(*args,**kwargs):model_attempts.append(True);raise AssertionError('No model in clean test')
    assert not core.INDEX.exists() and not core.RUNS.exists()
    core.ensure_index()
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler);http.daemon_threads=True
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try:
        with patch('urllib.request.urlopen',side_effect=local),patch('model.complete',side_effect=no_model),patch.object(sys,'argv',['check_v06','--base-url','http://127.0.0.1:'+str(http.server_port),'--private-test']):
            check_v06.main()
            restored=demo_case.restore('v06');run=exporting.prepare_run(core.get_run(restored['run_id']))
            assert run['demo_original']['id']=='965d0992d2f6' and len(run['model_calls'])==5
            assert run['research_requirements']['company_profile']['code']=='002032'
            assert run['valuation']['operating_scenario']['available']
            assert all(core.file_for(core.source(e['source_id'])).is_file() for e in run['evidence'])
            assert '海外经营压力情景' in exporting.memo_markdown(run)
            assert not public_attempts and not model_attempts
            result={'passed':True,'private':json.loads((core.DATA/'v06_private_acceptance.json').read_text('utf-8')),
                    'restored_v06_original':'965d0992d2f6','restored_model_calls_are_historical':5,
                    'public_network_attempts':0,'new_model_attempts':0,
                    'scope':'同机干净源码副本与公开资料路径；非另一实体电脑验证。'}
            (core.APP.parent/'clean_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'clean_passed':True,'private_checks':result['private']['passed'],'restored':run['id']},ensure_ascii=False),flush=True)
    finally:http.shutdown();http.server_close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');args=parser.parse_args()
    if args.worker:return worker()
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    target=core.ROOT/'tmp/v06_clean'/stamp;target.mkdir(parents=True)
    shutil.copytree(core.APP,target/'知衡初版',ignore=shutil.ignore_patterns('data','exports','__pycache__','*.pyc','*.log','.env','.env.*','config.local.json'))
    environment=dict(os.environ,ZHIHENG_DATASET=str(core.DATASET),PYTHONIOENCODING='utf-8')
    for name in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','DASHSCOPE_API_KEY','ZHIHENG_API_KEY']:environment.pop(name,None)
    subprocess.run([sys.executable,'-X','utf8',str(target/'知衡初版/check_v06_clean.py'),'--worker'],cwd=target/'知衡初版',env=environment,check=True)
    record=json.loads((core.APP/'V0.6验收记录.json').read_text('utf-8'))
    record['clean_install']=json.loads((target/'clean_acceptance.json').read_text('utf-8'))
    (core.APP/'V0.6验收记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'record':'V0.6验收记录.json','retained_copy':str(target)},ensure_ascii=False))


if __name__=='__main__':main()
