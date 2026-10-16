"""Package the tested app/public corpus, excluding user plans, videos and private stores."""
import argparse,hashlib,json,os,zipfile
from pathlib import Path
import release_v05 as prior
ROOT=prior.ROOT;APP=prior.APP
DOCS={'README.md','V0.7技术补完与交接.md','V0.6升级与交接.md','技术报告.md','第三方与模型说明.md','publish_demo.py','publish_v07.py','release_v05.py','release_v07.py'}

def inventory():
    rows=[r for r in prior.inventory(False) if Path(r['path']).parts[0]!='output' and (Path(r['path']).parts[0]!='参赛交付' or Path(r['path']).name in DOCS)]
    paths={r['path'] for r in rows}
    for file in [ROOT/'参赛交付'/n for n in DOCS]+[APP/n for n in ['财务结构预览V0.7.png','企业覆盖预览V0.6.jpg','海外压力预览V0.6.jpg']]:
        relative=file.relative_to(ROOT).as_posix()
        if file.is_file() and relative not in paths:rows.append({'path':relative,'bytes':file.stat().st_size,'sha256':prior.digest(file)})
    return sorted(rows,key=lambda r:r['path'])

def validate(rows):
    checks=[];paths={r['path'] for r in rows}
    def check(name,passed,detail=None):checks.append({'name':name,'passed':bool(passed),'detail':detail})
    required=['知衡初版/market_sources.json','知衡初版/financial_note_registry.json','知衡初版/financial_notes.py','知衡初版/static/depth.js',
              '知衡初版/V0.7验收记录.json','知衡初版/启动知衡.cmd','知衡初版/check_v07_clean.py','参赛交付/V0.7技术补完与交接.md']
    check('程序、登记与验收记录齐全',all(p in paths for p in required))
    check('说明中的实际页面图片齐全',all('知衡初版/'+n in paths for n in ['财务结构预览V0.7.png','企业覆盖预览V0.6.jpg','海外压力预览V0.6.jpg']))
    check('排除旧计划书、视频和金融私人反馈',not any('计划书' in p or p.startswith('output/') or Path(p).suffix.lower() in ['.mp4','.xlsx'] or Path(p).name=='build_video.py' for p in paths))
    check('排除密钥配置、本机数据库及缓存',not any(any(x in prior.EXCLUDED_PARTS for x in Path(p).parts) or Path(p).suffix in ['.sqlite3','.db','.log','.pyc'] for p in paths))
    keys=[os.environ.get(k,'').encode() for k in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','DASHSCOPE_API_KEY','ZHIHENG_API_KEY','GH_TOKEN','GITHUB_TOKEN']]
    hits=[]
    for r in rows:
        raw=(ROOT/r['path']).read_bytes()
        if prior.SECRET_PATTERN.search(raw) or any(len(k)>=12 and k in raw for k in keys):hits.append(r['path'])
    check('凭据扫描无命中',not hits,hits)
    sources=json.loads((prior.DATASET/'00_来源与索引/资料总索引.json').read_text('utf-8'))['sources']
    for name in ['company_sources.json','market_sources.json']:sources+=json.loads((APP/name).read_text('utf-8'))['sources']
    match=[(prior.DATASET/s['relative_path']).relative_to(ROOT).as_posix() in paths and prior.digest(prior.DATASET/s['relative_path'])==s['sha256'] for s in sources]
    check('105份公开来源与原件摘要一致',len(match)==105 and all(match),{'total':len(match),'matched':sum(match)})
    record=json.loads((APP/'V0.7验收记录.json').read_text('utf-8'))
    check('144项自动及61项本机流程通过',record['unit_tests']=={'passed':144,'failed':0} and record['http']['passed']==61)
    check('干净安装、合成资料边界与三稿恢复通过',record['clean_install']['passed'] and record['clean_install']['private_checks']==20 and len(record['clean_install']['restored'])==3)
    check('冻结题目相同且未冒称独立盲测',record['retrieval']['hit_at_5']==12 and hashlib.sha256((APP/'evaluation_cases_v07.json').read_bytes()).hexdigest()==record['retrieval']['case_sha256'])
    for case in record['public_cases']:
        file=APP/case['file'];run=json.loads(file.read_text('utf-8'))
        check('保存案例 '+case['company'],file.relative_to(ROOT).as_posix() in paths and prior.digest(file)==case['sha256'] and not case['expert_signoff'] and len(run['model_calls'])==5 and any(run['draft'][k] for k in ['thesis','risks','invalidation','monitoring','open_questions']))
    for definition in (APP/'demo').glob('sources*.json'):
        records=json.loads(definition.read_text('utf-8'))
        check('示范附原件 '+definition.name,all(prior.digest(APP/'demo'/r['filename'])==r['sha256'] for r in records))
    check('公开快照和验收JSON不含本机路径',not any(prior.MACHINE_PATH.search((ROOT/p).read_text('utf-8')) for p in paths if p.endswith('.json') and (p.startswith('知衡初版/demo/') or '验收记录' in p)))
    licences=json.loads((ROOT/'third_party_licenses/manifest.json').read_text('utf-8'))['files']
    check('第三方许可与NOTICE保留',len(licences)==5 and 'NOTICE.md' in paths and all(prior.digest(ROOT/'third_party_licenses'/r['file'])==r['sha256'] for r in licences))
    return {'passed':sum(c['passed'] for c in checks),'total':len(checks),'checks':checks,'ready_for_package':all(c['passed'] for c in checks)}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--package',action='store_true');parser.add_argument('--output-dir',default=str(ROOT.parent/'outputs/V0.7_2026-10-14'));args=parser.parse_args()
    out=Path(args.output_dir).resolve()
    if not out.is_relative_to(ROOT.parent.resolve()) or out.is_relative_to(ROOT.resolve()):raise ValueError('输出必须在工作区、源码外')
    out.mkdir(parents=True,exist_ok=True);rows=inventory();validation=validate(rows)
    manifest={'version':'0.7.0','file_count':len(rows),'files':rows,'validation':validation,'delivery_scope':'程序与公开样本；计划书、视频另行制作，金融复审未签认。'}
    if args.package and validation['ready_for_package']:
        final=out/'知衡V0.7_参赛体验包.zip';staged=out/'知衡V0.7_参赛体验包.zip.partial'
        if final.exists() or staged.exists():raise ValueError('保留已存在的包，请选择新目录')
        with zipfile.ZipFile(staged,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
            for r in rows:
                file=ROOT/r['path']
                if prior.digest(file)!=r['sha256']:raise ValueError('封包期间源文件变化')
                archive.write(file,'ThesisLens/'+r['path'])
            archive.writestr('ThesisLens/封包清单.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        with zipfile.ZipFile(staged) as archive:
            if archive.testzip():raise ValueError('ZIP校验失败')
            for r in rows:
                if hashlib.sha256(archive.read('ThesisLens/'+r['path'])).hexdigest()!=r['sha256']:raise ValueError('包内摘要不一致')
        staged.replace(final);manifest['zip']={'filename':final.name,'sha256':prior.digest(final),'bytes':final.stat().st_size,'members':len(rows)+1}
    (out/'交付封包验收.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'ready':validation['ready_for_package'],'checks':validation['passed'],'total':validation['total'],'zip':manifest.get('zip')},ensure_ascii=False))
    return 0 if validation['ready_for_package'] else 1
if __name__=='__main__':raise SystemExit(main())
