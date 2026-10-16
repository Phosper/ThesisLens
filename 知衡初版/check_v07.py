"""Bounded V0.7 end-to-end checks. Private fixtures require an empty isolated install."""
import argparse
from decimal import Decimal
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import core


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8765')
    parser.add_argument('--live',action='store_true',help='Three public extension cases, at most fifteen successful model calls')
    parser.add_argument('--live-codes',nargs='+',choices=['002032','002508','600060'],default=['002032','002508','600060'])
    parser.add_argument('--private-test',action='store_true',help='Synthetic fixture in an empty isolated install only')
    args=parser.parse_args()
    checks=[];cases=[]
    def request(path,body=None,expected=200):
        payload=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
        req=urllib.request.Request(args.base_url+path,data=payload,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=30) as response:status=response.status;raw=response.read();kind=response.headers.get('Content-Type','')
        except urllib.error.HTTPError as error:status=error.code;raw=error.read();kind=error.headers.get('Content-Type','')
        if status!=expected:raise AssertionError(path+' returned '+str(status)+': '+raw.decode('utf-8')[:400])
        return json.loads(raw) if kind.startswith('application/json') else raw
    def check(name,ok):
        checks.append({'name':name,'passed':bool(ok)})
        if not ok:raise AssertionError(name)
    def wait(job):
        deadline=time.monotonic()+660;last=None
        while time.monotonic()<deadline:
            row=request('/api/jobs/'+job['job_id'])
            trace=row.get('trace',[])
            if trace and trace[-1]['title']!=last:
                last=trace[-1]['title'];print(json.dumps({'job':job['job_id'],'step':last},ensure_ascii=False),flush=True)
            if row['status']=='failed':raise AssertionError(row['error'])
            if row['status']=='complete':return row
            time.sleep(.5)
        raise TimeoutError('任务仍在运行，保留编号，不重复提交')
    def run(body):
        complete=wait(request('/api/research',body,202))
        result=request('/api/runs/'+complete['run_id'])
        check(result['company']+'披露时点',all(e['publication_date']<=result['cutoff'] for e in result['evidence']))
        check(result['company']+'研究要求已保存',result['research_requirements']['company_profile']['code']==result['code'] and bool(result['research_coverage']['rows']))
        check(result['company']+'方法进入检索',any(t['tool']=='company_method_search' for t in result['tool_calls']))
        check(result['company']+'研究章节完整',any(result['draft'][key] for key in ['thesis','risks','invalidation','monitoring','open_questions']))
        for view in ['brief','full']:
            for fmt in ['md','html']:
                text=request(f"/api/runs/{result['id']}/export?format={fmt}&view={view}").decode('utf-8')
                check(result['company']+view+'/'+fmt+'需求与缺口导出','研究要求与数据覆盖' in text and '待金融同学确认' in text)
                if result.get('valuation',{}):check(view+'/'+fmt+'海外毛利情景导出','海外经营压力情景' in text and '毛利变化' in text)
                if result['decision'].get('document_mode'):check('非上市导出不套用交易约束 '+view+'/'+fmt,'投入上限：' not in text and '用户假设持有期' not in text)
        check('JSON保留完整研究快照',request(f"/api/runs/{result['id']}/export?format=json")==result)
        cases.append({'code':result['code'],'company':result['company'],'mode':result['mode'],'run_id':result['id'],
                      'evidence_count':len(result['evidence']),'model_calls':len(result['model_calls']),
                      'review_counts':{s:sum(i.get('severity')==s for i in result['review']['issues']) for s in ['高','中','低']},
                      'decision':result['decision']['status']})
        return result
    status=request('/api/status');check('V0.7服务',status['version']=='0.7.0')
    if args.live and not status['model']['configured']:raise ValueError('模型未配置，未发起真实调用')
    if args.private_test:
        check('合成测试仅用于空安装',not request('/api/runs')['data'] and len(status['companies'])==6)
        private=request('/api/companies',{'name':'验收合成企业（非真实样本）','listed':False,'note':'仅验证程序边界，不计入研究样本。'})
        code=private['code']
        job=request('/api/research',{'code':code,'mode':'local','question':'检查业务结构与风险资料'},202)
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            row=request('/api/jobs/'+job['job_id'])
            if row['status']!='running':break
            time.sleep(.3)
        check('缺本企业原文不借用行业生成研究',row['status']=='failed' and '本企业' in row['error'])
        source=wait(request('/api/knowledge/import',{'code':code,'publication_date':'2026-10-01','title':'程序验收合成业务资料（非真实样本）',
            'text':'这是合成的程序测试材料，不代表真实企业。该测试企业的主营业务为厨房设备研发与销售，渠道包括经销商和直营。测试材料描述原材料采购、客户集中与经营信息缺口；没有提供财务报表、归母利润、股票报价和投资收益。'},202))
        check('合成原文导入成功',source['status']=='complete')
        result=run({'code':code,'cutoff':'2026-10-06','mode':'local','question':'业务结构、渠道和经营风险有哪些原文？'})
        check('非上市财务与交易分支隔离',not result['metrics'] and not result['valuation'] and result['decision']['document_mode'] and not result['decision']['return_scenarios'])
        check('合成材料不转成经营论据',not result['draft']['thesis'] and bool(result['draft']['open_questions']))
        request('/api/valuation/context?code='+code,expected=400)
        checks.append({'name':'非上市PE拒绝','passed':True})
    else:
        registry=request('/api/companies?cutoff=2026-10-06')['data']
        check('六家真实企业及报告覆盖',len(registry)==6 and {r['reports'] for r in registry}=={2,17})
        for code in ['002032','002508','600060']:
            history=request('/api/financial/history?'+urllib.parse.urlencode({'code':code,'cutoff':'2026-10-06'}))['data']
            check(code+'四项流量与原页',len(history)==2 and all(all(k in h['fields'] for k in ['revenue','profit','core_profit','cashflow']) for h in history))
            ctx=request('/api/valuation/context?code='+code+'&cutoff=2026-10-06')
            check(code+'自身TTM、股份与保存日期报价',ctx['ttm_profit']['available'] and ctx['price'] and ctx['reported_shares'])
        assumption={'overseas_scenario_enabled':True,'overseas_revenue_change_pct':-10,'overseas_margin_change_pp':-1,
                    'overseas_scenario_basis':'验收压力假设：外销收入下降10%，海外毛利率下降1个百分点，未建宏观传导系数。',
                    'pe_basis':'验收用户示例倍数，未声称历史或同行合理区间。','pe_basis_reviewed':False}
        value=request('/api/valuation',{'code':'002032','cutoff':'2026-10-06','assumptions':assumption})
        baseline=request('/api/valuation',{'code':'002032','cutoff':'2026-10-06','assumptions':{k:v for k,v in assumption.items() if not k.startswith('overseas_')}})
        check('海外毛利计算与PE隔离',value['pe_scenarios']==baseline['pe_scenarios'] and Decimal(value['operating_scenario']['gross_profit_change_yuan'])<0)
        codes=args.live_codes if args.live else ['002032','002508','600060','000333']
        for code in codes:
            body={'code':code,'cutoff':'2026-10-06','mode':'llm' if args.live else 'local',
                  'question':status['companies'][code]+'2026年上半年经营、利润质量与现金流如何？结合业务结构和海外敞口分析风险，并明确反证与数据缺口。',
                  'options':{'auto_revise':True,'semantic_retrieval':False}}
            if code=='002032':body['options']['valuation_id']=value['id']
            result=run(body)
            if code=='002032':
                base=result['valuation']['operating_scenario']['baseline']
                check('压力基数原页进入证据',any(e['source_id']==base['source_id'] and e.get('pdf_page')==base['pdf_page'] for e in result['evidence']))
            check(code+'保持核验边界',result['decision']['status']=='暂缓投资判断' and result['financial_depth']['available'])
            if code!='000333':
                check(code+'已定位附注全部取回',all(r['status']=='已定位并取回原页' for r in result['disclosure_coverage']['rows']))
            check(code+'调用身份',3<=len(result['model_calls'])<=7 if args.live else not result['model_calls'])
    report={'version':'0.7.0','checked_at':core.now(),'live':args.live,'private_fixture':args.private_test,
            'checks':checks,'passed':len(checks),'cases':cases,'scope':'程序流程验收，不代表金融签认或投资效果验证。'}
    name='v07_live_acceptance.json' if args.live else 'v07_private_acceptance.json' if args.private_test else 'v07_http_acceptance.json'
    (core.DATA/name).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(checks),'passed':True,'cases':cases,'report':name},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
