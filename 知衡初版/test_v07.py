import copy,json,unittest
from decimal import Decimal
from unittest.mock import patch
import core,financial_depth as depth,financial_notes,research,valuation,operating_scenarios as operating,decision

class CompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):core.ensure_index()

    def test_empty_model_sections_repair_once_and_still_invalid_is_rejected(self):
        good={'summary':'摘要','open_questions':[{'text':'具体资料缺口','citations':[]}]}
        log={'model':'test'};logs=[]
        with patch('model.complete',side_effect=[({'summary':'摘要'},log),(good,log)]) as call:
            draft,_=research.complete_draft('system','context',[],logs,'研究写作')
        self.assertEqual(call.call_count,2);self.assertTrue(draft['open_questions']);self.assertEqual(len(logs),2)
        with patch('model.complete',return_value=({'summary':'摘要'},log)) as call:
            with self.assertRaisesRegex(ValueError,'空章节'):research.complete_draft('system','context',[],[],'研究写作')
        self.assertEqual(call.call_count,2)

    def test_explicit_non_equivalence_does_not_hide_separate_assertion(self):
        denied='非经常性损益与利润表未建立逐项调节桥，不能将分类解释直接等同于核心盈利稳定。'
        def checks(text):return decision.comparison_checks({'draft':{'open_questions':[{'text':text,'citations':[]}]}})
        self.assertFalse(any(i['rule']=='classification_does_not_prove_core_profit_stability' for i in checks(denied)))
        self.assertTrue(any(i['rule']=='classification_does_not_prove_core_profit_stability' for i in checks(denied+'但分类说明核心盈利稳定。')))

    def test_extension_depth_uses_consolidated_balance_and_own_share_units(self):
        p=depth.snapshot('002032','2026-10-06');f=p['fields']
        self.assertEqual(f['receivables']['amount_yuan'],'3194938477.33')
        self.assertEqual(f['assets']['amount_yuan'],str(Decimal(f['liabilities']['amount_yuan'])+Decimal(f['equity']['amount_yuan'])))
        self.assertEqual(depth.snapshot('600060','2026-10-06')['shares']['total'],1304972254)

    def test_hisense_main_business_denominator_and_no_reverse_yoy(self):
        p=depth.snapshot('600060','2026-10-06','2025-FY');r=p['segments'][0]
        self.assertEqual(r['denominator'],'53863967500.00')
        self.assertNotEqual(r['denominator_yi'],p['operating_revenue_yi'])
        self.assertIsNone(r['prior']);self.assertEqual(r['change_pct'],'-3.58')
        self.assertIn('未取得基期',r['growth_basis'])
        half=depth.snapshot('600060','2026-10-06','2026-H1')
        self.assertFalse(any(r['group']=='地区' for r in half['segments']))
        self.assertIn('不套用',half['segment_note'])

    def test_supor_note_pages_are_delivered_without_claiming_non_disclosure(self):
        with patch('core.save_run'):r=research.run('002032','2026-10-06','应收账款与存货、减值和利润调节如何？','local')
        locations={(e['source_id'],e.get('pdf_page')) for e in r['evidence']}
        self.assertTrue(set(financial_notes.locations(r['code'],r['cutoff'],r['period'])).issubset(locations))
        self.assertTrue(all(row['status']=='已定位并取回原页' for row in r['disclosure_coverage']['rows']))
        self.assertIn('不能表述为公司未披露',r['markdown'])
        partial=financial_notes.coverage(r['code'],r['cutoff'],r['period'],[])
        self.assertTrue(all('未取回' in row['status'] for row in partial['rows']))

    def test_note_registration_is_isolated_from_future_and_revised_sources(self):
        self.assertFalse(financial_notes.locations('002032','2026-08-27','2026-H1'))
        self.assertFalse(financial_notes.locations('002032','2026-10-06','2024-H1'))
        manifest=copy.deepcopy(core.manifest());s=copy.deepcopy(core.source('CNINFO_002032_1225522987'))
        s.update(source_id='REVISED',publication_date='2026-09-01');manifest['sources'].append(s)
        with patch('core.manifest',return_value=manifest):self.assertFalse(financial_notes.locations('002032','2026-10-06','2026-H1'))

    def test_new_price_series_have_issuer_bound_snapshot_and_cutoff(self):
        for code,close in [('002032','39.950'),('002508','17.110'),('600060','27.450')]:
            p=core.prices(code,'2026-10-06');self.assertEqual(len(p['data']),1023)
            self.assertEqual(Decimal(str(p['data'][-1]['close'])),Decimal(close))
            self.assertTrue(all(r['day'][:10]<='2026-09-30' for r in p['data']))
            self.assertEqual(p['metadata']['stock_code'],code)
            self.assertFalse(core.prices(code,'2022-07-14')['data'])
            ctx=valuation.context(code,'2026-10-06');sh=ctx['reported_shares']
            v=valuation.calculate({'code':code,'cutoff':'2026-10-06','assumptions':{'shares_yi':sh['total_yi'],'shares_source_id':sh['source_id']}})
            self.assertTrue(v['market_pe']['available']);self.assertEqual(v['market_pe']['price_date'],'2026-09-30')

    def test_scenarios_are_period_specific_and_cost_gaps_stay_unavailable(self):
        for code,cutoff,period in [('000651','2026-10-06','2026-H1'),('002032','2026-04-10','2025-FY'),('600060','2026-04-10','2025-FY')]:
            b=operating.context(code,cutoff);self.assertTrue(b['available']);self.assertEqual(b['period'],period)
            s=operating.calculate(b,{'overseas_scenario_enabled':True,'overseas_revenue_change_pct':0,'overseas_margin_change_pp':0})
            self.assertEqual(Decimal(s['gross_profit_change_yuan']),0)
        for code in ['002508','600060','600690']:self.assertFalse(operating.context(code,'2026-10-06')['available'])

if __name__=='__main__':unittest.main()
