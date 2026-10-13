"""Validate and package the current workspace without reading/writing Git's index.

Default: validate and record the deliverable file manifest. --manifest-only records
a preliminary inventory; --package validates again, then makes a local ZIP.
Sensitive scans report filenames only, never matched content or key values.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import zipfile

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT/'知衡初版'
DATASET = ROOT/'知衡数据资料/家电行业_截至2026-10-06'
DEFAULT_OUT = ROOT.parent/'outputs/V0.5_2026-10-12_终验'
EXCLUDED_PARTS = {'.git', '.codex', '.agents', 'data', 'exports', '__pycache__', 'tmp', '.tmp', 'node_modules', '.idea', '.vscode'}
PRIVATE_NAMES = re.compile(r'报名|证件|身份证|学生证|护照|id.?card|passport|registration|student.?id', re.I)
APP_EXTENSIONS = {'.py', '.md', '.json', '.txt', '.cmd', '.jpg', '.jpeg', '.png', '.svg', '.html', '.js', '.css'}
APP_PREVIEWS = {'预览.jpg', '预览V0.5.jpg', '财务解剖预览.jpg', '官方公告预览.jpg'}
DOC_NAMES = {'README.md', '项目计划书.md', '演示与答辩手册.md', '技术报告.md', '第三方与模型说明.md',
             '项目计划书_Typora.md', 'Typora导出说明.md', '提交前清单.md', '逻辑修订与金融核验要点.md', '逻辑修订稿_供金融复核.md', 'build_materials.py', 'publish_demo.py', 'revise_logic_demo.py', 'release_v05.py'}
VIDEO_NAMES = {'build_video.py', 'video_metadata.json', '知衡_项目简介.mp4'}
PDF_NAMES = {'知衡_项目计划书.pdf', '知衡_演示与答辩手册.pdf'}
SECRET_PATTERN = re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{20,})\b')
MACHINE_PATH = re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:[\\/]|Administrator', re.I)


def digest(file):
    value = hashlib.sha256()
    with file.open('rb') as source:
        while block := source.read(1024*1024):
            value.update(block)
    return value.hexdigest()


def include(relative, include_video=False):
    if any(part.lower() in EXCLUDED_PARTS for part in relative.parts) or PRIVATE_NAMES.search(relative.as_posix()):
        return False
    name = relative.name
    if name.startswith(('.env', 'config.local', '.tmp', 'tmp_')) or name in ['Thumbs.db', '.DS_Store'] or relative.suffix.lower() in ['.pyc', '.pyo', '.log', '.sqlite3', '.db']:
        return False
    if len(relative.parts) == 1:
        return name in ['README.md', '.gitignore', '.gitattributes', 'NOTICE', 'NOTICE.md', 'NOTICE.txt', 'LICENSE', 'LICENSE.md', 'LICENSE.txt']
    if relative.parts[0] == '知衡初版':
        if relative.suffix.lower() not in APP_EXTENSIONS and not (relative.parts[1] == 'demo' and relative.suffix.lower() == '.pdf'):
            return False
        if relative.suffix.lower() in ['.jpg', '.jpeg', '.png'] and relative.parts[1] not in ['static', 'demo'] and name not in APP_PREVIEWS:
            return False
        return len(relative.parts) == 2 or relative.parts[1] in ['static', 'demo']
    if relative.parts[0] == '知衡数据资料':
        return len(relative.parts) >= 3 and relative.parts[1] == '家电行业_截至2026-10-06'
    if relative.parts[0] == '参赛交付':
        return len(relative.parts) == 2 and (name in DOC_NAMES or (include_video and name in VIDEO_NAMES))
    if relative.parts[0] == 'third_party_licenses':
        return len(relative.parts) == 2 and relative.suffix.lower() in ['.txt','.md','.json']
    if relative.parts[:2] == ('output', 'pdf'):
        return len(relative.parts) == 3 and name in PDF_NAMES
    return False


def inventory(include_video=False):
    selected = []
    for folder, directories, filenames in os.walk(ROOT):
        directories[:] = [name for name in directories if name.lower() not in EXCLUDED_PARTS and not name.lower().startswith(('tmp_', '.tmp')) and not PRIVATE_NAMES.search(name)]
        for name in filenames:
            file = Path(folder)/name
            relative = file.relative_to(ROOT)
            if include(relative,include_video):
                # Resolve before reading: delivery cannot follow a link outside ROOT.
                if not file.resolve().is_relative_to(ROOT.resolve()) or file.is_symlink():
                    raise ValueError('封包路径超出项目范围：' + relative.as_posix())
                selected.append({'path': relative.as_posix(), 'bytes': file.stat().st_size, 'sha256': digest(file)})
    return sorted(selected, key=lambda row: row['path'])


def video_duration(file):
    """Read actual MP4 mvhd timing without launching media tools or trusting sidecars."""
    with file.open('rb') as stream:
        total = file.stat().st_size
        def boxes(start, end):
            offset = start
            while offset + 8 <= end:
                stream.seek(offset)
                size, kind = struct.unpack('>I4s', stream.read(8))
                header = 8
                if size == 1:
                    size = struct.unpack('>Q', stream.read(8))[0]
                    header = 16
                elif size == 0:
                    size = end-offset
                if size < header or offset+size > end:
                    raise ValueError('视频MP4容器尺寸无效')
                yield kind, offset+header, offset+size
                offset += size
        for kind, start, end in boxes(0, total):
            if kind != b'moov':
                continue
            for child, begin, finish in boxes(start, end):
                if child != b'mvhd':
                    continue
                stream.seek(begin)
                payload = stream.read(min(32, finish-begin))
                if payload[0] == 1:
                    timescale = struct.unpack('>I', payload[20:24])[0]
                    duration = struct.unpack('>Q', payload[24:32])[0]
                else:
                    timescale, duration = struct.unpack('>II', payload[12:20])
                if not timescale:
                    raise ValueError('视频时间基无效')
                return duration/timescale
    raise ValueError('视频没有可读取的MP4时长')


def validate(files,include_video=False):
    paths = {row['path'] for row in files}
    checks, hits = [], []
    def check(name, passed, details=None):
        item = {'name': name, 'passed': bool(passed)}
        if details is not None:
            item['details'] = details
        checks.append(item)
    required = ['README.md', '知衡初版/decision.py', '知衡初版/research.py', '知衡初版/valuation.py',
                '知衡初版/启动知衡.cmd', '知衡初版/static/index.html', '知衡初版/V0.5验收记录.json',
                '参赛交付/项目计划书.md', '参赛交付/演示与答辩手册.md', '参赛交付/技术报告.md',
                '参赛交付/第三方与模型说明.md', '参赛交付/项目计划书_Typora.md', '参赛交付/Typora导出说明.md',
                'output/pdf/知衡_项目计划书.pdf', 'output/pdf/知衡_演示与答辩手册.pdf']
    check('必要源码、验收与材料存在于当前封包清单', all(name in paths for name in required), [name for name in required if name not in paths])
    check('交付根目录包含第三方NOTICE', any(name in paths for name in ['NOTICE', 'NOTICE.md', 'NOTICE.txt']))
    license_manifest=ROOT/'third_party_licenses/manifest.json'
    license_entries=json.loads(license_manifest.read_text('utf-8'))['files'] if license_manifest.is_file() else []
    license_checks=[]
    for row in license_entries:
        file=ROOT/'third_party_licenses'/row['file']
        license_checks.append(file.resolve().is_relative_to((ROOT/'third_party_licenses').resolve()) and file.relative_to(ROOT).as_posix() in paths and file.is_file() and digest(file)==row['sha256'])
    check('第三方许可证原文按清单逐项SHA256一致', len(license_entries)==5 and all(license_checks),{'count':len(license_entries),'matched':sum(license_checks)})
    check('清单排除本机数据库、缓存、临时目录与私人报名证件', all(include(Path(name),include_video) for name in paths))
    keys = [os.environ.get(name, '').encode() for name in ['DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'DASHSCOPE_API_KEY', 'ZHIHENG_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN']]
    for row in files:
        file = ROOT/row['path']
        data = file.read_bytes()
        if SECRET_PATTERN.search(data) or any(len(value) >= 12 and value in data for value in keys):
            hits.append(row['path'])
    check('密钥扫描只报告命中路径且没有命中', not hits, hits)
    manifest = json.loads((DATASET/'00_来源与索引/资料总索引.json').read_text('utf-8'))
    originals = []
    for source in manifest['sources']:
        file = DATASET/source['relative_path']
        relative = file.relative_to(ROOT).as_posix()
        originals.append(relative in paths and file.is_file() and digest(file) == source['sha256'])
    check('96份公开原件逐项SHA256一致', len(originals) == 96 and all(originals), {'count': len(originals), 'matched': sum(originals)})
    demo_sources = sorted((APP/'demo').glob('sources*.json'))
    demo_count = 0
    demo_ok = True
    for definition in demo_sources:
        for source in json.loads(definition.read_text('utf-8')):
            file = APP/'demo'/source['filename']
            demo_count += 1
            demo_ok = demo_ok and file.is_file() and file.relative_to(ROOT).as_posix() in paths and digest(file) == source['sha256']
    check('历史与新版示范原件逐项SHA256一致', bool(demo_sources) and demo_ok, {'definitions': [file.relative_to(ROOT).as_posix() for file in demo_sources], 'entries': demo_count})
    public_records = [row['path'] for row in files if (row['path'].startswith('知衡初版/demo/') and row['path'].endswith('.json')) or (row['path'].startswith('知衡初版/') and '验收记录' in row['path'] and row['path'].endswith('.json'))]
    machine_hits = [name for name in public_records if MACHINE_PATH.search((ROOT/name).read_text('utf-8'))]
    check('公开示范与验收JSON不含本机绝对路径', not machine_hits, machine_hits)
    cases = []
    for file in (APP/'demo').glob('*case*model*.json'):
        content = json.loads(file.read_text('utf-8'))
        if all(key in content for key in ['decision', 'investment_profile', 'comparison_checks']) and content.get('mode') == 'llm' and len(content.get('model_calls', [])) >= 3:
            cases.append(file.relative_to(ROOT).as_posix())
    check('已保存含V0.5判断字段的公开真实模型案例', bool(cases), cases)
    version_files = ['README.md', '知衡初版/README.md', '参赛交付/README.md', '参赛交付/技术报告.md', '参赛交付/项目计划书.md', '参赛交付/演示与答辩手册.md']
    outdated = [name for name in version_files if 'V0.5' not in (ROOT/name).read_text('utf-8')]
    check('项目与材料说明已更新V0.5', not outdated, outdated)
    from pypdf import PdfReader
    pdfs = []
    for name in sorted(PDF_NAMES):
        file = ROOT/'output/pdf'/name
        reader = PdfReader(file)
        text = [page.extract_text() or '' for page in reader.pages]
        pdfs.append({'path': file.relative_to(ROOT).as_posix(), 'pages': len(text), 'all_pages_have_text': all(value.strip() for value in text), 'mentions_v05': any('V0.5' in value for value in text)})
    check('两份PDF可读取、逐页有文本且明确V0.5', all(row['pages'] > 0 and row['all_pages_have_text'] and row['mentions_v05'] for row in pdfs), pdfs)
    if include_video:
        video = ROOT/'参赛交付/知衡_项目简介.mp4'
        duration = video_duration(video)
        check('实际MP4时长与大小符合交付约束', 0 < duration <= 300 and video.stat().st_size <= 500*1024*1024,
              {'path': video.relative_to(ROOT).as_posix(), 'duration_seconds': duration, 'bytes': video.stat().st_size})
        metadata_file = ROOT/'参赛交付/video_metadata.json'
        metadata = json.loads(metadata_file.read_text('utf-8')) if metadata_file.exists() else {}
        check('视频明确V0.5且元数据SHA256与实际文件一致', metadata.get('version') == '0.5.0' and metadata.get('sha256') == digest(video))
    else:
        check('用户自行制作视频，体验包未混入旧版MP4或元数据', not any('参赛交付/'+name in paths for name in VIDEO_NAMES))
    return {'checks': checks, 'passed': sum(row['passed'] for row in checks), 'total': len(checks), 'ready_for_package': all(row['passed'] for row in checks)}


def package(files, output, manifest):
    final = output/'知衡V0.5_参赛体验包.zip'
    if final.exists():
        raise ValueError('交付ZIP已存在；请保留旧包后选择新的输出目录。')
    staging = output/'知衡V0.5_参赛体验包.zip.partial'
    if staging.exists():
        raise ValueError('发现未完成的封包，请先检查该临时文件。')
    try:
        with zipfile.ZipFile(staging, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for row in files:
                file = ROOT/row['path']
                if digest(file) != row['sha256']:
                    raise ValueError('封包过程中工作区文件变化：' + row['path'])
                archive.write(file, 'ThesisLens/' + row['path'])
            archive.writestr('ThesisLens/封包清单.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(staging) as archive:
            if archive.testzip() is not None:
                raise ValueError('ZIP完整性检查失败')
            for row in files:
                with archive.open('ThesisLens/' + row['path']) as member:
                    value = hashlib.sha256()
                    while block := member.read(1024*1024):
                        value.update(block)
                    if value.hexdigest() != row['sha256']:
                        raise ValueError('ZIP内文件摘要不一致：' + row['path'])
        staging.replace(final)
        return {'filename': final.name, 'bytes': final.stat().st_size, 'sha256': digest(final), 'members': len(files)+1, 'top_level': 'ThesisLens'}
    finally:
        if staging.exists():
            staging.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', action='store_true')
    parser.add_argument('--manifest-only', action='store_true')
    parser.add_argument('--include-video', action='store_true', help='Include and verify a separately completed V0.5 video')
    parser.add_argument('--output-dir', default=str(DEFAULT_OUT))
    args = parser.parse_args()
    if args.package and args.manifest_only:
        parser.error('--package and --manifest-only are mutually exclusive')
    output = Path(args.output_dir).resolve()
    if not output.is_relative_to(ROOT.parent.resolve()) or output.is_relative_to(ROOT.resolve()):
        raise ValueError('输出目录必须位于工作区内且在ThesisLens源码目录之外')
    output.mkdir(parents=True, exist_ok=True)
    files = inventory(args.include_video)
    manifest = {'version': '0.5.0', 'source': 'current_workspace_files', 'top_level': 'ThesisLens',
                'file_count': len(files), 'uncompressed_bytes': sum(row['bytes'] for row in files), 'files': files,
                'delivery_scope':'本地程序与文档体验包；不代表全部参赛前置事项完成',
                'video_included':args.include_video}
    validation = {'ready_for_package': False, 'validation_not_run': True} if args.manifest_only else validate(files,args.include_video)
    report = dict(manifest, validation=validation)
    if args.package and validation['ready_for_package']:
        report['zip'] = package(files, output, manifest)
    name = '封包清单_待终验.json' if args.manifest_only else '交付封包验收.json'
    (output/name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'report': str(output/name), 'file_count': len(files), 'ready_for_package': validation['ready_for_package'], 'zip': report.get('zip')}, ensure_ascii=False))
    return 0 if args.manifest_only or validation['ready_for_package'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
