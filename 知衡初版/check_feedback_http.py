"""Exercise V0.5 local workflows without external requests or model calls."""
import argparse
import json
import time
import urllib.error
import urllib.request
from decimal import Decimal
import core


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    args=parser.parse_args();checks=[]

    def request(path,body=None):
        payload=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
        req=urllib.request.Request(args.base_url+path,data=payload,headers={'Content-Type':'application/json'} if payload else {})
        try:
            with urllib.request.urlopen(req,timeout=20) as response:return response.status,response.headers,response.read()
        except urllib.error.HTTPError as exc:return exc.code,exc.headers,exc.read()

    def get(path):
        code,_,data=request(path)
        if code!=200:raise AssertionError(path+': '+data.decode('utf-8'))
        return json.loads(data)

    def post(path,body,expected=200):
        code,_,data=request(path,body)
        if code!=expected:raise AssertionError(path+': '+data.decode('utf-8'))
        return json.loads(data)

    def check(label,condition):
        if not condition:raise AssertionError(label)
        checks.append(label)

    def wait(job):
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            result=get('/api/jobs/'+job['job_id'])
            if result['status']!='running':return result
            time.sleep(.3)
        raise AssertionError('本机任务未按时完成')

    status=get('/api/status');check('V0.5及后续正式版可访问',status['version'] in ['0.5.0','0.6.0'])
    context=get('/api/valuation/context?code=000333&cutoff=2026-10-06')
    check('未选股数不会自动产生PE',not context['market_pe']['available'])
    shares=context['reported_shares']
    assumptions={'shares_yi':shares['total_yi'],'shares_source_id':shares['source_id'],
        'pe_basis':'V0.5验收演示：沿用默认倍数，历史与同行依据尚待补核。',
        'pe_basis_reviewed':False,'dividend_per_share_yuan':'0','fees_pct':'0'}
    val=post('/api/valuation',{'code':'000333','cutoff':'2026-10-06','assumptions':assumptions})
    check('保存日期A股参考PE按原值计算',val['market_pe']['available'] and abs(Decimal(val['market_pe']['pe'])-Decimal('13.7419392942451'))<Decimal('.0000001'))
    check('原件股数来源与A股价格类别保留',val['assumptions']['shares_source_id']==shares['source_id'] and val['market_pe']['price_share_class']=='A')
    check('未签认倍数保持待核验',val['pe_basis']['status']=='unreviewed' and val['pe_basis']['reviewed'] is False)
    check('明确零股利费用可计算总回报',all(s['price_return_pct']==s['total_return_pct'] for s in val['pe_scenarios']))
    post('/api/valuation',{'assumptions':{'pe_basis_reviewed':'true'}},expected=400)
    checks.append('字符串不能冒充人工复核声明')
    invalid=wait(post('/api/research',{'question':'验收无效期限','mode':'local','options':{'investment_profile':{'horizon_months':1.5}}},expected=202))
    check('无效期限在生成前拒绝',invalid['status']=='failed' and '整数' in invalid['error'])
    job=post('/api/research',{'code':'000333','cutoff':'2026-10-06','question':'V0.5验收演示：美的2026年上半年经营表现与风险核验',
        'mode':'local','options':{'valuation_id':val['id'],'investment_profile':{'goal':'验收演示：评估投资价值与下行风险','horizon_months':12,'budget_yuan':'100000','max_loss_pct':'10'}}},expected=202)
    complete=wait(job);check('资料模式新研究完成',complete['status']=='complete')
    run_id=complete['run_id'];run=get('/api/runs/'+run_id)
    check('研究约束保存且不调用模型',run['investment_profile']['max_loss_pct']=='10' and not run['model_calls'])
    check('未决依据和情景压力使判断暂缓',run['decision']['status']=='暂缓投资判断' and any('超出' in item for item in run['decision']['missing']))
    check('新研究不冒充历史兼容视图',not run['decision']['review_status']['compatibility_view'])
    for view in ['brief','full']:
        for fmt in ['md','html']:
            code,headers,data=request(f'/api/runs/{run_id}/export?format={fmt}&view={view}')
            text=data.decode('utf-8')
            check(f'{view}/{fmt}导出保留判断风险约束',code==200 and 'attachment' in headers.get('Content-Disposition','') and '暂缓投资判断' in text and '10%' in text)
            if fmt=='html':check(view+' HTML保留原件证据引用','ref-E1' in text)
        code,_,data=request(f'/api/runs/{run_id}/print?view={view}')
        check(view+'打印页可用',code==200 and 'window.print()' in data.decode('utf-8'))
    code,_,data=request(f'/api/runs/{run_id}/export?format=json&view=brief')
    check('JSON始终保留完整快照与当前判断',code==200 and json.loads(data)==run)
    code,_,_=request(f'/api/runs/{run_id}/export?format=md&view=invalid')
    check('无效展示参数拒绝',code==400)
    note='V0.5页面验收：本项可回看原页，财务支持关系仍待金融同学复核。'
    post(f'/api/runs/{run_id}/annotations',{'claim_id':'thesis:0','state':'pending','note':note})
    refreshed=get('/api/runs/'+run_id)
    check('保存待核验备注后读取最新记录',any(n['note']==note and n['state']=='pending' for n in refreshed['human_review']['notes']))
    check('人工备注不会覆盖生成时判断',refreshed['decision_at_generation']==run['decision_at_generation'])
    history=get('/api/runs')['data']
    old=next((r for r in history if r['id']=='8d74405af148'),None)
    if old:
        saved=get('/api/runs/'+old['id'])
        check('原核验案例明确标历史补充且保留高风险',saved['decision']['review_status']['compatibility_view'] and saved['comparison_checks'] and saved['decision']['status']=='暂缓投资判断')
    report={'version':status['version'],'checked_at':core.now(),'run_id':run_id,'valuation_id':val['id'],
        'checks':checks,'model_calls':0,'scope':'本机历史资料、规则研究和导出验收；未提交金融专家核验或发起真实模型调用。'}
    (core.DATA/'feedback-http-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'检查数':len(checks),'结果':'全部通过','研究编号':run_id},ensure_ascii=False))


if __name__=='__main__':main()
