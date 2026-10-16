"""Package current V0.6 app and public samples, excluding user-authored plans/video."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

import release_v05 as prior

ROOT=prior.ROOT
APP=prior.APP
DOCS={'README.md','V0.6升级与交接.md','技术报告.md','第三方与模型说明.md','publish_demo.py','publish_v06.py','release_v05.py','release_v06.py'}


def inventory():
    rows=[]
    for row in prior.inventory(False):
        path=Path(row['path'])
        if path.parts[0]=='output':continue
        if path.parts[0]=='参赛交付' and path.name not in DOCS:continue
        rows.append(row)
    present={row['path'] for row in rows}
    for name in DOCS:
        file=ROOT/'参赛交付'/name
        relative=file.relative_to(ROOT).as_posix()
        if file.is_file() and relative not in present:
            rows.append({'path':relative,'bytes':file.stat().st_size,'sha256':prior.digest(file)})
    # The prior packer only allows named app previews; include the new verified UI.
    for name in ['企业覆盖预览V0.6.jpg','海外压力预览V0.6.jpg']:
        file=APP/name
        if file.is_file():rows.append({'path':file.relative_to(ROOT).as_posix(),'bytes':file.stat().st_size,'sha256':prior.digest(file)})
    return sorted(rows,key=lambda r:r['path'])


def validate(rows):
    checks=[];paths={r['path'] for r in rows}
    def check(name,ok,detail=None):
        checks.append({'name':name,'passed':bool(ok),'detail':detail})
    required=['知衡初版/companies.json','知衡初版/company_sources.json','知衡初版/operating_baselines.json',
              '知衡初版/companies.py','知衡初版/operating_scenarios.py','知衡初版/research_requirements.py',
              '知衡初版/static/methods.js','知衡初版/启动知衡.cmd','知衡初版/V0.6验收记录.json',
              '知衡初版/demo/case_model_v06.json','参赛交付/V0.6升级与交接.md']
    check('最新程序、公开案例与验收记录齐全',all(name in paths for name in required))
    check('排除旧计划书、答辩PDF、视频及私人核验附件',not any('计划书' in p or p.startswith('output/') or Path(p).suffix.lower() in ['.mp4','.xlsx'] or p.endswith('build_video.py') for p in paths))
    check('排除本机数据库、密钥配置和缓存',not any(any(x in prior.EXCLUDED_PARTS for x in Path(p).parts) or Path(p).suffix in ['.sqlite3','.db','.log','.pyc'] for p in paths))
    import os
    keys=[os.environ.get(k,'').encode() for k in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','DASHSCOPE_API_KEY','ZHIHENG_API_KEY','GH_TOKEN','GITHUB_TOKEN']]
    hits=[]
    for row in rows:
        raw=(ROOT/row['path']).read_bytes()
        if prior.SECRET_PATTERN.search(raw) or any(len(k)>=12 and k in raw for k in keys):hits.append(row['path'])
    check('凭据扫描没有命中',not hits,hits)
    sources=json.loads((prior.DATASET/'00_来源与索引/资料总索引.json').read_text('utf-8'))['sources']
    extra=json.loads((APP/'company_sources.json').read_text('utf-8'))['sources'];sources+=extra
    matched=[]
    for s in sources:
        file=prior.DATASET/s['relative_path']
        matched.append(file.relative_to(ROOT).as_posix() in paths and prior.digest(file)==s['sha256'])
    check('102份公开原件与登记摘要一致',len(matched)==102 and all(matched),{'matched':sum(matched),'total':len(matched)})
    for definition in (APP/'demo').glob('sources*.json'):
        records=json.loads(definition.read_text('utf-8'))
        check('示范原件 '+definition.name,all(prior.digest(APP/'demo'/r['filename'])==r['sha256'] for r in records))
    record=json.loads((APP/'V0.6验收记录.json').read_text('utf-8'))
    check('自动、接口、真实模型验收已登记',record['unit_tests']['passed']==136 and record['http']['passed']==54 and record['live']['passed']==24)
    check('干净安装及非上市合成边界已验收',record.get('clean_install',{}).get('passed') is True)
    case=json.loads((APP/'demo/case_model_v06.json').read_text('utf-8'))
    check('新案例保留真实调用、压力原页和未签认状态',case['mode']=='llm' and len(case['model_calls'])==5 and case['valuation']['operating_scenario']['available'] and not record['public_case']['expert_signoff'])
    check('公开案例与验收JSON不含本机路径',not any(prior.MACHINE_PATH.search((ROOT/p).read_text('utf-8')) for p in paths if p.endswith('.json') and (p.startswith('知衡初版/demo/') or '验收记录' in p)))
    licences=json.loads((ROOT/'third_party_licenses/manifest.json').read_text('utf-8'))['files']
    check('第三方许可与NOTICE保留',len(licences)==5 and 'NOTICE.md' in paths and all(prior.digest(ROOT/'third_party_licenses'/r['file'])==r['sha256'] for r in licences))
    return {'passed':sum(r['passed'] for r in checks),'total':len(checks),'checks':checks,'ready_for_package':all(r['passed'] for r in checks)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package',action='store_true');parser.add_argument('--output-dir',default=str(ROOT.parent/'outputs/V0.6_2026-10-14'))
    args=parser.parse_args();out=Path(args.output_dir).resolve()
    if not out.is_relative_to(ROOT.parent.resolve()) or out.is_relative_to(ROOT.resolve()):raise ValueError('输出目录须位于工作区、源码之外')
    out.mkdir(parents=True,exist_ok=True)
    rows=inventory();validation=validate(rows)
    manifest={'version':'0.6.0','top_level':'ThesisLens','file_count':len(rows),'files':rows,
              'delivery_scope':'程序与公开样本体验包；计划书、视频由用户另行制作，金融复审尚未完成。',
              'uncompressed_bytes':sum(r['bytes'] for r in rows),'validation':validation}
    if args.package and validation['ready_for_package']:
        final=out/'知衡V0.6_参赛体验包.zip'
        if final.exists():raise ValueError('保留已存在的包，请选择新输出目录')
        staged=out/'知衡V0.6_参赛体验包.zip.partial'
        if staged.exists():raise ValueError('需检查既有未完成文件')
        with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
            for row in rows:
                file=ROOT/row['path']
                if prior.digest(file)!=row['sha256']:raise ValueError('源文件在封包时变化')
                archive.write(file,'ThesisLens/'+row['path'])
            archive.writestr('ThesisLens/封包清单.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        with zipfile.ZipFile(staged) as archive:
            if archive.testzip():raise ValueError('ZIP校验失败')
            for row in rows:
                if hashlib.sha256(archive.read('ThesisLens/'+row['path'])).hexdigest()!=row['sha256']:raise ValueError('包内文件摘要不一致')
        staged.replace(final)
        manifest['zip']={'filename':final.name,'sha256':prior.digest(final),'bytes':final.stat().st_size,'members':len(rows)+1}
    (out/'交付封包验收.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ready':validation['ready_for_package'],'checks':validation['passed'],'total':validation['total'],'zip':manifest.get('zip')},ensure_ascii=False))
    return 0 if validation['ready_for_package'] else 1


if __name__=='__main__':raise SystemExit(main())
