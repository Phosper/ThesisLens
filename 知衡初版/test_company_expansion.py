import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import companies
import core
import decision
import financials
import operating_scenarios
import research
import research_requirements
import valuation


class CompanyExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.ensure_index()

    def test_expansion_reports_have_matching_issuer_hashes_and_four_flows(self):
        expansion=json.loads(core.EXPANSION.read_text(encoding='utf-8'))
        self.assertEqual(len(expansion['sources']),6)
        for source in expansion['sources']:
            self.assertEqual(hashlib.sha256(core.file_for(source).read_bytes()).hexdigest(),source['sha256'])
            rows=financials.history(source['stock_code'],'2026-10-06')['data']
            record=next(row for row in rows if row['source_id']==source['source_id'])
            self.assertTrue(all(key in record['fields'] for key in financials.FLOWS))
            self.assertTrue(all(record['fields'][key]['page']<=source['page_count'] for key in financials.FLOWS))
        self.assertFalse(financials.history('002032','2026-03-01')['data'])

    def test_merged_coverage_counts_include_expansion_without_double_counting(self):
        manifest=core.base_manifest();sources=manifest['sources'];stats=manifest['stats']
        pdfs=[s for s in sources if str(s.get('relative_path','')).lower().endswith('.pdf')]
        self.assertEqual(stats['financial_reports'],sum(s['category']=='01_公司财报' for s in sources))
        self.assertEqual(stats['financial_reports'],57)
        self.assertEqual(stats['pdf_count'],len(pdfs))
        self.assertEqual(stats['company_pdfs'],sum(bool(s.get('stock_code')) for s in pdfs))
        self.assertEqual(stats['market_series'],sum(s['category']=='06_市场行情' for s in sources))
        self.assertEqual(stats['by_company']['苏泊尔'],2)
        expansion=json.loads(core.EXPANSION.read_text(encoding='utf-8'))
        expansion['sources'].append(copy.deepcopy(sources[0]))
        with tempfile.TemporaryDirectory(dir=core.DATA) as directory:
            path=Path(directory)/'duplicate_expansion.json'
            path.write_text(json.dumps(expansion,ensure_ascii=False),encoding='utf-8')
            with patch.object(core,'EXPANSION',path):self.assertEqual(core.base_manifest()['stats'],stats)

    def test_new_issuer_ttm_uses_its_own_reported_prior(self):
        for code in ['002032','002508','600060']:
            result=financials.rolling(code,'2026-10-06')
            self.assertTrue(result['available'])
            self.assertEqual(len(result['terms']),3)
            self.assertTrue(all(core.source(t['source_id'])['stock_code']==code for t in result['terms']))
            expected=sum(Decimal(t['value_yuan'])*t['sign'] for t in result['terms'])
            self.assertEqual(Decimal(result['amount_yuan']),expected)

    def test_subsector_focus_changes_research_planning(self):
        small,_=research.make_plan('002032','2026-10-06','查看经营与风险','2026-H1','local')
        kitchen,_=research.make_plan('002508','2026-10-06','查看经营与风险','2026-H1','local')
        self.assertIn('关联交易',small['questions'][1]['query'])
        self.assertIn('工程渠道',kitchen['questions'][1]['query'])
        self.assertNotEqual(small['questions'][1],kitchen['questions'][1])
        self.assertIn('待金融同学确认',research_requirements.context('600060')['owner'])

    def test_private_registration_survives_reload_and_rejects_false_security_code(self):
        with tempfile.TemporaryDirectory(dir=core.DATA) as directory,patch.object(core,'DATA',Path(directory)):
            private=companies.register({'name':'测试资料企业','listed':False,'note':'测试输入，不是真实财务'})
            self.assertFalse(companies.get(private['code'])['listed'])
            companies.refresh()
            self.assertIn(private['code'],core.COMPANIES)
            with self.assertRaises(ValueError):companies.register({'name':'另一家测试企业','listed':False,'code':'123456'})
            with self.assertRaises(ValueError):companies.register({'name':'测试资料企业','listed':False})
            with self.assertRaises(ValueError):valuation.context(private['code'],'2026-10-06')
            requirement=research_requirements.context(private['code'])
            self.assertFalse(any(row['id']=='valuation' for row in requirement['requirements']))
        companies.refresh()


class OperatingScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):core.ensure_index()

    def baseline(self):return operating_scenarios.context('002032','2026-10-06')

    def test_zero_shock_reconciles_to_unrounded_income_less_cost(self):
        base=self.baseline();self.assertTrue(base['available'])
        result=operating_scenarios.calculate(base,{'overseas_scenario_enabled':True,'overseas_revenue_change_pct':0,'overseas_margin_change_pp':0})
        self.assertEqual(Decimal(result['gross_profit_change_yuan']),0)
        self.assertEqual(result['gross_profit_yi'],base['gross_profit_yi'])
        self.assertNotEqual(Decimal(base['gross_margin_pct']),Decimal(base['reported_margin_pct']))

    def test_pressure_is_gross_profit_and_does_not_change_pe_earnings(self):
        assumption={'overseas_scenario_enabled':True,'overseas_revenue_change_pct':-10,'overseas_margin_change_pp':-1}
        result=valuation.calculate({'code':'002032','cutoff':'2026-10-06','assumptions':assumption})
        baseline=valuation.calculate({'code':'002032','cutoff':'2026-10-06','assumptions':{}})
        self.assertLess(Decimal(result['operating_scenario']['gross_profit_change_yuan']),0)
        self.assertEqual(result['pe_scenarios'],baseline['pe_scenarios'])
        self.assertIn('不直接映射',result['operating_scenario']['note'])

    def test_missing_inputs_and_unsupported_period_do_not_become_zero(self):
        for inputs in [{'overseas_scenario_enabled':True}, {'overseas_scenario_enabled':'true'},
                       {'overseas_scenario_enabled':True,'overseas_revenue_change_pct':True,'overseas_margin_change_pp':0},
                       {'overseas_scenario_enabled':True,'overseas_revenue_change_pct':0,'overseas_margin_change_pp':'NaN'}]:
            with self.assertRaises(ValueError):operating_scenarios.calculate(self.baseline(),inputs)
        self.assertFalse(operating_scenarios.context('002032','2026-04-02')['available'])
        self.assertFalse(operating_scenarios.context('002508','2026-10-06')['available'])
        with self.assertRaises(ValueError):operating_scenarios.calculate({'available':False,'reason':'基数缺失'},{'overseas_scenario_enabled':True})

    def test_revision_hash_mismatch_blocks_old_baseline(self):
        manifest=copy.deepcopy(core.manifest())
        for source in manifest['sources']:
            if source['source_id']=='CNINFO_002032_1225522987':source['sha256']='changed'
        with patch('operating_scenarios.core.manifest',return_value=manifest):
            result=self.baseline()
        self.assertFalse(result['available'])
        self.assertIn('重新核对',result['reason'])


if __name__=='__main__':unittest.main()
