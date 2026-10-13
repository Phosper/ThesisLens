"""Regressions for the finance review's reasoning errors and decision gates."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import decision
import research


def complete_run():
    return {'mode': 'llm', 'cutoff': '2026-10-06',
            'investment_profile': {'goal': '评估中期投资价值', 'horizon_months': 12,
                                   'budget_yuan': '10000', 'max_loss_pct': '20'},
            'draft': {'summary': '营收同比增长3.55%[E1]。',
                      'thesis': [{'id': 'T1', 'text': '待验证：后续主营利润增长有持续性。', 'citations': ['E1']}],
                      'risks': [], 'invalidation': [{'text': '同口径利润持续下滑时重新评估。', 'citations': ['E1'], 'thesis_ids': ['T1']}],
                      'monitoring': [], 'open_questions': []},
            'evidence': [{'citation': 'E1', 'source_id': 'REPORT', 'locator': 'PDF第1页'}],
            'review': {'summary': '仍需人工核验', 'issues': []},
            'human_review': {'notes': [{'claim_id': 'thesis:0', 'state': 'confirmed', 'note': '已核对原页与论据支持边界。'}]},
            'valuation': {'assumptions': {'shares_yi': '10'},
                          'market_pe': {'available': True, 'pe': '12'},
                          'pe_basis': {'text': '已登记可比样本与口径。', 'reviewed': True, 'status': 'user_reviewed'},
                          'pe_scenarios': [{'label': '谨慎', 'pe': '8', 'equity_value_yi': '100', 'per_share_yuan': '10',
                                            'price_return_pct': '-5', 'total_return_pct': '-3'}]}}


class DecisionFeedbackTests(unittest.TestCase):
    def test_mixed_balance_and_revenue_bases_block_in_all_sections(self):
        for section in decision.SECTIONS:
            run = complete_run()
            run['draft'][section] = [{'text': '应收账款较期初增长53.16%，增幅高于营收同比3.55%，说明回款恶化。',
                                     'citations': ['E1'], 'id': 'T1', 'thesis_ids': ['T1']}]
            before = copy.deepcopy(run['draft'])
            checks = decision.comparison_checks(run)
            self.assertTrue(any(row['rule'] == 'period_end_vs_start_vs_revenue_yoy' for row in checks), section)
            self.assertEqual(checks[0]['severity'], '高')
            self.assertEqual(run['draft'], before)
            self.assertEqual(decision.build(run)['status'], '暂缓投资判断')

    def test_implicit_revenue_yoy_and_summary_are_checked(self):
        run = complete_run()
        run['draft']['thesis'][0]['text'] = '应收账款较期初增长53.16%，增幅高于营收+3.55%，后续需验证。'
        self.assertTrue(decision.comparison_checks(run))
        run['draft']['summary'] = '应收环比53.16%超过营收同比3.55%，回款风险加剧。'
        self.assertTrue(any(row['section'] == 'summary' for row in decision.comparison_checks(run)))

    def test_warning_and_same_basis_comparisons_are_not_errors(self):
        for text in ['应收较期初增长53.16%，不能与营收同比3.55%直接比较，更不能说前者高于后者。',
                     '应收同比增长8%，高于同期间营收同比3.55%；需进一步核验。',
                     '应收较期初增长53.16%；营收同比3.55%。两种数据分别展示。']:
            run = complete_run()
            run['draft']['thesis'][0]['text'] = text
            self.assertEqual(decision.comparison_checks(run), [], text)

    def test_denial_of_causality_does_not_erase_mixed_comparison(self):
        run = complete_run()
        run['draft']['thesis'][0]['text'] = '应收较年初增速高于营收同比，但无法证明回款恶化。'
        self.assertTrue(decision.comparison_checks(run))

    def test_implicit_contrast_and_unrelated_negation_cannot_hide_mixup(self):
        for text in ['应收较期初增加53.16%，而营收同比仅增长3.55%，反映客户回款恶化。',
                     '应收较期初增速高于营收同比，说明回款恶化。存货与营业收入不能直接比较。']:
            run = complete_run()
            run['draft']['thesis'][0]['text'] = text
            self.assertTrue(decision.comparison_checks(run), text)

    def test_classification_explanation_does_not_prove_stability(self):
        run = complete_run()
        run['draft']['thesis'][0]['text'] = '扣非下滑为汇兑与衍生收益分类所致，若剔除该分类影响核心盈利能力应更稳定，但资产减值影响尚需验证。'
        checks = decision.comparison_checks(run)
        self.assertEqual(checks[0]['rule'], 'classification_does_not_prove_core_profit_stability')
        self.assertEqual(decision.build(run)['status'], '暂缓投资判断')

    def test_explicit_stability_gap_is_not_reported_as_an_assertion(self):
        for text in ['分类解释无法证明核心盈利稳定，须量化调节并核验。',
                     '汇兑损益分类说明不能推出核心利润改善。',
                     '分类影响之外，核心盈利是否稳定仍待验证。']:
            run = complete_run()
            run['draft']['thesis'][0]['text'] = text
            self.assertEqual(decision.comparison_checks(run), [], text)

    def test_stability_assertion_and_explicit_limited_hypothesis_have_separate_scope(self):
        run = complete_run()
        run['draft']['thesis'][0]['text'] = '若剔除汇兑分类影响核心盈利能力应更稳定，但资产减值拖累尚待核验。'
        self.assertTrue(decision.comparison_checks(run))
        run['draft']['thesis'][0]['text'] = '若剔除汇兑分类影响核心盈利可能更稳定；这仅是待验证推测，尚缺量化利润调节桥，不能据此作投资判断。'
        self.assertEqual(decision.comparison_checks(run), [])

    def test_saved_real_case_keeps_known_b01_and_t2_gates(self):
        run = json.loads((Path(__file__).parent / 'demo' / 'case_model.json').read_text(encoding='utf-8'))
        rules = {row['rule'] for row in decision.comparison_checks(run)}
        self.assertIn('period_end_vs_start_vs_revenue_yoy', rules)
        self.assertIn('classification_does_not_prove_core_profit_stability', rules)
        view = decision.build(run)
        self.assertEqual(view['status'], '暂缓投资判断')
        self.assertTrue(view['review_status']['compatibility_view'])

    def test_falsifying_a_stability_claim_is_not_asserting_it(self):
        run = complete_run()
        run['draft']['invalidation'][0]['text'] = '若后续逐项利润调节桥显示，扣除汇兑等经常性汇率影响后核心利润同比仍显著为负，则核心盈利稳定判断被推翻；管理层分类解释不能替代量化调节桥。'
        rules = {item['rule'] for item in decision.comparison_checks(run)}
        self.assertNotIn('classification_does_not_prove_core_profit_stability', rules)
        self.assertIn('invalidation_target_not_in_thesis', rules)

    def test_falsification_clause_does_not_hide_another_stability_assertion(self):
        run = complete_run()
        run['draft']['thesis'][0]['text'] = '若汇兑分类桥不足，则核心盈利稳定判断被推翻。分类解释说明核心盈利稳定，因此经营基础稳健。'
        self.assertTrue(any(row['rule']=='classification_does_not_prove_core_profit_stability' for row in decision.comparison_checks(run)))

    def test_confirmed_thesis_cannot_clear_independent_rule_failure(self):
        run = complete_run()
        self.assertEqual(decision.build(run)['status'], '有条件纳入研究候选')
        run['draft']['thesis'][0]['text'] = '应收环比高于营收同比，说明经营恶化。'
        self.assertEqual(decision.build(run)['status'], '暂缓投资判断')

    def test_pending_and_refuted_human_claims_block_the_decision(self):
        for state in ['pending', 'refuted']:
            run = complete_run()
            run['human_review']['notes'][0]['state'] = state
            self.assertEqual(decision.build(run)['status'], '暂缓投资判断')
        run = complete_run()
        run['human_review']['notes'][0]['note'] = ''
        self.assertEqual(decision.build(run)['review_status']['pending_theses'], 1)

    def test_scenario_loss_exceeding_user_tolerance_blocks_even_reviewed_case(self):
        run = complete_run()
        run['investment_profile']['max_loss_pct'] = 10
        run['valuation']['pe_scenarios'][0]['total_return_pct'] = '-39.59'
        view = decision.build(run)
        self.assertEqual(view['status'], '暂缓投资判断')
        self.assertTrue(any('谨慎情景总回报-39.59%超出' in item for item in view['missing']))

    def test_deterministic_checks_trigger_existing_single_revision_when_critic_misses(self):
        import core
        core.ensure_index()
        plan = {'questions': [{'topic': '经营', 'query': '营业收入'}], 'hypotheses': [], 'missing': []}
        bad = copy.deepcopy(complete_run()['draft'])
        bad['thesis'][0]['text'] = '应收较期初增速高于营收同比，说明回款恶化。'
        good = copy.deepcopy(bad)
        good['thesis'][0]['text'] = '应收较期初变化不能与营收同比直接比较，仍需同口径核验。'
        review = {'summary': '仍待人工核验', 'issues': []}
        log = {'provider': 'test', 'model': 'test'}
        with patch('model.complete', side_effect=[(plan, log), (bad, log), (review, log), (good, log), (review, log)]) as complete, patch('core.save_run'):
            run = research.run('000333', '2026-10-06', '美的2026年上半年应收与营收核验', 'llm')
        self.assertEqual(complete.call_count, 5)
        self.assertEqual(run['previous_review']['model_review'], review)
        self.assertTrue(run['previous_comparison_checks'])
        self.assertEqual(run['comparison_checks'], [])
        self.assertEqual(run['draft']['thesis'][0]['text'], good['thesis'][0]['text'])
        self.assertIn('投资判断与执行条件', run['markdown'])

    def test_missing_sources_and_unreviewed_pe_cannot_produce_a_candidate(self):
        run = complete_run()
        run['evidence'][0].pop('source_id')
        self.assertEqual(decision.build(run)['status'], '暂缓投资判断')
        run = complete_run()
        run['valuation']['pe_basis']['reviewed'] = False
        self.assertTrue(any('尚未经' in item for item in decision.build(run)['missing']))

    def test_old_valuation_does_not_invent_a_market_pe_or_return(self):
        run = complete_run()
        del run['investment_profile']
        run['valuation'].pop('pe_basis')
        run['valuation'].pop('market_pe')
        for row in run['valuation']['pe_scenarios']:
            row.pop('price_return_pct')
            row.pop('total_return_pct')
        before = copy.deepcopy(run)
        view = decision.build(run)
        self.assertTrue(view['review_status']['compatibility_view'])
        self.assertIsNone(view['return_scenarios'][0]['price_return_pct'])
        self.assertEqual(run, before)
        self.assertIn('历史记录补充视图', decision.markdown(view, []))

    def test_model_and_deterministic_high_risks_are_not_double_counted(self):
        run = complete_run()
        run['draft']['thesis'][0]['text'] = '应收较期初增速高于营收同比。'
        checks = decision.comparison_checks(run)
        run['review']['issues'] = checks
        self.assertEqual(decision.build(run)['review_status']['unresolved_high'], 1)
        run['review']['issues'].append({'severity': '中', 'claim': '独立估值缺口'})
        self.assertEqual(decision.build(run)['review_status']['unresolved_medium'], 1)

    def test_profile_validation_rejects_invalid_inputs_and_preserves_zero_loss(self):
        for payload in [{'horizon_months': 1.5}, {'horizon_months': True}, {'horizon_months': 61},
                        {'budget_yuan': 0}, {'budget_yuan': 'Infinity'}, {'max_loss_pct': -1},
                        {'max_loss_pct': 'NaN'}, {'goal': []}, {'goal': ''}, []]:
            with self.assertRaises(ValueError, msg=repr(payload)):
                decision.validate_profile(payload)
        profile = decision.validate_profile({'budget_yuan': '123.45', 'max_loss_pct': 0})
        self.assertEqual(profile['budget_yuan'], '123.45')
        self.assertEqual(profile['max_loss_pct'], '0')
        self.assertEqual(profile['horizon_months'], 12)

    def test_invalid_profile_is_rejected_before_model_calls(self):
        with patch('model.complete') as complete:
            with self.assertRaises(ValueError):
                research.run('000333', '2026-10-06', '美的经营表现核验', 'llm',
                             options={'investment_profile': {'budget_yuan': -1}})
        complete.assert_not_called()


if __name__ == '__main__':
    unittest.main()
