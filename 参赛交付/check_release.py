"""Check staged public files, credential exclusion and exact original source bytes."""
import hashlib
import io
import json
import os
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def main():
    names=[n for n in git('ls-files','-z').decode('utf-8').split('\0') if n]
    allowed=['.gitignore','.gitattributes','README.md','NOTICE.md']
    assert all(n in allowed or n.startswith(('知衡初版/','知衡数据资料/','参赛交付/','output/pdf/','third_party_licenses/')) for n in names)
    assert not any('/data/' in n or '/exports/' in n or '/__pycache__/' in n or
                   Path(n).suffix.lower() in ['.sqlite3','.db','.pyc','.log'] or
                   Path(n).name=='config.local.json' or
                   (Path(n).name.startswith('.env') and Path(n).name!='.env.example') for n in names)
    assert not any(re.search(r'报名|身份证|学生证|护照|passport|id.?card', n, re.I) for n in names)
    keys=[os.environ.get(k,'') for k in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','DASHSCOPE_API_KEY','ZHIHENG_API_KEY','GH_TOKEN','GITHUB_TOKEN']]
    pattern=re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{20,})\b')
    for name in names:
        data=git('show',':'+name)
        assert not pattern.search(data),'Possible credential in '+name
        assert not any(len(k)>=10 and k.encode() in data for k in keys),'Credential in '+name
        assert len(data)<100*1024*1024,'File too large: '+name
    dataset=ROOT/'知衡数据资料/家电行业_截至2026-10-06'
    manifest_path='知衡数据资料/家电行业_截至2026-10-06/00_来源与索引/资料总索引.json'
    manifest=json.loads(git('show',':'+manifest_path).decode('utf-8'))
    for source in manifest['sources']:
        file=dataset/source['relative_path'];relative=file.relative_to(ROOT).as_posix()
        assert hashlib.sha256(file.read_bytes()).hexdigest()==source['sha256'],'Working source changed: '+source['source_id']
        assert hashlib.sha256(git('show',':'+relative)).hexdigest()==source['sha256'],'Staged source changed: '+source['source_id']
    demo_count=0
    definitions=[name for name in names if name.startswith('知衡初版/demo/sources') and name.endswith('.json')]
    for definition in definitions:
        for source in json.loads(git('show',':'+definition).decode('utf-8')):
            name='知衡初版/demo/'+source['filename']
            assert hashlib.sha256(git('show',':'+name)).hexdigest()==source['sha256'],'Demo original changed: '+name
            demo_count+=1
    records=[name for name in names if (name.startswith('知衡初版/demo/') and name.endswith('.json')) or ('验收记录' in name and name.endswith('.json'))]
    for name in records:
        text=git('show',':'+name).decode('utf-8')
        assert 'Administrator' not in text and not re.search(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]',text),'Machine path in public record: '+name
    parent_path='知衡初版/demo/case_model_v05.json'
    revision_path='知衡初版/demo/case_logic_v05.json'
    parent=json.loads(git('show',':'+parent_path).decode('utf-8'))
    revision=json.loads(git('show',':'+revision_path).decode('utf-8'))
    assert revision['mode']=='development_revision' and revision['model_calls']==[]
    assert revision['revision_provenance']['parent_run_id']==parent['id']
    assert revision['revision_provenance']['parent_snapshot_sha256']==hashlib.sha256(git('show',':'+parent_path)).hexdigest()
    assert revision['revision_provenance']['human_financial_review_completed'] is False
    assert revision['valuation']['pe_basis']['reviewed'] is False
    assert revision['decision']['status']=='暂缓投资判断'
    license_manifest=json.loads(git('show',':third_party_licenses/manifest.json').decode('utf-8'))
    for entry in license_manifest['files']:
        name='third_party_licenses/'+entry['file']
        assert hashlib.sha256(git('show',':'+name)).hexdigest()==entry['sha256'],'License copy changed: '+name
    from pypdf import PdfReader
    for name,count in [('知衡_项目计划书.pdf',8),('知衡_演示与答辩手册.pdf',6)]:
        pdf=PdfReader(io.BytesIO(git('show',':output/pdf/'+name)));assert len(pdf.pages)==count
        assert all((p.extract_text() or '').strip() for p in pdf.pages)
    print(json.dumps({'staged_files':len(names),'original_source_hashes':len(manifest['sources']),
                      'public_demo_original_entries':demo_count,'demo_source_definitions':len(definitions),
                      'public_record_path_scan':len(records),'license_copies':len(license_manifest['files']),
                      'credential_check':'passed','local_runtime_exclusion':'passed',
                      'logic_revision_provenance':'passed','pdf_page_counts':[8,6]},ensure_ascii=False))

if __name__=='__main__':main()
