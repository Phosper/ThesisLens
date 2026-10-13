"""Prepare explicitly selected public model snapshots; never export local databases."""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'知衡初版'))
import core
import decision
import exporting


def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ['markdown','human_review']}
    if isinstance(value,list):return [clean(v) for v in value]
    if isinstance(value,str):
        for prefix in [str(ROOT),ROOT.as_posix()]:
            value=value.replace(prefix,'ThesisLens')
        return value
    return value


def verify_public(value):
    text=json.dumps(value,ensure_ascii=False)
    if re.search(r'\b[A-Z]:[\\/]',text) or 'Administrator' in text:raise ValueError('公开快照仍含本机路径，未写入')
    if re.search(r'\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{40,})\b',text):raise ValueError('疑似凭据，未写入')
    for name in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','DASHSCOPE_API_KEY','ZHIHENG_API_KEY','GH_TOKEN','GITHUB_TOKEN']:
        key=os.environ.get(name,'')
        if len(key)>=10 and key in text:raise ValueError('凭据不应进入示范，未写入')


def publish(run_id,first_run_id=None,audit_path=None,post_fix_retested=False):
    folder=ROOT/'知衡初版/demo';folder.mkdir(exist_ok=True)
    run=clean(exporting.prepare_run(core.get_run(run_id)));verify_public(run)
    if run.get('mode')!='llm' or not run.get('decision'):raise ValueError('应选择含新版判断的真实模型记录')
    if post_fix_retested and (not run.get('audit',{}).get('available') or not run.get('audit',{}).get('model_attempts') or run_id==first_run_id):
        raise ValueError('修补后复测必须选择带新审计尝试的不同真实运行，不可给旧实录加标签')
    run['demo_version']='0.5.0'
    run['demo_scope']='竞赛演示输入与保存的真实模型结果；未作金融专家签认，未复写原模型输出。'
    dataset=ROOT/'知衡数据资料/家电行业_截至2026-10-06'
    original_ids={s['source_id'] for s in json.loads((dataset/'00_来源与索引/资料总索引.json').read_text('utf-8'))['sources']}
    extras=[]
    existing={row['source_id']:row for row in json.loads((folder/'sources.json').read_text('utf-8'))}
    copies=[]
    for sid in sorted({e['source_id'] for e in run['evidence']}-original_ids):
        source=core.source(sid);raw=core.file_for(source).read_bytes()
        official=source.get('official_metadata') or {}
        if not official or not str(official.get('detail_url','')).startswith('https://'):
            raise ValueError('新增来源缺少官方登记，未自动进入公开体验包')
        if sid in existing:
            entry=existing[sid]
            if entry['sha256']!=hashlib.sha256(raw).hexdigest():raise ValueError('已发布示范原件摘要不同')
            if not (folder/entry['filename']).is_file():raise ValueError('已发布示范原件缺失')
            extras.append(entry)
            continue
        filename='v05_'+hashlib.sha256(raw).hexdigest()[:12]+'.pdf'
        copies.append((filename,raw))
        body={'filename':source.get('original_filename') or filename,'title':source['title'],'publication_date':source['publication_date'],
            'code':source.get('code',''),'publisher':source.get('publisher',''),'period':source.get('report_period','')}
        extras.append({'filename':filename,'source_id':sid,'sha256':hashlib.sha256(raw).hexdigest(),'body':body,'official_metadata':source['official_metadata']})
    audit=None
    if audit_path:
        audit=clean(json.loads(Path(audit_path).read_text('utf-8')));verify_public(audit)
        key='postrun_development_audit' if run_id==audit['run_id'] else 'previous_case_development_audit'
        run[key]={'run_id':audit['run_id'],'finding_count':len(audit['findings']),
            'record':'demo/v05_first_case_review.json','status':'开发复查意见；尚非金融专家签认'}
        if run_id==audit['run_id']:
            run.setdefault('warnings',[]).insert(0,'本例为补强规则与提示词前的真实模型实录，开发复查发现8项问题，尚未完成修订后真实模型复测；请结合复查意见核验，不作为已核验投资备忘录。')
        else:
            run.setdefault('warnings',[]).insert(0,'本例为补强后的真实模型保存记录；前次案例的开发复查另行保留。当前结果仍需金融人工复核，未作专家签认。')
    run['decision_at_generation']=run.get('decision_at_generation') or run['decision']
    run['comparison_checks']=decision.comparison_checks(run)
    run['decision']=decision.build(run)
    verify_public(run)
    for filename,raw in copies:(folder/filename).write_bytes(raw)
    (folder/'case_model_v05.json').write_text(json.dumps(run,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'sources_v05.json').write_text(json.dumps(extras,ensure_ascii=False,indent=2),encoding='utf-8')
    if first_run_id:
        first=clean(core.get_run(first_run_id));verify_public(first)
        (folder/'case_model_v05_first.json').write_text(json.dumps(first,ensure_ascii=False,indent=2),encoding='utf-8')
    if audit is not None:
        (folder/'v05_first_case_review.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    record={'version':'0.5.0','run_id':run_id,'first_run_id':first_run_id,'public_extra_sources':len(extras),
        'successful_model_calls':len(run['model_calls']),'evidence_count':len(run['evidence']),
        'post_fix_real_model_retested':bool(post_fix_retested),'previous_case_development_audit_findings':len(audit['findings']) if audit else None,
        'scope':'仅选定公开资料与模型快照，不含本机全部数据库、私人核验备注、密钥或报名证明。'}
    (folder/'v05_demo_metadata.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return record


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--first-run-id');p.add_argument('--audit-path');p.add_argument('--post-fix-retested',action='store_true');a=p.parse_args()
    print(json.dumps(publish(a.run_id,a.first_run_id,a.audit_path,a.post_fix_retested),ensure_ascii=False))
