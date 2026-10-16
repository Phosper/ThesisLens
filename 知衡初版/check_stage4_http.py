"""V0.4/V0.5-compatible HTTP checks. --live makes one full model case."""
import argparse
import json
import time
import urllib.request
import urllib.error
import urllib.parse
import core

def main():
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group();mode.add_argument('--live',action='store_true');mode.add_argument('--run-id',help='Validate a saved model record without another model call');parser.add_argument('--base-url',help='Use an explicit local test instance');args=parser.parse_args()
    base=args.base_url or json.loads((core.DATA/'service.json').read_text('utf-8'))['url'];checks=[]
    def request(path,body=None):
        req=urllib.request.Request(base+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
                                   headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=25) as response:
            data=response.read();return json.loads(data) if response.headers.get('Content-Type','').startswith('application/json') else data
    def check(name,ok):
        checks.append({'name':name,'passed':bool(ok)})
        if not ok:raise AssertionError(name)
    def job(body):
        task=request('/api/research',body)
        for _ in range(180):
            row=request('/api/jobs/'+task['job_id'])
            if row['status']=='failed':raise ValueError(row['error'])
            if row['status']=='complete':return request('/api/runs/'+row['run_id'])
            time.sleep(1)
        raise TimeoutError('Research task still running')
    actual_version=request('/api/status')['version']
    check('兼容V0.4至V0.6实例',actual_version in ['0.4.0','0.5.0','0.6.0'])
    for code in core.COMPANIES:
        for period in ['2025-FY','2026-H1']:
            p=request('/api/financial/depth?'+urllib.parse.urlencode({'code':code,'cutoff':'2026-10-06','period':period}))
            check(code+' '+period+'财务解剖',p['available'] and p['shares']['total']>0 and len(p['segments'])>=5)
    p=request('/api/financial/depth?code=000333&cutoff=2026-08-28&period=2026-H1')
    check('未披露期间不穿越',not p['available'])
    p=request('/api/financial/depth?code=000333&cutoff=2026-10-06&period=2024-H1')
    check('未登记期间不套用',not p['available'])
    check('CSV保留原页与口径','期末对比' in request('/api/financial/depth/export?code=000333&cutoff=2026-10-06&period=2026-H1').decode('utf-8'))
    c=request('/api/valuation/context?code=000333&cutoff=2026-10-06');s=c['reported_shares']
    v=request('/api/valuation',{'code':'000333','cutoff':'2026-10-06','assumptions':{'shares_yi':s['total_yi'],'shares_source_id':s['source_id'],'pe_low':'8','pe_base':'12','pe_high':'16'}})
    check('估值分母原件可追溯',v['assumptions']['shares_source_id']==s['source_id'] and v['pe_scenarios'][1]['equity_value_yi']=='5325.33')
    try:request('/api/valuation',{'code':'000333','cutoff':'2026-10-06','assumptions':{'shares_yi':'1','shares_source_id':s['source_id']}});rejected=False
    except urllib.error.HTTPError as exc:rejected=exc.code==400
    check('伪造已核对股数被拒绝',rejected)
    local=job({'code':'000333','cutoff':'2026-10-06','question':'美的2026年上半年应收、存货和现金流变化如何核验？','mode':'local','options':{'valuation_id':v['id']}})
    check('资料模式零模型调用',not local['model_calls'])
    check('资料模式含解剖与论据关联',local['financial_depth']['available'] and all(x['thesis_ids'] for k in ['risks','invalidation','monitoring'] for x in local['draft'][k]))
    live=None
    if args.live:
        live=job({'code':'000333','cutoff':'2026-10-06','question':'请为美的集团2026年上半年形成完整买方投资备忘录：围绕增长与利润质量、应收和存货、海外收入、同行及所附估值情景，提出可被反证的论据、失效条件与持续跟踪指标。','mode':'llm','options':{'semantic_retrieval':True,'auto_revise':True,'valuation_id':v['id']}})
    elif args.run_id:live=request('/api/runs/'+args.run_id)
    if live:
        check('真实模型研究含财务解剖',live['mode']=='llm' and live['financial_depth']['available'] and len(live['model_calls'])>=3)
        check('真实模型关联有效论据',all(x['thesis_ids'] for k in ['risks','invalidation','monitoring'] for x in live['draft'][k]))
        check('真实模型所附估值留存',live['valuation']['id']==v['id'] if args.live else live['valuation']['code']==live['code'] and live['valuation']['cutoff']==live['cutoff'])
    target=live or local
    for fmt in ['md','json','html']:
        content=request('/api/runs/'+target['id']+'/export?format='+fmt)
        check('研究导出 '+fmt,('财务解剖' in (json.dumps(content,ensure_ascii=False) if isinstance(content,dict) else content.decode('utf-8'))))
    report={'version':actual_version,'check_suite':'stage4_compatible','date':core.now(),'checks':checks,'passed':sum(x['passed'] for x in checks),
            'total':len(checks),'local_run_id':local['id'],'live_run_id':live['id'] if live else None,'valuation_id':v['id'],'reused_model_record':bool(args.run_id)}
    (core.DATA/'stage4_http.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
