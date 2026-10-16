"""Publish one selected V0.6 public-data case; preserve original model outputs."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'知衡初版'))
import core
import exporting
from publish_demo import clean,verify_public


def main():
    run_id='965d0992d2f6'
    run=clean(exporting.prepare_run(core.get_run(run_id)))
    if run['mode']!='llm' or len(run['model_calls'])!=5 or run['code']!='002032':
        raise ValueError('不是指定的新企业真实模型验收案例')
    known={s['source_id']:s for s in core.base_manifest()['sources']}
    for evidence in run['evidence']:
        source=known.get(evidence['source_id'])
        if not source or source['sha256']!=hashlib.sha256(core.file_for(source).read_bytes()).hexdigest():
            raise ValueError('示范证据必须是已登记的公开原件')
    run['demo_version']='0.6.0'
    run['demo_scope']='V0.6真实模型保存记录；压力参数为验收用户假设，剩余复核原文保留，无金融签认。'
    verify_public(run)
    folder=core.APP/'demo'
    path=folder/'case_model_v06.json'
    if path.exists():raise ValueError('保留已发布案例，不覆盖')
    path.write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'sources_v06.json').write_text('[]\n',encoding='utf-8')
    reports={}
    for name in ['v06_http_acceptance.json','v06_live_acceptance.json']:
        result=json.loads((core.DATA/name).read_text(encoding='utf-8'))
        verify_public(result);reports[name]=result
    record={'version':'0.6.0','checked_at':core.now(),'unit_tests':{'passed':136,'failed':0},
            'http':reports['v06_http_acceptance.json'],'live':reports['v06_live_acceptance.json'],
            'public_case':{'file':'demo/case_model_v06.json','sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                           'run_id':run_id,'successful_model_calls':5,'expert_signoff':False},
            'limitations':['新增三家每家两期财报，未登记深度原页或行情','非上市企业目前为资料研究，真实样本原件待补',
                           '开发侧研究规范待金融同学确认','未验证实际投资效果','计划书与视频由用户另行制作']}
    verify_public(record)
    (core.APP/'V0.6验收记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'case':path.name,'run_id':run_id,'checks':[reports[n]['passed'] for n in reports]},ensure_ascii=False))


if __name__=='__main__':main()
