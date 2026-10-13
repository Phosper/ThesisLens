"""Offline regressions for incompatible future baselines and invented thesis targets.

The human-review and valuation values below are synthetic test fixtures.  They
allow a rule failure to be tested independently of ordinary missing evidence;
they do not attest to any company's financial facts or the saved demo's quality.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import decision


BASELINE_RULE = 'receivables_future_baseline_incompatible'
TARGET_RULE = 'invalidation_target_not_in_thesis'


def fixture_run():
    return {
        'mode': 'llm',
        'investment_profile': {
            'goal': '离线逻辑回归测试', 'horizon_months': 12,
            'budget_yuan': '10000', 'max_loss_pct': '20',
        },
        'draft': {
            'summary': '本例仅检验研究逻辑，不代表金融核验。[E1]',
            'thesis': [
                {'id': 'T1', 'text': '研究假设：后续海外收入同比仍高于国内。',
                 'kind': '推测', 'citations': ['E1'], 'thesis_ids': []},
                {'id': 'T2', 'text': '研究假设：后续同口径应收周转天数较上年同期缩短，基准待补。',
                 'kind': '推测', 'citations': ['E1'], 'thesis_ids': []},
            ],
            'risks': [], 'invalidation': [], 'monitoring': [], 'open_questions': [],
        },
        'evidence': [{'citation': 'E1', 'source_id': 'TEST_ONLY', 'locator': '离线测试第1页'}],
        'review': {'summary': '测试夹具，不是人工金融核验。', 'issues': []},
        'human_review': {'notes': [
            {'claim_id': 'thesis:0', 'state': 'confirmed', 'note': '合成测试状态，不代表真实人工核验。'},
            {'claim_id': 'thesis:1', 'state': 'confirmed', 'note': '合成测试状态，不代表真实人工核验。'},
        ]},
        'valuation': {
            'assumptions': {'shares_yi': '10'},
            'market_pe': {'available': True, 'pe': '12'},
            'pe_basis': {'text': '合成测试口径。', 'reviewed': True},
            'pe_scenarios': [{'label': '测试', 'pe': '8', 'equity_value_yi': '100',
                              'per_share_yuan': '10', 'price_return_pct': '-5',
                              'total_return_pct': '-3'}],
        },
    }


def add_monitoring(run, text):
    run['draft']['monitoring'] = [
        {'text': text, 'kind': '核验建议', 'citations': ['E1'], 'thesis_ids': ['T2']}
    ]


def add_invalidation(run, text, thesis_ids=None):
    run['draft']['invalidation'] = [
        {'text': text, 'kind': '推测', 'citations': ['E1'],
         'thesis_ids': thesis_ids if thesis_ids is not None else ['T1']}
    ]


class LogicAlignmentTests(unittest.TestCase):
    def matching(self, run, rule):
        before = copy.deepcopy(run)
        issues = [row for row in decision.comparison_checks(run) if row['rule'] == rule]
        self.assertEqual(run, before, '规则检查不得改写研究、来源或人工状态')
        return issues

    def test_future_receivables_cannot_use_start_period_trend_as_upper_or_lower_bound(self):
        for text in [
            '下期同基期应收同比及周转天数应不高于本期较期初增幅所隐含的趋势。',
            '下期同基期应收同比及周转天数应不低于本期较期初增幅所隐含的趋势。',
            '以本期较期初增幅所隐含的趋势作为下期同基期应收同比及周转天数的上限。',
            '以本期较期初增幅所隐含的趋势作为下期同基期应收同比及周转天数的下限。',
            '下期应收同比应不高于本期较年初增幅。',
        ]:
            with self.subTest(text=text):
                run = fixture_run()
                add_monitoring(run, text)
                issues = self.matching(run, BASELINE_RULE)
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]['severity'], '中')
                self.assertTrue(issues[0]['blocks_decision'])

    def test_explicit_incomparability_and_separate_displays_are_not_mixed_baselines(self):
        for text in [
            '同基期应收同比及周转天数不能与本期较期初增幅所隐含的趋势比较。',
            '不能将应收同比与较期初增幅比较，需分别核验基准。',
            '本期较期初增幅与下期同基期应收同比及周转天数口径不同，不应直接比较。',
            '本期应收较期初增长53.16%；下期同基期应收同比及周转天数基准待补。',
            '跟踪应收同比和周转天数，分别与上年同期间同指标比较；期末较期初增幅仅作历史展示。',
        ]:
            with self.subTest(text=text):
                run = fixture_run()
                add_monitoring(run, text)
                self.assertEqual(self.matching(run, BASELINE_RULE), [])

    def test_unrelated_later_warning_does_not_clear_incompatible_baseline(self):
        run = fixture_run()
        add_monitoring(run, '下期同基期应收同比及周转天数应不高于本期较期初增幅所隐含的趋势；存货和收入不能直接比较。')
        self.assertTrue(self.matching(run, BASELINE_RULE))

    def test_comparison_failure_keeps_links_and_blocks_an_otherwise_complete_fixture(self):
        run = fixture_run()
        self.assertEqual(decision.build(run)['status'], '有条件纳入研究候选')
        add_monitoring(run, '下期同基期应收同比及周转天数应不高于本期较期初增幅所隐含的趋势。')
        before = copy.deepcopy(run)
        issue = self.matching(run, BASELINE_RULE)[0]
        self.assertEqual(issue['source'], 'deterministic')
        self.assertEqual(issue['section'], 'monitoring')
        self.assertEqual(issue['claim_id'], 'monitoring:0')
        self.assertEqual(issue['thesis_ids'], ['T2'])
        self.assertEqual(issue['citations'], ['E1'])
        view = decision.build(run)
        self.assertEqual(view['status'], '暂缓投资判断')
        self.assertGreaterEqual(view['review_status']['unresolved_medium'], 1)
        self.assertEqual(run, before)

    def test_stability_target_must_have_been_proposed_in_the_linked_thesis(self):
        for text, kind in [
            ('管理层解释尚缺量化调节桥；缺乏逐项量化前，不能证明核心盈利稳定。', '管理层解释'),
            ('核心盈利是否稳定仍待核验；目前没有可检验的稳定判断。', '核验建议'),
            ('待验证研究假设：后续核心盈利不稳定。', '推测'),
            ('后续核心盈利不能保持稳定。', '推测'),
            ('核心盈利是否稳定需要继续观察。', '核验建议'),
            ('研究假设：后续海外收入同比仍高于国内。', '推测'),
        ]:
            with self.subTest(text=text):
                run = fixture_run()
                run['draft']['thesis'][0].update(text=text, kind=kind)
                add_invalidation(run, '若后续利润调节桥显示核心利润同比仍显著为负，则核心盈利稳定判断被推翻。')
                issues = self.matching(run, TARGET_RULE)
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]['severity'], '中')
                self.assertTrue(issues[0]['blocks_decision'])

    def test_main_profit_improvement_cannot_be_invented_in_invalidation(self):
        run = fixture_run()
        run['draft']['thesis'][0]['text'] = '主营利润能否改善仍待核验，缺少可比期间数据。'
        add_invalidation(run, '若下期主营利润继续下降，则主营利润改善判断被推翻。')
        self.assertTrue(self.matching(run, TARGET_RULE))

    def test_real_forward_hypothesis_and_its_opposite_observation_are_allowed(self):
        for thesis, invalidation in [
            ('待验证研究假设：后续同口径核心盈利保持稳定，需下期报告核验。',
             '若下期同口径核心利润持续下滑，则核心盈利稳定判断被推翻。'),
            ('待验证研究假设：后续同口径主营利润改善，需后续财报核验。',
             '若下期同口径主营利润下降，则主营利润改善判断被推翻。'),
        ]:
            with self.subTest(thesis=thesis):
                run = fixture_run()
                run['draft']['thesis'][0]['text'] = thesis
                add_invalidation(run, invalidation)
                self.assertEqual(self.matching(run, TARGET_RULE), [])

    def test_a_different_thesis_cannot_supply_the_missing_target(self):
        run = fixture_run()
        run['draft']['thesis'][0]['text'] = '管理层分类解释尚缺量化调节桥，不能证明核心盈利稳定。'
        run['draft']['thesis'][1]['text'] = '待验证研究假设：后续同口径核心盈利保持稳定。'
        add_invalidation(run, '若下期同口径核心利润持续下滑，则核心盈利稳定判断被推翻。', ['T1'])
        self.assertTrue(self.matching(run, TARGET_RULE))
        run['draft']['invalidation'][0]['thesis_ids'] = ['T2']
        self.assertEqual(self.matching(run, TARGET_RULE), [])

    def test_stability_and_improvement_are_distinct_invalidation_targets(self):
        for thesis, invalidation in [
            ('待验证研究假设：后续同口径核心盈利改善，需下期报告核验。',
             '若下期核心利润仍为负，则核心盈利稳定判断被推翻。'),
            ('待验证研究假设：后续同口径核心盈利保持稳定，需下期报告核验。',
             '若下期核心利润仍为负，则核心盈利改善判断被推翻。'),
        ]:
            with self.subTest(thesis=thesis):
                run = fixture_run()
                run['draft']['thesis'][0]['text'] = thesis
                add_invalidation(run, invalidation)
                issues = self.matching(run, TARGET_RULE)
                self.assertEqual(len(issues), 1)
                self.assertEqual(issues[0]['severity'], '中')
                self.assertEqual(issues[0]['thesis_ids'], ['T1'])

    def test_target_failure_keeps_links_and_blocks_decision_without_rewriting_input(self):
        run = fixture_run()
        run['draft']['thesis'][0].update(
            text='管理层解释尚缺量化调节桥；缺乏逐项量化前，不能证明核心盈利稳定。',
            kind='管理层解释',
        )
        add_invalidation(run, '若后续量化利润桥显示核心利润仍为负，则核心盈利稳定判断被推翻。')
        before = copy.deepcopy(run)
        issue = self.matching(run, TARGET_RULE)[0]
        self.assertEqual(issue['source'], 'deterministic')
        self.assertEqual(issue['section'], 'invalidation')
        self.assertEqual(issue['claim_id'], 'invalidation:0')
        self.assertEqual(issue['thesis_ids'], ['T1'])
        self.assertEqual(issue['citations'], ['E1'])
        view = decision.build(run)
        self.assertEqual(view['status'], '暂缓投资判断')
        self.assertGreaterEqual(view['review_status']['unresolved_medium'], 1)
        self.assertEqual(run, before)

    def test_saved_real_eb64_case_exposes_both_logic_gaps_without_rewriting_history(self):
        path = Path(__file__).parent / 'demo' / 'case_model_v05.json'
        saved_text = path.read_text(encoding='utf-8')
        run = json.loads(saved_text)
        self.assertEqual(run['id'], 'eb64fcc72e43')
        before = copy.deepcopy(run)
        issues = decision.comparison_checks(run)
        self.assertTrue(any(row['rule'] == BASELINE_RULE and row['claim_id'] == 'thesis:1'
                            and row['thesis_ids'] == ['T2'] for row in issues))
        self.assertTrue(any(row['rule'] == TARGET_RULE and row['claim_id'] == 'invalidation:2'
                            and row['thesis_ids'] == ['T3'] for row in issues))
        self.assertEqual(decision.build(run)['status'], '暂缓投资判断')
        self.assertEqual(run, before)
        self.assertEqual(path.read_text(encoding='utf-8'), saved_text)

    def test_development_revision_moves_the_profit_limit_instead_of_inventing_a_stability_thesis(self):
        folder = Path(__file__).parent / 'demo'
        run = json.loads((folder / 'case_logic_v05.json').read_text(encoding='utf-8'))
        before = copy.deepcopy(run)
        draft = run['draft']
        self.assertEqual([row['id'] for row in draft['thesis']], ['T1', 'T2', 'T3'])
        self.assertIn('经营现金流', draft['thesis'][2]['text'], '原T4现金流假设应改号为T3')
        self.assertFalse(any('核心盈利稳定' in row['text'] for row in draft['thesis']))
        moved = [row for row in draft['open_questions'] if '不能证明核心盈利稳定' in row['text']]
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0]['kind'], '核验建议')
        self.assertEqual(moved[0]['thesis_ids'], [])
        self.assertIn('尚缺量化调节桥', moved[0]['text'])
        valid = {'T1', 'T2', 'T3'}
        for section in decision.SECTIONS:
            for row in draft[section]:
                self.assertTrue(set(row.get('thesis_ids', [])).issubset(valid), (section, row))
        self.assertEqual(decision.comparison_checks(run), [])
        self.assertEqual(run, before)

    def test_development_revision_zero_rule_findings_do_not_inherit_model_or_human_verification(self):
        folder = Path(__file__).parent / 'demo'
        parent_path = folder / 'case_model_v05.json'
        parent_bytes = parent_path.read_bytes()
        parent = json.loads(parent_bytes.decode('utf-8'))
        run = json.loads((folder / 'case_logic_v05.json').read_text(encoding='utf-8'))
        before = copy.deepcopy(run)
        self.assertEqual(run['id'], 'logicb6db4b91f139')
        self.assertEqual(run['mode'], 'development_revision')
        self.assertEqual(run['model_calls'], [])
        self.assertEqual(run['review']['source'], 'development_revision')
        provenance = run['revision_provenance']
        self.assertEqual(provenance['parent_run_id'], parent['id'])
        self.assertEqual(provenance['parent_model_call_count'], len(parent['model_calls']))
        self.assertEqual(len(parent['model_calls']), 7)
        self.assertEqual(provenance['new_model_call_count'], 0)
        self.assertFalse(provenance['human_financial_review_completed'])
        self.assertEqual(provenance['parent_snapshot_sha256'], hashlib.sha256(parent_bytes).hexdigest())
        self.assertFalse(run['valuation']['pe_basis']['reviewed'])
        self.assertEqual((run.get('human_review') or {}).get('notes', []), [])
        self.assertEqual(run['audit']['model_attempts'], [])
        self.assertEqual(decision.comparison_checks(run), [])
        self.assertEqual(run['decision']['status'], '暂缓投资判断')
        current = decision.build(run)
        self.assertEqual(current['status'], '暂缓投资判断')
        self.assertEqual(current['review_status']['pending_theses'], 3)
        self.assertTrue(any('开发侧逻辑修订' in row for row in current['missing']))
        self.assertTrue(any('PE倍数依据' in row for row in current['missing']))
        parent_rules = {row['rule'] for row in decision.comparison_checks(parent)}
        self.assertTrue({BASELINE_RULE, TARGET_RULE}.issubset(parent_rules))
        self.assertEqual(run, before)
        self.assertEqual(parent_path.read_bytes(), parent_bytes)

    def test_logic_demo_restore_is_offline_and_preserves_the_derived_draft_without_parent_calls(self):
        import core
        import demo_case
        import exporting
        import knowledge
        import workbench

        path = Path(__file__).parent / 'demo' / 'case_logic_v05.json'
        saved_text = path.read_text(encoding='utf-8')
        saved = json.loads(saved_text)
        with tempfile.TemporaryDirectory(dir=core.DATA) as folder:
            isolated = Path(folder).resolve()
            self.assertTrue(isolated.is_relative_to(core.DATA.resolve()))
            with patch.object(core, 'DATA', isolated), \
                    patch.object(core, 'INDEX', isolated / 'index.sqlite3'), \
                    patch.object(core, 'RUNS', isolated / 'runs.sqlite3'), \
                    patch.object(knowledge, 'DB', isolated / 'library.sqlite3'), \
                    patch.object(workbench, 'DB', isolated / 'workbench.sqlite3'), \
                    patch('model.complete', side_effect=AssertionError('逻辑示例恢复不得请求模型')) as complete, \
                    patch('urllib.request.urlopen', side_effect=AssertionError('逻辑示例恢复不得访问网络')) as network:
                core.ensure_index()
                result = demo_case.restore('v05_logic')
                run = core.get_run(result['run_id'])
                self.assertNotEqual(run['id'], saved['id'])
                self.assertEqual(result['original_run_id'], saved['id'])
                self.assertEqual(run['demo_original']['id'], saved['id'])
                self.assertEqual(run['draft'], saved['draft'])
                self.assertEqual(run['mode'], 'development_revision')
                self.assertEqual(run['model_calls'], [])
                self.assertEqual(run['review']['source'], 'development_revision')
                self.assertEqual(workbench.notes(run['id']), [])
                self.assertFalse(run['valuation']['pe_basis']['reviewed'])
                prepared = exporting.prepare_run(run)
                self.assertEqual(prepared['draft'], saved['draft'])
                self.assertEqual(prepared['model_calls'], [])
                self.assertEqual(prepared['audit']['model_attempts'], [])
                self.assertEqual(prepared['human_review']['confirmed'], 0)
                self.assertEqual(prepared['human_review']['notes'], [])
                self.assertEqual(prepared['comparison_checks'], [])
                self.assertEqual(prepared['decision']['status'], '暂缓投资判断')
                complete.assert_not_called()
                network.assert_not_called()
        self.assertEqual(path.read_text(encoding='utf-8'), saved_text)


if __name__ == '__main__':
    unittest.main()
