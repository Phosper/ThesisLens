"""Live HTTP acceptance for V0.3. --live generates one model research, importing is done in UI."""
import argparse
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

APP=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    base=json.loads((APP/'data/service.json').read_text('utf-8'))['url'];checks=[]
    def request(path,body=None):
        req=urllib.request.Request(base+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
            headers={'Content-Type':'application/json'} if body is not None else {})
        try:
            with urllib.request.urlopen(req,timeout=40) as fp:return fp.status,json.load(fp)
        except urllib.error.HTTPError as exc:return exc.code,json.load(exc)
    def check(name,condition):
        checks.append({'name':name,'passed':bool(condition)})
        if not condition:raise AssertionError(name)
    def job(task):
        for _ in range(700):
            _,r=request('/api/jobs/'+task['job_id'])
            if r['status']=='failed':raise AssertionError(r['error'])
            if r['status']=='complete':return r
            time.sleep(1)
        raise AssertionError('Job timed out')
    _,status=request('/api/status');check('支持V0.3功能的服务',status['version'] in ['0.3.0','0.4.0'])
    _,sources=request('/api/knowledge');official=[r for r in sources['data'] if r.get('official_metadata') and r['enabled']]
    check('三家公司均已实测公告导入',{r['stock_code'] for r in official}=={'000333','000651','600690'})
    for r in official:
        check('官方导入保留摘要和查询出处 '+r['stock_code'],len(r['sha256'])==64 and bool(r['official_metadata']['query_endpoint']))
        before=(dt.date.fromisoformat(r['publication_date'])-dt.timedelta(days=1)).isoformat()
        _,past=request('/api/sources?'+urllib.parse.urlencode({'code':r['stock_code'],'cutoff':before}))
        _,after=request('/api/sources?'+urllib.parse.urlencode({'code':r['stock_code'],'cutoff':r['publication_date']}))
        check('新公告不能进入更早的研究 '+r['stock_code'],r['source_id'] not in {s['source_id'] for s in past['data']} and r['source_id'] in {s['source_id'] for s in after['data']})
    _,rows=request('/api/announcements');check('候选与已导入状态一致',all(r['status']=='available' for r in rows['data'] if r.get('existing_source') in {s['source_id'] for s in official}))
    meetings=[r for r in rows['data'] if '业绩说明会' in r['title']]
    check('业绩说明会公告不误标成财报',all(not r['period'] for r in meetings))
    _,task=request('/api/retrieval',{'question':'美的集团现金流','code':'000333','cutoff':'2026-10-06','period':'2026-H1','semantic':False})
    r=job(task)['result'];check('资料检索不调用模型',r['mode']=='keyword' and not r['model_calls'])
    _,saved=request('/api/retrieval/'+r['id']);check('独立检索记录可恢复',saved['candidate_sha256']==r['candidate_sha256'])
    run_id=None
    if args.live:
        code,task=request('/api/research',{'code':'000333','cutoff':'2026-10-06',
            'question':'美的集团2026年上半年赚的钱真的收回来了吗？请结合存货、汇兑损益和同行核验利润质量。',
            'mode':'llm','options':{'semantic_retrieval':True,'auto_revise':True}})
        check('语义研究任务已接受',code==202)
        busy,_=request('/api/announcements/check',{'code':'000333','start':'2026-09-01','end':'2026-10-07'})
        check('长任务防止重复发起',busy==409)
        completed=job(task);run_id=completed['run_id'];_,run=request('/api/runs/'+run_id)
        check('语义检索任务接入完整备忘录',run['retrieval']['mode'] in ['semantic','expanded','keyword'] and 3<=len(run['model_calls'])<=7)
        check('排序失败不伪装为语义成功',run['retrieval']['mode']=='semantic' or bool(run['retrieval']['warnings']))
        check('新流程仍保留财务原页与最新行业政策',{'IND_010','IND_020','IND_022'}.issubset({e['source_id'] for e in run['evidence']}))
        refs={e['citation'] for e in run['evidence']};check('引用和日期完整有效',all(e['publication_date']<=run['cutoff'] for e in run['evidence']) and all(set(row['citations'])<=refs for key in ['thesis','risks','invalidation','monitoring','open_questions'] for row in run['draft'][key]))
        print(json.dumps({'run_id':run_id,'model_calls':len(run['model_calls']),'steps':len(run['trace']),'evidence':len(run['evidence']),'seconds':run['duration_seconds']},ensure_ascii=False),flush=True)
    result={'created_at':status['today'],'checks':checks,'count':len(checks),'run_id':run_id}
    (APP/'data/stage3_http.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
