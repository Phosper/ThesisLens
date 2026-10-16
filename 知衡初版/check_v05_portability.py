"""Offline clean-install acceptance using a copied app and public corpus only.

Creates a retained isolated installation below ThesisLens/tmp/v05_portability.
Never invokes a model or a public-network request; the server uses an ephemeral
loopback port. --restore-only repeats demo restoration after replacing its public
snapshot, without touching the main app's local databases or service.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from unittest.mock import patch

import core


def worker(output, restore_only=False):
    import demo_case
    import exporting
    import model
    import server

    report = {'date': core.now(), 'scope': '同一台电脑上的源码与公开数据副本、干净本地数据库和独立服务验证；不是另一台实体电脑测试，也不是独立盲测。',
              'install_path': str(core.ROOT), 'app_path': str(core.APP), 'dataset_path': str(core.DATASET),
              'restore_only': restore_only, 'checks': [], 'cases': [], 'model_attempts': 0,
              'public_network_attempts': 0}
    http = None
    original_urlopen = urllib.request.urlopen
    def local_only(request, *args, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if urllib.parse.urlparse(url).hostname not in ['127.0.0.1', 'localhost']:
            report['public_network_attempts'] += 1
            raise AssertionError('Portability acceptance cannot access public network')
        return original_urlopen(request, *args, **kwargs)
    def no_model(*args, **kwargs):
        report['model_attempts'] += 1
        raise AssertionError('Portability acceptance cannot make model requests')
    def check(name, passed, evidence=None):
        item = {'name': name, 'passed': bool(passed)}
        if evidence is not None:
            item['evidence'] = evidence
        report['checks'].append(item)
        if not passed:
            raise AssertionError(name)
    try:
        with patch('model.complete', side_effect=no_model), patch('urllib.request.urlopen', side_effect=local_only):
            if not restore_only:
                check('启动前数据库为空', not core.INDEX.exists() and not core.RUNS.exists())
            core.ensure_index()
            http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
            http.daemon_threads = True
            thread = threading.Thread(target=http.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:' + str(http.server_port)
            report['base_url'] = base
            def request(path, body=None):
                data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
                req = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=30) as response:
                    raw = response.read()
                    return json.loads(raw) if response.headers.get('Content-Type', '').startswith('application/json') else raw.decode('utf-8')
            def job(body):
                task = request('/api/research', body)
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    row = request('/api/jobs/' + task['job_id'])
                    if row['status'] == 'failed':
                        raise AssertionError(row.get('error'))
                    if row['status'] == 'complete':
                        return request('/api/runs/' + row['run_id'])
                    time.sleep(.05)
                raise TimeoutError('Local research task did not complete')
            status = request('/api/status')
            report['version'] = status['version']
            report['index'] = status['index']
            check('干净副本独立启动V0.5或V0.6', status['version'] in ['0.5.0','0.6.0'] and http.server_port != 8765,
                  {'port': http.server_port, 'instance_id': status['instance_id']})
            check('基础公开来源与索引恢复', int(status['index']['source_count']) == 96 and int(status['index']['chunk_count']) > 7000,
                  {'sources': status['index']['source_count'], 'chunks': status['index']['chunk_count']})
            if not restore_only:
                check('新安装没有复用原本机研究记录', request('/api/runs')['data'] == [])
                cases = [
                    ('000333', '2025-06-01', '美的2025年一季度经营现金流同比与扣非利润是否一致，请给出可核验口径。', '2025-Q1'),
                    ('000651', '2024-09-01', '格力2024年上半年归母和扣非利润有哪些差异，现金流能否支持这些判断？', '2024-H1'),
                    ('600690', '2023-11-01', '海尔2023年三季度现金流、营收与利润的累计口径如何核验？', '2023-Q3'),
                    ('000333', '2026-08-28', '美的2026年上半年营业收入、应收与现金流是否能形成研究结论？', '2026-H1'),
                    ('000333', '2022-08-30', '美的2022年上半年营收和现金流有哪些已披露证据？', '2022-H1'),
                ]
                for code, cutoff, question, period in cases:
                    run = job({'code': code, 'cutoff': cutoff, 'question': question, 'mode': 'local',
                               'options': {'investment_profile': {'goal': '核验陌生期间的研究依据', 'horizon_months': 9, 'budget_yuan': '10000', 'max_loss_pct': '10'}}})
                    snapshot = {'code': code, 'company': run['company'], 'cutoff': cutoff, 'question': question,
                                'period': run['period'], 'run_id': run['id'], 'evidence_count': len(run['evidence']),
                                'max_evidence_date': max(row['publication_date'] for row in run['evidence']),
                                'metric_count': len(run['metrics']), 'target_metric_count': sum(row['code'] == code for row in run['metrics']), 'decision': run['decision']['status']}
                    report['cases'].append(snapshot)
                    check(code + ' ' + cutoff + '资料题完成且保留截止日', run['period'] == period and run['cutoff'] == cutoff and not run['model_calls'], snapshot)
                    check(code + ' ' + cutoff + '全部证据不越过时点', all(row['publication_date'] <= cutoff for row in run['evidence']))
                    check(code + ' ' + cutoff + 'V0.5决策字段与用户假设保留', run['investment_profile']['horizon_months'] == 9 and all(key in run['decision'] for key in ['basis', 'entry_conditions', 'exit_conditions', 'return_scenarios', 'missing', 'review_status']) and isinstance(run['comparison_checks'], list))
                    check(code + ' ' + cutoff + '资料模式没有强制投资建议', run['decision']['status'] == '暂缓投资判断')
                    if cutoff in ['2026-08-28', '2022-08-30']:
                        check(cutoff + '未披露目标财报不参与计算', all(row['code'] != code and row['publication_date'] <= cutoff for row in run['metrics']) and not run['financial_depth']['available'])
                    for view in ['brief', 'full']:
                        for fmt in ['md', 'html', 'json']:
                            content = request('/api/runs/' + run['id'] + '/export?' + urllib.parse.urlencode({'format': fmt, 'view': view}))
                            text = json.dumps(content, ensure_ascii=False) if isinstance(content, dict) else content
                            check(code + ' ' + cutoff + '导出 ' + view + '/' + fmt,
                                  '暂缓投资判断' in text and ('投资判断' in text or 'decision' in text) and ('E1' in text))
                history = request('/api/financial/history?code=000333&cutoff=2022-08-30')
                check('更正披露日期前的2022半年报不穿越', all(row['source_id'] != 'SINA_000333_8507661' for row in history['data']))
                context = request('/api/valuation/context?code=000333&cutoff=2026-10-06')
                shares = context['reported_shares']
                value = request('/api/valuation', {'code': '000333', 'cutoff': '2026-10-06',
                    'assumptions': {'shares_yi': shares['total_yi'], 'shares_source_id': shares['source_id'],
                                   'pe_basis': '验收演示假设，不声称行业估值依据', 'pe_basis_reviewed': False,
                                   'dividend_per_share_yuan': '0', 'fees_pct': '0'}})
                check('新安装参考PE与A股币种口径可追溯', value['market_pe']['available'] and value['market_pe']['price_share_class'] == 'A' and value['market_pe']['price_currency'] == 'CNY' and bool(value['market_pe']['shares_source_id']))
                check('新安装估值依据未审状态保留', value['pe_basis']['status'] == 'unreviewed' and all(row['price_return_pct'] is not None and row['total_return_pct'] is not None for row in value['pe_scenarios']))
                scenario_run = job({'code': '000333', 'cutoff': '2026-10-06', 'question': '美的2026年上半年利润质量和所附估值情景如何核验？', 'mode': 'local',
                                    'options': {'valuation_id': value['id'], 'investment_profile': {'horizon_months': 12, 'budget_yuan': '10000', 'max_loss_pct': '10'}}})
                check('带估值记录仍保留未审倍数与损失约束缺口', scenario_run['decision']['status'] == '暂缓投资判断' and any('PE倍数' in item for item in scenario_run['decision']['missing']) and any('最大可接受损失' in item and '超出' in item for item in scenario_run['decision']['missing']))
            restored = demo_case.restore()
            run = request('/api/runs/' + restored['run_id'])
            report['restored_demo'] = {'run_id': run['id'], 'original_id': run['demo_original']['id'],
                                       'original_created_at': run['demo_original']['created_at'],
                                       'model_calls_saved': len(run['model_calls']),
                                       'comparison_checks': [row['rule'] for row in run['comparison_checks']],
                                       'decision': run['decision']['status'], 'compatibility_view': run['decision']['review_status']['compatibility_view'],
                                       'snapshot_sha256': hashlib.sha256((core.APP/'demo/case_model.json').read_bytes()).hexdigest()}
            check('公开历史示范无需新模型请求即可恢复', len(run['model_calls']) >= 3 and bool(run['demo_original']) and report['model_attempts'] == 0)
            check('恢复示范保留历史身份与未签认核验状态', '历史' in run['mode_label'] and '历史' in run['warnings'][0] and not run['human_review']['notes'])
            check('恢复示范新增判断不被伪称专家签认', run['decision']['status'] == '暂缓投资判断' and run['decision']['review_status']['pending_theses'] > 0)
            for row in run['evidence']:
                check('恢复引用原件存在 ' + row['citation'], core.file_for(core.source(row['source_id'])).is_file())
            for view in ['brief', 'full']:
                text = request('/api/runs/' + run['id'] + '/export?format=md&view=' + view)
                html = request('/api/runs/' + run['id'] + '/print?view=' + view)
                check('恢复示范简详导出可用 ' + view, '投资判断' in text and '暂缓投资判断' in html and '人工核验' in html)
            check('接受测试未调用大模型或公网', report['model_attempts'] == 0 and report['public_network_attempts'] == 0)
        report['completed'] = True
    except Exception:
        report['completed'] = False
        report['error'] = traceback.format_exc()
    finally:
        if http is not None:
            http.shutdown()
            http.server_close()
        report['passed'] = sum(row['passed'] for row in report['checks'])
        report['total'] = len(report['checks'])
        report['source_hashes'] = {name: hashlib.sha256((core.APP/name).read_bytes()).hexdigest() for name in ['core.py', 'research.py', 'decision.py', 'valuation.py', 'exporting.py', 'server.py']}
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report': str(output), 'completed': report['completed'], 'passed': report['passed'], 'total': report['total']}, ensure_ascii=False))
    return 0 if report['completed'] else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--output')
    parser.add_argument('--restore-only', action='store_true')
    parser.add_argument('--install-path', help='Existing isolated install for demo-only recheck')
    args = parser.parse_args()
    if args.worker:
        return worker(args.output, args.restore_only)
    root = (core.ROOT/'tmp/v05_portability').resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.restore_only:
        if not args.install_path:
            parser.error('--restore-only requires --install-path')
        install = Path(args.install_path).resolve()
        if not install.is_relative_to(root) or not (install/'知衡初版/core.py').is_file():
            raise ValueError('复测目标必须是v05_portability中的已有隔离副本')
        # The demo selector and decision guards may have changed with the case.
        # Refresh public app files while retaining this isolated install's own DBs.
        shutil.copytree(core.APP, install/'知衡初版', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('data', 'exports', '__pycache__', '*.pyc', '*.log', '.env', '.env.*', 'config.local.json'))
        output = install/'v05_demo_restore_recheck.json'
    else:
        stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')
        install = root/('clean_install_' + stamp)
        shutil.copytree(core.APP, install/'知衡初版', ignore=shutil.ignore_patterns('data', 'exports', '__pycache__', '*.pyc', '*.log', '.env', '.env.*', 'config.local.json'))
        shutil.copytree(core.DATASET, install/'知衡数据资料/家电行业_截至2026-10-06')
        output = install/'v05_portability_acceptance.json'
    environment = dict(os.environ, PYTHONIOENCODING='utf-8')
    for key in ['DEEPSEEK_API_KEY', 'OPENAI_API_KEY', 'DASHSCOPE_API_KEY', 'ZHIHENG_API_KEY', 'ZHIHENG_DATASET', 'ZHIHENG_KEY_ENV']:
        environment.pop(key, None)
    command = [sys.executable, str(install/'知衡初版'/Path(__file__).name), '--worker', '--output', str(output)]
    if args.restore_only:
        command.append('--restore-only')
    result = subprocess.run(command, cwd=install/'知衡初版', env=environment, capture_output=True, text=True, encoding='utf-8')
    (install/'acceptance_stdout.txt').write_text(result.stdout, encoding='utf-8')
    (install/'acceptance_stderr.txt').write_text(result.stderr, encoding='utf-8')
    print(json.dumps({'install_path': str(install), 'report': str(output), 'exit_code': result.returncode}, ensure_ascii=False))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
