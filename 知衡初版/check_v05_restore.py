"""Verify the current public demo offline, using separate empty local databases."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import core
import knowledge
import workbench
import demo_case
import exporting
import decision


def main():
    folder=core.ROOT/'tmp/v05_restore'
    folder.mkdir(parents=True,exist_ok=True)
    install=core.DATA/'v05_restore'/core.now().replace(':','').replace('+','_')
    install.mkdir(parents=True)
    snapshot=core.APP/'demo/case_model_v05.json'
    original=json.loads(snapshot.read_text('utf-8'))
    report={'version':'0.5.0','checked_at':core.now(),'scope':'同机离线、隔离空数据库公开示范恢复；无服务重启、网络或模型请求。',
            'checks':[],'model_attempts':0,'network_attempts':0}
    def reject(kind):
        def fail(*args,**kwargs):
            report[kind+'_attempts']+=1
            raise AssertionError('Offline acceptance forbids '+kind+' requests')
        return fail
    def check(name,ok):
        report['checks'].append({'name':name,'passed':bool(ok)})
        if not ok:raise AssertionError(name)
    original_hash=hashlib.sha256(snapshot.read_bytes()).hexdigest()
    with patch.object(core,'DATA',install),patch.object(core,'RUNS',install/'runs.sqlite3'),patch.object(knowledge,'DB',install/'library.sqlite3'),patch.object(workbench,'DB',install/'workbench.sqlite3'),patch('model.complete',side_effect=reject('model')),patch('urllib.request.urlopen',side_effect=reject('network')):
        check('恢复前无研究、增量来源与人审数据库',not any(install.iterdir()))
        restored=demo_case.restore()
        saved=core.get_run(restored['run_id'])
        shown=exporting.prepare_run(saved)
        check('默认选择本次V0.5真实历史记录',restored['version']=='0.5.0' and restored['original_run_id']==original['id'])
        check('模型原文、复核及调用记录未被开发润色',all(saved[key]==original[key] for key in ['draft','review','model_calls','previous_review']))
        check('恢复未签认金融论据',not shown['human_review']['notes'] and shown['decision']['status']=='暂缓投资判断')
        historical_review=shown.get('previous_case_development_audit') or shown.get('postrun_development_audit') or {}
        check('前次开发审查与当前签认边界可见',historical_review.get('finding_count')==8 and any('专家签认' in warning or '尚未完成' in warning for warning in shown['warnings']))
        check('生成时判断与当前规则结果分别保留',shown['decision_at_generation']==original['decision_at_generation'] and shown['comparison_checks']==decision.comparison_checks(original))
        check('所需增量原件摘要一致',all(hashlib.sha256(core.file_for(source).read_bytes()).hexdigest()==source['sha256'] for source in knowledge.sources()))
        check('估值可恢复并保留未核验依据',workbench.get_valuation(saved['valuation']['id'])['pe_basis']['reviewed'] is False)
        for view in ['brief','full']:
            for fmt,render in [('md',exporting.memo_markdown),('html',exporting.memo_html)]:
                output=render(saved,view)
                check(view+'/'+fmt+'保留暂缓、原引用及核验边界','暂缓投资判断' in output and 'E1' in output and shown['warnings'][0] in output)
        check('读取与导出未改写公开原始模型记录',hashlib.sha256(snapshot.read_bytes()).hexdigest()==original_hash and core.get_run(restored['run_id'])['draft']==original['draft'])
        check('全程没有模型或网络请求',report['model_attempts']==0 and report['network_attempts']==0)
        report['restored']={'original_id':original['id'],'rule_checks_count':len(shown['comparison_checks']),
            'rule_checks_by_severity':{s:sum(row['severity']==s for row in shown['comparison_checks']) for s in ['高','中','低']},
            'decision_status':shown['decision']['status'],'successful_historical_model_calls':len(shown['model_calls'])}
    report.update(passed=len(report['checks']),failed=0,public_snapshot_sha256=original_hash)
    (folder/'验收记录.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['passed','failed','model_attempts','network_attempts','restored']},ensure_ascii=False))


if __name__=='__main__':main()
