"""Check staged public files, credential exclusion and exact original source bytes."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def main():
    names=[n for n in git('ls-files','-z').decode('utf-8').split('\0') if n]
    allowed=['.gitignore','.gitattributes','README.md']
    assert all(n in allowed or n.startswith(('知衡初版/','知衡数据资料/','参赛交付/','output/pdf/')) for n in names)
    assert not any('/data/' in n or '/exports/' in n or '/__pycache__/' in n or Path(n).name.startswith('.env') for n in names)
    keys=[os.environ.get(k,'') for k in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','DASHSCOPE_API_KEY','ZHIHENG_API_KEY','GH_TOKEN','GITHUB_TOKEN']]
    pattern=re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{20,})\b')
    for name in names:
        data=git('show',':'+name)
        assert not pattern.search(data),'Possible credential in '+name
        assert not any(len(k)>=10 and k.encode() in data for k in keys),'Credential in '+name
        assert len(data)<100*1024*1024,'File too large: '+name
    dataset=ROOT/'知衡数据资料/家电行业_截至2026-10-06'
    manifest=json.loads((dataset/'00_来源与索引/资料总索引.json').read_text('utf-8'))
    for source in manifest['sources']:
        file=dataset/source['relative_path'];relative=file.relative_to(ROOT).as_posix()
        assert hashlib.sha256(file.read_bytes()).hexdigest()==source['sha256'],'Working source changed: '+source['source_id']
        assert hashlib.sha256(git('show',':'+relative)).hexdigest()==source['sha256'],'Staged source changed: '+source['source_id']
    app=ROOT/'知衡初版'
    for source in json.loads((app/'demo/sources.json').read_text('utf-8')):
        name='知衡初版/demo/'+source['filename']
        assert hashlib.sha256(git('show',':'+name)).hexdigest()==source['sha256'],'Demo original changed'
    for name in ['知衡初版/demo/case_model.json','知衡初版/V0.4验收记录.json']:
        text=git('show',':'+name).decode('utf-8')
        assert 'Administrator' not in text and not re.search(r'[A-Z]:[\\/]',text),'Machine path in public record'
    from pypdf import PdfReader
    for name,count in [('知衡_项目计划书.pdf',8),('知衡_演示与答辩手册.pdf',6)]:
        pdf=PdfReader(ROOT/'output/pdf'/name);assert len(pdf.pages)==count
        assert all((p.extract_text() or '').strip() for p in pdf.pages)
    print(json.dumps({'staged_files':len(names),'original_source_hashes':len(manifest['sources']),'public_demo_originals':1,'credential_check':'passed','local_runtime_exclusion':'passed','pdf_page_counts':[8,6]},ensure_ascii=False))

if __name__=='__main__':main()
