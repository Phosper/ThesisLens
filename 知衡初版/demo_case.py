"""Restore the published, historical model example without sending a model request."""
import argparse
import base64
import hashlib
import json
import uuid
import core
import knowledge
import workbench
import research
import audit

@audit.operation('demo_restore')
def restore(version='latest'):
    folder=core.APP/'demo'
    if version=='latest':version='v07' if (folder/'case_model_v07.json').is_file() else 'v05' if (folder/'case_model_v05.json').is_file() else 'v04'
    if version not in ['v04','v05','v05_logic','v06','v07','v07_boss','v07_hisense']:raise ValueError('请选择已保存的示范版本')
    suffix='_v07' if version.startswith('v07') else '_v06' if version=='v06' else '_v05' if version in ['v05','v05_logic'] else ''
    for entry in json.loads(audit.read_text(folder/f'sources{suffix}.json',purpose='demo_sources_read')):
        raw=audit.read_bytes(folder/entry['filename'],source_id=entry['source_id'],purpose='demo_original_read')
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('示范原件摘要不匹配')
        result=knowledge.import_document(dict(entry['body'],content_base64=base64.b64encode(raw).decode('ascii')),
                                         verified_metadata=entry.get('official_metadata'))
        if result['source_id']!=entry['source_id']:raise ValueError('示范来源编号不一致')
    case_path=folder/('case_logic_v05.json' if version=='v05_logic' else f'case_model_{version}.json' if version.startswith('v07') else f'case_model{suffix}.json')
    run=json.loads(audit.read_text(case_path,purpose='demo_snapshot_read'))
    logic=version=='v05_logic'
    original={'id':run['id'],'created_at':run['created_at'],'version':'0.5.0-logic1' if logic else ('0.7.0' if version.startswith('v07') else '0.6.0' if version=='v06' else '0.5.0' if version=='v05' else '0.4.0'),
              'note':'开发侧逻辑修订示例，未新增模型研究或模型复核；父记录原文另行保留，待金融核验。' if logic else '历史模型输出，未发起新的模型请求；保留复核问题，待团队复审。'}
    run.update(id=audit.current()['run_id'],created_at=core.now(),demo_original=original,
               mode_label='开发侧逻辑修订示范 · 尚待金融核验' if logic else '历史大模型示范 · '+('V0.7保存记录' if version.startswith('v07') else 'V0.6保存记录' if version=='v06' else 'V0.5保存记录' if version=='v05' else 'V0.4保存记录'))
    if run.get('valuation'):
        v=run['valuation']
        with workbench.connect() as db:db.execute('INSERT OR IGNORE INTO valuations VALUES (?,?,?)',(v['id'],v['created_at'],core.json_dump(v)))
    run['warnings'].insert(0,original['note'])
    run['markdown']=research.markdown(run);core.save_run(run)
    return {'run_id':run['id'],'original_run_id':original['id'],'version':original['version'],'note':original['note']}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--restore',action='store_true');parser.add_argument('--version',choices=['latest','v04','v05','v05_logic','v06','v07','v07_boss','v07_hisense'],default='latest');args=parser.parse_args()
    if not args.restore:parser.error('Use --restore to add the historical example to local records.')
    core.ensure_index();print(json.dumps(restore(args.version),ensure_ascii=False))
