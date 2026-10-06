"""One bounded end-to-end live call, with credentials read only by model.py."""
import json
import time
import urllib.request

base='http://127.0.0.1:8765'
body=json.dumps({'code':'000333','cutoff':'2026-10-06','question':'美的集团2026年上半年营收、利润与现金流表现如何？有哪些需要反向验证的风险？','mode':'llm'},ensure_ascii=False).encode('utf-8')
req=urllib.request.Request(base+'/api/research',data=body,headers={'Content-Type':'application/json'})
with urllib.request.urlopen(req) as fp: task=json.load(fp)
print('LIVE_MODEL_JOB',task['job_id'],flush=True)
last=None
for _ in range(150):
    with urllib.request.urlopen(base+'/api/jobs/'+task['job_id']) as fp: job=json.load(fp)
    stage=job['trace'][-1]['title'] if job['trace'] else '准备'
    if stage!=last: print('STAGE',stage,flush=True);last=stage
    if job['status']=='failed':
        print('LIVE_MODEL_FAILED',job['error'],flush=True)
        raise SystemExit(1)
    if job['status']=='complete':
        with urllib.request.urlopen(base+'/api/runs/'+job['run_id']) as fp: result=json.load(fp)
        print('LIVE_MODEL_OK',result['id'],len(result['evidence']),'evidence',len(result['model_calls']),'model calls',result['duration_seconds'],'seconds',flush=True)
        print('MODELS',[c['model'] for c in result['model_calls']],flush=True)
        print('REVIEW_ITEMS',len(result['review'].get('issues',[])),flush=True)
        break
    time.sleep(2)
else: raise SystemExit('Live check timed out')
