"""Focused end-to-end checks of the running local prototype; no model calls."""
import argparse
import json
import os
import urllib.error
import urllib.request
import time
from pathlib import Path

import core


def main():
    parser = argparse.ArgumentParser(description='Check a running local instance without making model calls.')
    parser.add_argument('--base-url')
    parser.add_argument('--run-id', help='Optional existing research record to check')
    args = parser.parse_args()
    service = core.APP / 'data/service.json'
    base = args.base_url or (json.loads(service.read_text('utf-8'))['url'] if service.exists() else 'http://127.0.0.1:8765')
    checks = []

    def request(path, headers=None, body=None):
        req = urllib.request.Request(base + path, data=body, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers, exc.read()

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append({'检查': name, '结果': '通过'})

    code, _, data = request('/api/status')
    status = json.loads(data)
    expected=core.base_manifest()
    check('服务启动、已登记来源与索引覆盖一致', code == 200 and
          status['dataset']['downloaded_sources'] == expected['stats']['downloaded_sources'] and
          int(status['index']['chunk_count']) >= 7855)
    secrets = [os.environ.get(k) for k in ['DEEPSEEK_API_KEY', 'OPENAI_API_KEY']]
    check('设置接口不返回本机模型密钥', all(not key or key.encode() not in data for key in secrets))

    for period in ['2026-H1', '2025-FY']:
        code, _, data = request('/api/metrics?period=' + period)
        issuers={s['stock_code'] for s in expected['sources'] if s.get('report_period')==period}
        check(period + '已登记公司指标可读取', code == 200 and {r['code'] for r in json.loads(data)['data']} == issuers)
    code, _, data = request('/api/metrics?period=2026-H1&cutoff=2026-05-01')
    check('研究截止日前未披露的半年报指标不返回', code == 200 and json.loads(data)['data'] == [])

    run_id = args.run_id
    if not run_id:
        code, _, data = request('/api/runs')
        history = json.loads(data)['data']
        latest = next((r for r in history if r['code'] == '000333' and r['mode'] == 'llm'), None)
        if latest:
            run_id = latest['id']
        else:
            body = json.dumps({'code': '000333', 'cutoff': '2026-10-06', 'question': '美的2026年上半年经营表现及反向验证风险', 'mode': 'local'}, ensure_ascii=False).encode()
            code, _, data = request('/api/research', {'Content-Type': 'application/json'}, body)
            check('无历史记录时可创建本机资料草稿', code == 202)
            job_id = json.loads(data)['job_id']
            for _ in range(30):
                _, _, data = request('/api/jobs/' + job_id)
                job = json.loads(data)
                if job['status'] == 'complete':
                    run_id = job['run_id']
                    break
                if job['status'] == 'failed':
                    raise AssertionError(job.get('error', 'Research failed'))
                time.sleep(1)
            else:
                raise AssertionError('Local research did not finish in time')
    code, _, data = request('/api/runs/' + run_id)
    result = json.loads(data)
    expected_calls = [2,3,5] if result['mode'] == 'llm' else [0]
    if result.get('retrieval') and result['mode']=='llm':expected_calls=[3,4,5,6,7]
    check('研究记录完整保留当前模式的调用过程', code == 200 and len(result['model_calls']) in expected_calls)
    check('最新行业数据和补贴政策进入证据包',
          {'IND_010', 'IND_020', 'IND_022'}.issubset({e['source_id'] for e in result['evidence']}))

    for fmt in ['md', 'json', 'html']:
        code, headers, data = request('/api/runs/' + run_id + '/export?format=' + fmt)
        check(fmt + '导出可下载并落盘', code == 200 and 'attachment' in headers.get('Content-Disposition', '') and
              (core.APP / 'exports' / ('知衡_' + result['company'] + '_' + run_id + '.' + fmt)).is_file())
        check(fmt + '导出不包含本机模型密钥', all(not key or key.encode() not in data for key in secrets))
        if fmt == 'json':
            check('完整记录导出保留证据、公式和模型输出', json.loads(data) == result)
        elif fmt=='md':
            text = data.decode('utf-8')
            check('备忘录导出保留研究时点、正文和原件引用',
                  '2026-10-06' in text and '[E1]' in text and '本地原件' in text and '反向' in text)

    source_id = result['evidence'][0]['source_id']
    code, headers, data = request('/api/files/' + source_id, {'Range': 'bytes=0-31'})
    check('PDF原件支持页预览所需的分段读取', code == 206 and len(data) == 32 and
          data.startswith(b'%PDF-') and headers.get('Content-Range', '').startswith('bytes 0-31/'))
    code, _, _ = request('/%2e%2e/core.py')
    check('静态文件路径不能越过页面目录', code == 403)
    code, _, _ = request('/api/config', {'Origin': 'https://example.invalid', 'Content-Type': 'application/json'}, b'{}')
    check('拒绝外部网页修改本机模型设置', code == 403)
    code, _, _ = request('/api/config', {'Content-Type': 'text/plain'}, b'{}')
    check('拒绝非JSON设置请求', code == 415)

    report = {
        '项目': '知衡——融合证据链与反向验证的买方投研智能体',
        '版本': status['version'], '检查时间': core.now(), '资料截止日': result['cutoff'],
        'HTTP与导出检查': checks,
        '本次研究检查': {'模式': result['mode_label'], '运行编号': run_id,
                         '调用次数': len(result['model_calls']), '证据数量': len(result['evidence']),
                         '耗时秒': result['duration_seconds'], '复核提出待核验问题数': len(result['review']['issues'])},
        '启动入口': '启动知衡.cmd',
        '范围': '可运行的比赛原型；估值采用用户假设，关键词检索与本地数据跟踪，模型结论仍需人工核验。'
    }
    output = core.APP / 'data/http-check.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps({'HTTP与导出': len(checks), '结果': '全部通过', '检查记录': 'data/http-check.json'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
