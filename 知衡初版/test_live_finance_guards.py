"""Original-row guards derived from the c30a0bb56179 financial audit."""
import copy
import unittest

import core
import decision


def packet(text,refs=None,unit='千元'):
    scale=1000 if unit=='元' else 1
    def amount(value):return f'{value*scale:,}'
    age=f'金额单位为人民币{unit}\n应收账款\n账龄 期末数 期初数\n一年以内 {amount(61292625)} {amount(39882419)}\n一到二年 {amount(1370996)} {amount(937373)}\n'
    return {'draft':{'summary':'营收同比3.55%。','thesis':[{'id':'T1','text':text,'citations':refs or ['E8']}]},
            'financial_depth':{'segments':[{'group':'地区','label':'海外','change_pct':'5.54'},
                                           {'group':'地区','label':'国内','change_pct':'2.07'}]},
            'evidence':[{'citation':'E8','source_id':'REPORT','pdf_page':52,'text':'国内 2.07%\n海外 5.54%'},
                        {'citation':'E13','source_id':'REPORT','pdf_page':148,'text':'金额单位为人民币千元\n境外业务组合 34,055,407 1.05%'},
                        {'citation':'E26','source_id':'REPORT','pdf_page':147,'text':age},
                        {'citation':'E14','source_id':'REPORT','pdf_page':98,'text':'合并及公司利润表\n金额单位为人民币千元\n信用减值损失 (606,402) (346,377)\n资产减值损失 (1,652,869) (366,345)\n公允价值变动收益/(损失) 四(56) 4,997,108 (1,369,697)\n投资收益 四(57) 3,040,102 645,870\n其他收益 四(59) 1,482,928 1,395,801'},
                        {'citation':'E16','source_id':'REPORT','pdf_page':8,'text':'非经常性损益项目及金额\n合计6,850,858'}]}


def rules(run):return {i['rule']:i for i in decision.comparison_checks(run)}


class LiveFinanceGuardTests(unittest.TestCase):
    def test_regional_gap_wrong_suggestion_is_checked_against_registered_values(self):
        p=packet('海外增速5.54%快于国内2.07%，两者增速差约1个百分点量级。')
        before=copy.deepcopy(p)
        finding=rules(p)['regional_growth_gap_mismatch']
        self.assertEqual(finding['severity'],'高')
        self.assertIn('3.47个百分点',finding['reason'])
        self.assertEqual(p,before)
        p['draft']['thesis'][0]['text']='海外增速5.54%快于国内2.07%，两者增速差3.47个百分点。'
        self.assertNotIn('regional_growth_gap_mismatch',rules(p))
        p['draft']['thesis'][0]['text']='海外增速5.54%快于国内2.07%，两者增速差约3.5个百分点。'
        self.assertNotIn('regional_growth_gap_mismatch',rules(p))

    def test_unrelated_growth_difference_and_absent_context_do_not_invent_facts(self):
        p=packet('智能家居与工业技术两者增速差约1个百分点。')
        self.assertNotIn('regional_growth_gap_mismatch',rules(p))
        p['draft']['thesis'][0]['text']='海外增速快于国内，两者增速差约1个百分点。'
        p.pop('financial_depth')
        self.assertNotIn('regional_growth_gap_mismatch',rules(p))

    def test_wrong_age_page_points_to_supplied_labelled_row(self):
        p=packet('应收一年以内612.93亿元、一至二年13.71亿元[E13]。',['E13'])
        finding=rules(p)['receivables_age_amount_wrong_citation']
        self.assertEqual(finding['severity'],'高')
        self.assertIn('E26物理第147页',finding['reason'])
        self.assertEqual(sum(i['rule']=='receivables_age_amount_wrong_citation' for i in decision.comparison_checks(p)),1)

    def test_correct_age_rows_are_supported_with_yuan_or_thousand_yuan_units(self):
        for unit in ['千元','元']:
            with self.subTest(unit=unit):
                p=packet('账龄一年以内612.93亿元、一至二年13.71亿元[E26]。',['E26'],unit)
                self.assertNotIn('receivables_age_amount_wrong_citation',rules(p))
                self.assertNotIn('receivables_age_amount_support_pending',rules(p))

    def test_matching_number_elsewhere_is_not_support_and_unknown_units_are_not_inferred(self):
        p=packet('账龄一年以内612.93亿元[E13]。',['E13'])
        p['evidence'][1]['text']='金额单位为人民币千元\n现金余额 61,292,625'
        self.assertIn('receivables_age_amount_wrong_citation',rules(p))
        p['evidence'][1]['text']='一年以内 61,292,625 39,882,419'
        self.assertNotIn('receivables_age_amount_wrong_citation',rules(p))
        p.pop('evidence')
        self.assertEqual(rules(p),{})

    def test_loss_direction_not_signed_percentage_is_the_economic_change(self):
        for label in ['信用减值损失','资产减值损失']:
            with self.subTest(label=label):
                p=packet(label+'同比下降，坏账压力减轻。',['E14'])
                self.assertEqual(rules(p)['impairment_loss_direction_reversed']['severity'],'高')
                p['draft']['thesis'][0]['text']=label+'同比-75.07%至6.06亿元。'
                self.assertEqual(rules(p)['signed_impairment_loss_needs_direction']['severity'],'中')
                p['draft']['thesis'][0]['text']=label+'报表带符号同比为-75.07%；损失绝对额扩大，应进一步核验。'
                self.assertNotIn('impairment_loss_direction_reversed',rules(p))
                self.assertNotIn('signed_impairment_loss_needs_direction',rules(p))

    def test_loss_reduction_is_not_flagged_when_absolute_loss_actually_falls(self):
        p=packet('信用减值损失同比减少。',['E14'])
        p['evidence'][3]['text']='信用减值损失 -346,377 -606,402'
        self.assertNotIn('impairment_loss_direction_reversed',rules(p))

    def test_local_same_basis_condition_does_not_inherit_historical_baseline(self):
        p=packet('应收期末较期初+53.16%是历史背景；若同基期应收增速显著高于营收同比增速，触发核验。')
        self.assertNotIn('period_end_vs_start_vs_revenue_yoy',rules(p))
        p['draft']['thesis'][0]['text']='跟踪同基期应收同比、周转天数，与2026H1期末较期初53.16%比较；若同基期应收增速高于营收增速，触发复核。'
        self.assertNotIn('period_end_vs_start_vs_revenue_yoy',rules(p))
        self.assertEqual(rules(p)['receivables_monitoring_baseline_ambiguous']['severity'],'中')
        p['draft']['thesis'][0]['text']='同基期应收同比不能与期末较期初53.16%比较。'
        self.assertNotIn('receivables_monitoring_baseline_ambiguous',rules(p))

    def test_future_same_basis_qualifier_cannot_clear_a_real_prior_mixup(self):
        p=packet('应收较期初53.16%高于营收同比3.55%，未来同基期应收增速高于营收时再核验。')
        self.assertIn('period_end_vs_start_vs_revenue_yoy',rules(p))

    def test_income_statement_amounts_cannot_all_be_called_nonrecurring(self):
        p=packet('待核验非经常性损益各项目（公允价值变动收益49.97亿元、投资收益30.40亿元、其他收益14.83亿元）。',['E14','E16'])
        self.assertIn('income_statement_items_not_all_nonrecurring',rules(p))
        p['draft']['thesis'][0]['text']='利润表公允价值变动收益49.97亿元、投资收益30.40亿元，不能直接等同非经常性损益各项目。'
        self.assertNotIn('income_statement_items_not_all_nonrecurring',rules(p))
        p['draft']['thesis'][0]['text']='非经常性损益各项目包括特定工具公允价值及投资损益合计67.46亿元。'
        self.assertNotIn('income_statement_items_not_all_nonrecurring',rules(p))

    def test_saved_pe_results_are_distinct_from_basis_and_missing_dcf(self):
        p=packet('PE情景下的估值结果、现金流折现均未完成。')
        p['valuation']={'pe_scenarios':[{'equity_value_yi':'5325.33','per_share_yuan':'69.95'}]}
        self.assertIn('completed_pe_output_called_incomplete',rules(p))
        p['draft']['thesis'][0]['text']='PE情景计算完成，倍数依据尚未完成核验；FCFE未输入所以现金流折现未完成。'
        self.assertNotIn('completed_pe_output_called_incomplete',rules(p))
        p['draft']['thesis'][0]['text']='PE计算完成但DCF尚未完成。'
        self.assertNotIn('completed_pe_output_called_incomplete',rules(p))
        p['draft']['thesis'][0]['text']='如果PE结果未完成，则应先计算。'
        self.assertNotIn('completed_pe_output_called_incomplete',rules(p))
        p.pop('valuation')
        p['draft']['thesis'][0]['text']='PE结果未完成。'
        self.assertNotIn('completed_pe_output_called_incomplete',rules(p))

    def test_explicit_future_amount_assumptions_are_not_audited_as_reported_facts(self):
        p=packet('用户假设：若一年以内余额600亿元则重新核验。',['E13'])
        self.assertNotIn('receivables_age_amount_support_pending',rules(p))
        p['draft']['thesis'][0]['text']='情景设定海外未来5%、国内4%，两者增速差1个百分点。'
        self.assertNotIn('regional_growth_gap_mismatch',rules(p))


class SavedLiveFinanceGuardTests(unittest.TestCase):
    def test_c30_record_reproduces_new_guards_and_downgrades_ambiguous_monitoring(self):
        try:run=core.get_run('c30a0bb56179')
        except (KeyError,OSError):
            import json
            snapshot=core.APP/'demo/case_model_v05_first.json'
            if not snapshot.is_file():self.skipTest('Local record and public raw snapshot are unavailable.')
            run=json.loads(snapshot.read_text('utf-8'))
        found=rules(run)
        for name in ['regional_growth_gap_mismatch','receivables_age_amount_wrong_citation',
                     'signed_impairment_loss_needs_direction','income_statement_items_not_all_nonrecurring',
                     'completed_pe_output_called_incomplete']:
            self.assertIn(name,found)
        self.assertNotIn('period_end_vs_start_vs_revenue_yoy',found)
        self.assertEqual(found['receivables_monitoring_baseline_ambiguous']['severity'],'中')
        before=copy.deepcopy(run)
        self.assertEqual(decision.build(run)['status'],'暂缓投资判断')
        self.assertEqual(run,before)


if __name__=='__main__':unittest.main()
