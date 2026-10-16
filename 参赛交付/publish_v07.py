"""Preserve three real public-data model cases and the actual technical test record."""
import json,hashlib,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT/'知衡初版'))
import core,exporting
from publish_demo import clean,verify_public

def main():
    initial=json.loads((core.DATA/'v07_live_initial.json').read_text('utf-8'))
    final=json.loads((core.DATA/'v07_live_acceptance.json').read_text('utf-8'))
    by_code={r['code']:r for r in initial['cases']};by_code.update({r['code']:r for r in final['cases']})
    public=[]
    for code,suffix in [('002032','v07'),('002508','v07_boss'),('600060','v07_hisense')]:
        run=clean(exporting.prepare_run(core.get_run(by_code[code]['run_id'])))
        assert run['mode']=='llm' and 3<=len(run['model_calls'])<=7
        assert any(run['draft'][key] for key in ['thesis','risks','invalidation','monitoring','open_questions'])
        assert all(r['status']=='已定位并取回原页' for r in run['disclosure_coverage']['rows'])
        known={s['source_id']:s for s in core.base_manifest()['sources']}
        for e in run['evidence']:
            s=known[e['source_id']];assert hashlib.sha256(core.file_for(s).read_bytes()).hexdigest()==s['sha256']
            assert s['publication_date']<=run['cutoff']
        run.update(demo_version='0.7.0',demo_scope='真实模型保存原稿与复核；无金融签认，待人工判断。')
        verify_public(run)
        path=core.APP/'demo'/f'case_model_{suffix}.json'
        if path.exists():raise ValueError('保留已发布案例，不覆盖')
        path.write_text(json.dumps(run,ensure_ascii=False,indent=2),'utf-8')
        public.append(dict(by_code[code],file='demo/'+path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                           expert_signoff=False,rule_findings=len(run.get('comparison_checks',[]))))
    (core.APP/'demo/sources_v07.json').write_text('[]\n','utf-8')
    text=(core.DATA/'v07_unit_test_output.txt').read_text('utf-8');match=re.search(r'Ran (\d+) tests',text)
    assert match and text.strip().endswith('OK')
    http=json.loads((core.DATA/'v07_http_acceptance.json').read_text('utf-8'))
    retrieval=json.loads((core.DATA/'v07_retrieval_after.json').read_text('utf-8'))
    record={'version':'0.7.0','checked_at':core.now(),'unit_tests':{'passed':int(match[1]),'failed':0},
            'http':http,'live':final,'public_cases':public,'retrieval':retrieval,
            'initial_model_iteration':{'calls':sum(r['model_calls'] for r in initial['cases']),
                'cases':initial['cases'],'finding':'苏泊尔仅摘要空章节曾被接受；已加入空稿拦截和一次格式修复并复测。老板现金流调节跨页漏取已补，否定稳定结论误报已修正。'},
            'successful_model_calls_this_round':sum(r['model_calls'] for r in initial['cases'])+sum(r['model_calls'] for r in final['cases']),
            'dataset':{'sources':105,'reports':57,'pdf_pages':8440,'market_rows':6138,'depth_reports':12,'operating_baselines':5},
            'limitations':['开发标注12题不是独立盲测','真实模型仍有复核意见，未获金融签认','非上市企业真实样本原件待补',
                           '未验证实际投资效果','另一实体电脑及团队模型账号待验收','计划书和视频由用户制作']}
    verify_public(record)
    (core.APP/'V0.7验收记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'public_cases':public,'tests':int(match[1]),'http':http['passed'],'calls':record['successful_model_calls_this_round']},ensure_ascii=False))

if __name__=='__main__':main()
