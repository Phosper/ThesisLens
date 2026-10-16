"""Bounded real-model V0.5 acceptance; one primary case, optional saved-case checks."""
import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
import core


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--run-id')
    args=parser.parse_args()
    if bool(args.live)==bool(args.run_id):parser.error('Choose --live or --run-id')
    def request(path,body=None):
        data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
        req=urllib.request.Request(args.base_url+path,data=data,headers={'Content-Type':'application/json'} if data else {})
        try:
            with urllib.request.urlopen(req,timeout=25) as response:
                raw=response.read()
                return json.loads(raw) if response.headers.get('Content-Type','').startswith('application/json') else raw
        except urllib.error.HTTPError as exc:raise ValueError('本机服务HTTP '+str(exc.code)) from None
    status=request('/api/status')
    if status['version'] not in ['0.5.0','0.6.0']:raise ValueError('本机服务不是V0.5或V0.6')
    if args.live:
        if not status['model']['configured']:raise ValueError('模型未配置，未发起真实调用')
        ctx=request('/api/valuation/context?code=000333&cutoff=2026-10-06');shares=ctx['reported_shares']
        val=request('/api/valuation',{'code':'000333','cutoff':'2026-10-06','assumptions':{
            'pe_low':'8','pe_base':'12','pe_high':'16','earnings_change_pct':'0',
            'shares_yi':shares['total_yi'],'shares_source_id':shares['source_id'],
            'pe_basis':'竞赛流程演示的压力情景：8/12/16倍尚无核验完成的历史与同行估值依据，不能作为市场共识或投资评级。',
            'pe_basis_reviewed':False,'dividend_per_share_yuan':'0','fees_pct':'0.2'}})
        body={'code':'000333','cutoff':'2026-10-06','mode':'llm',
            'question':'请为美的集团2026年上半年形成买方投资备忘录，围绕增长与利润质量、应收与存货、海外业务和同行对照，说明进一步研究的依据、关键风险、论据失效条件和持续跟踪指标。结合所附估值，说明什么条件满足后才可以形成投资判断。',
            'options':{'semantic_retrieval':True,'auto_revise':True,'valuation_id':val['id'],
                'investment_profile':{'goal':'竞赛演示假设：评估投资价值及下行情景，投入与损失约束均为示例输入',
                    'horizon_months':12,'budget_yuan':'100000','max_loss_pct':'10'}}}
        job=request('/api/research',body)
        print(json.dumps({'job_id':job['job_id'],'valuation_id':val['id'],'model':status['model']['model']},ensure_ascii=False),flush=True)
        (core.DATA/'v05-live-job.json').write_text(json.dumps({'job_id':job['job_id'],'valuation_id':val['id']},ensure_ascii=False),encoding='utf-8')
        deadline=time.monotonic()+600;last_step=None
        while time.monotonic()<deadline:
            current=request('/api/jobs/'+job['job_id'])
            trace=current.get('trace',[])
            if trace and trace[-1]['title']!=last_step:
                last_step=trace[-1]['title'];print(json.dumps({'step':last_step,'elapsed':trace[-1]['elapsed_seconds']},ensure_ascii=False),flush=True)
            if current['status']=='failed':raise ValueError(current['error'])
            if current['status']=='complete':run_id=current['run_id'];break
            time.sleep(1)
        else:raise TimeoutError('真实研究仍在运行，保留任务编号供复查，不重复提交')
    else:run_id=args.run_id
    run=request('/api/runs/'+run_id)
    checks=[]
    def check(name,ok):
        checks.append({'name':name,'passed':bool(ok)})
        if not ok:raise AssertionError(name)
    check('真实模型输出与调用留痕',run['mode']=='llm' and len(run['model_calls'])>=3)
    check('研究截止前原件及日期',all(e['publication_date']<=run['cutoff'] for e in run['evidence']))
    allowed={e['citation'] for e in run['evidence']}
    check('E编号均对应保存证据',all(c in allowed for key in ['thesis','risks','invalidation','monitoring','open_questions'] for r in run['draft'][key] for c in r['citations']))
    check('判断按未核验依据保持暂缓',run['decision']['status']=='暂缓投资判断' and run['valuation']['pe_basis']['reviewed'] is False)
    check('规则意见可回看且生成时判断留存','comparison_checks' in run and run.get('decision_at_generation') is not None)
    check('原件股数与保存日期参考PE完整',run['valuation']['market_pe']['available'] and run['valuation']['market_pe']['price_date']=='2026-09-30')
    check('未将示例损失上限作为保证',any('超出' in x for x in run['decision']['missing']))
    for view in ['brief','full']:
        for fmt in ['md','html']:
            exported=request(f'/api/runs/{run_id}/export?format={fmt}&view={view}').decode('utf-8')
            check(view+'/'+fmt+'保留暂缓与引用及假设','暂缓投资判断' in exported and 'E1' in exported and '2026-09-30' in exported)
    json_export=request(f'/api/runs/{run_id}/export?format=json')
    check('完整JSON导出保留当前与生成时判断',json_export==run)
    issues=run['review'].get('issues',[])
    counts={s:sum(i.get('severity')==s for i in issues) for s in ['高','中','低']}
    report={'version':'0.5.0','checked_at':core.now(),'run_id':run_id,'valuation_id':run['valuation']['id'],
        'duration_seconds':run['duration_seconds'],'successful_model_calls':len(run['model_calls']),
        'model':run['model_calls'][-1]['model'],'evidence_count':len(run['evidence']),'trace_steps':len(run['trace']),
        'retrieval':run.get('retrieval'),'remaining_review_counts':counts,'rule_checks_count':len(run['comparison_checks']),
        'first_rule_checks_count':len(run.get('previous_comparison_checks',[])),
        'decision_status':run['decision']['status'],'checks':checks,'model_record_reused':bool(args.run_id),
        'limitations':['示例期限、预算、损失和股利费率是竞赛演示输入','PE倍数依据未完成金融核验','程序验收不代表事实准确率或专家签认','成功日志数不包括无日志失败请求的账单次数']}
    output=core.DATA/'v05_live_acceptance.json';output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['run_id','duration_seconds','successful_model_calls','evidence_count','trace_steps','remaining_review_counts','rule_checks_count','decision_status']},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
