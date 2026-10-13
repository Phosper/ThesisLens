"""Make a separate, explicitly developer-edited example; never call a model.

The original model record and its original reviews remain unchanged.  This
script changes reasoning wording, not the numerical sources or human status.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'知衡初版'))
import core
import decision
import research
from publish_demo import verify_public


def revise(parent):
    if parent['id'] != 'eb64fcc72e43':
        raise ValueError('This revision is scoped to the selected original eb64 case.')
    run = copy.deepcopy(parent)
    draft = run['draft']
    source_text = draft['thesis'][2]['text']
    old_third = copy.deepcopy(draft['thesis'][2])
    # Keep the factual limitations, instead of inventing a stable-profit thesis.
    old_third.update(text=source_text.replace('T3：', '利润分类核验限制：', 1),
                     kind='核验建议', thesis_ids=[])
    old_third.pop('id', None)
    draft['open_questions'].insert(0, old_third)
    draft['thesis'].pop(2)
    draft['invalidation'].pop(2)
    draft['monitoring'].pop(2)
    for section in ['thesis', 'risks', 'invalidation', 'monitoring', 'open_questions']:
        for row in draft[section]:
            row['thesis_ids'] = ['T3' if tid == 'T4' else tid for tid in row.get('thesis_ids', []) if tid != 'T3']
            row['text'] = row['text'].replace('T4', 'T3')
    draft['thesis'][2]['id'] = 'T3'
    draft['thesis'][1].update(
        text='T2：H1应收账款净额619.55亿元，较期初+53.16%[E4]；未扣坏账的账龄账面余额中，一年以内由398.82亿元升至612.93亿元，坏账准备由17.20亿元升至20.88亿元[E26]。净额与账面余额分别列示。待验证研究假设：应收增长可能主要属于季节性或结算节奏扰动，而非持续回款恶化。拟以同日期、同合并范围、同净额口径的应收同比相对对应累计期间营收同比，以及同公式周转天数相对上年同累计期间分别观察；应收同比不高于营收同比且周转天数未同比拉长仅为本研究设定的支持观察条件，不单独证明季节性因果。两项基准及季节性证据待补；较期初53.16%仅作历史背景，不作未来同比或天数阈值。',
        kind='推测')
    draft['invalidation'][1].update(
        text='T2复核条件：取得同日期、同合并范围、同净额口径数据后，若应收同比高于对应累计期间营收同比，或按同公式计算的周转天数较上年同累计期间拉长，则重新评估“季节性或结算扰动而非持续回款恶化”的假设。两项触发条件为研究假设，尚缺基准；触发不等于已证明回款恶化或季节性解释不成立。账龄另按同账面余额分母核验，未来一年以上占比上升只作为补充核验信号，不称当前已“继续抬升”；历史期初变化不作同比/天数基准。',
        kind='核验建议')
    draft['monitoring'][1].update(
        text='T2：应收账款净额分别登记观察日余额与上年同日余额，并核对合并范围后计算同比，再与对应累计期间营收同比对照；周转天数登记计算公式、同累计期间收入、期初期末应收及上年同期间天数，保持平均应收与收入口径一致。两项基准和季节性说明尚待补齐，缺失时只标待核验，不评价是否改善。账龄账面余额与应收净额分别列示[E4][E26]。',
        kind='核验建议')
    draft['thesis'][2]['text'] = draft['thesis'][2]['text'].replace(
        '下期同口径该比值或维持在1附近及以上',
        '后续同累计期间、同合并范围该比值可能维持在1及以上（1仅为本研究假设阈值，非行业标准；需考虑季节性）')
    draft['invalidation'][2].update(
        text='T3复核条件：若后续同累计期间、同合并范围的经营现金流与归母净利润比值低于1，触发重新评估“该比值维持在1及以上”的研究假设。阈值1是研究假设；该条件不等于整体现金回收恶化，更不推翻H1已披露现金流与利润。',
        kind='核验建议')
    draft['monitoring'][2]['text'] = 'T3：分别核对后续同累计期间、同合并范围的经营现金流和归母净利润及其比值，并考虑季节性；阈值1为研究假设。本期1.42仅作已计算历史背景[计算包]，不把不同累计期间比值直接解释为趋势；该比值不等于全部利润的现金转化[E1]。'
    draft['risks'][0]['text'] = draft['risks'][0]['text'].replace(
        '上年同期为财务收入-59.88亿元', '上年同期为财务收入59.88亿元（转换为财务费用口径为-59.88亿元）')
    # No inherited approval or model review is a review of this edited text.
    for key in ['human_review', 'review', 'previous_review', 'previous_comparison_checks',
                'decision', 'decision_at_generation', 'postrun_development_audit',
                'previous_case_development_audit', 'audit', 'audit_at_generation', 'demo_original']:
        run.pop(key, None)
    raw = json.dumps(draft, ensure_ascii=False, sort_keys=True).encode('utf-8')
    run.update(id='logic'+hashlib.sha256(raw).hexdigest()[:12], created_at=core.now(),
               mode='development_revision', mode_label='开发侧逻辑修订示范 · 尚待金融核验',
               model_calls=[], previous_review=None, previous_comparison_checks=[],
               duration_seconds=0, demo_version='0.5.0-logic1',
               demo_scope='由eb64真实模型案例派生的开发侧逻辑修订；未新增模型调用或金融签认。')
    run['revision_provenance'] = {
        'kind': 'developer_logic_revision', 'parent_run_id': parent['id'],
        'parent_snapshot': 'demo/case_model_v05.json',
        'parent_model_call_count': len(parent.get('model_calls', [])),
        'new_model_call_count': 0, 'human_financial_review_completed': False,
        'note': '原模型写作、复核及运行留痕均在父记录；本例不继承其复核结论。原T3核验限制移入待核实问题，原T4重编号为T3。'}
    run['review'] = {'source': 'development_revision', 'summary': '开发侧已修订比较基准、反证对象及相邻措辞；本例未新作模型复核，也未经金融人工核验。规则通过不表示事实或假设正确。', 'issues': []}
    run['warnings'] = [run['demo_scope'],
                       '应收同日期同比、同公式周转天数、季节性及合并范围证据仍待补；量化利润调节桥和PE倍数依据仍待金融核验。',
                       '本例没有新增真实模型研究，模型调用记录为空；父记录7次调用不计入本例。']
    run['trace'] = [{'title': '开发侧逻辑修订', 'detail': run['revision_provenance']['note'], 'elapsed_seconds': 0}]
    run['audit'] = {'available': False, 'run_id': run['id'], 'model_attempts': [], 'events': [],
                    'event_count': 0, 'scope': '开发侧修订文件；未新增模型请求。恢复时另登记本次文件读取。'}
    run['audit_at_generation'] = copy.deepcopy(run['audit'])
    draft, warnings = research.validate_draft(draft, run['evidence'])
    run['draft'] = draft
    run['warnings'].extend(warnings)
    run['comparison_checks'] = decision.comparison_checks(run)
    if run['comparison_checks']:
        raise ValueError('The edited example still fails a bounded reasoning rule.')
    run['decision'] = decision.build(run)
    run['decision_at_generation'] = copy.deepcopy(run['decision'])
    return run


def main():
    folder = ROOT/'知衡初版/demo'
    parent_path = folder/'case_model_v05.json'
    original = parent_path.read_bytes()
    run = revise(json.loads(original))
    run['revision_provenance']['parent_snapshot_sha256'] = hashlib.sha256(original).hexdigest()
    verify_public(run)
    target = folder/'case_logic_v05.json'
    target.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding='utf-8')
    if parent_path.read_bytes() != original:
        raise AssertionError('Original model snapshot changed.')
    print(json.dumps({'path': str(target.relative_to(ROOT)), 'id': run['id'],
                      'mode': run['mode'], 'new_model_calls': 0,
                      'current_rule_issues': len(run['comparison_checks']),
                      'decision': run['decision']['status']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
