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

def restore():
    folder=core.APP/'demo'
    for entry in json.loads((folder/'sources.json').read_text('utf-8')):
        raw=(folder/entry['filename']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('示范原件摘要不匹配')
        result=knowledge.import_document(dict(entry['body'],content_base64=base64.b64encode(raw).decode('ascii')),
                                         verified_metadata=entry.get('official_metadata'))
        if result['source_id']!=entry['source_id']:raise ValueError('示范来源编号不一致')
    run=json.loads((folder/'case_model.json').read_text('utf-8'))
    original={'id':run['id'],'created_at':run['created_at'],'note':'历史模型输出，未发起新的模型请求；保留复核问题，待团队复审。'}
    run.update(id=uuid.uuid4().hex[:12],created_at=core.now(),demo_original=original,mode_label='历史大模型示范 · 保存记录')
    if run.get('valuation'):
        v=run['valuation']
        with workbench.connect() as db:db.execute('INSERT OR IGNORE INTO valuations VALUES (?,?,?)',(v['id'],v['created_at'],core.json_dump(v)))
    run['warnings'].insert(0,original['note'])
    run['markdown']=research.markdown(run);core.save_run(run)
    return {'run_id':run['id'],'original_run_id':original['id'],'note':original['note']}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--restore',action='store_true');args=parser.parse_args()
    if not args.restore:parser.error('Use --restore to add the historical example to local records.')
    core.ensure_index();print(json.dumps(restore(),ensure_ascii=False))
