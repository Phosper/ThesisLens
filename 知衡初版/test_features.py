import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
import core
import financials
import knowledge
import valuation
import workbench
import research
import exporting
import questions

def isolated_directory():
    folder=tempfile.TemporaryDirectory(dir=core.DATA)
    if not Path(folder.name).resolve().is_relative_to(core.DATA.resolve()):raise AssertionError('Test directory escaped the application data folder')
    return folder

class FinancialFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):core.ensure_index()

    def test_history_complete_and_quarter_cumulative_columns(self):
        rows=financials.history()['data']
        self.assertEqual(len(rows),57)
        self.assertEqual(sum(r['code'] in ['000333','000651','600690'] for r in rows),51)
        self.assertTrue(all(all(k in r['fields'] for k in financials.FLOWS) for r in rows))
        m=next(r for r in rows if r['code']=='000333' and r['period']=='2025-Q3')
        self.assertEqual(m['fields']['revenue']['value'],'363056751')
        self.assertIsNone(m['fields']['revenue']['prior'])
        h=next(r for r in rows if r['code']=='600690' and r['period']=='2025-Q3')
        self.assertEqual(h['fields']['profit']['prior'],'15148238900.50')
        self.assertEqual(h['fields']['profit']['growth'],'14.68')

    def test_cross_page_and_adjusted_base(self):
        h=next(r for r in financials.history()['data'] if r['code']=='600690' and r['period']=='2023-Q1')
        self.assertEqual(h['fields']['cashflow']['page'],2)
        self.assertEqual(h['fields']['profit']['prior'],'3526836008.82')

    def test_ttm_uses_current_reports_comparable_base(self):
        m=financials.rolling('000333','2026-10-06')
        self.assertEqual(m['amount_yuan'],'44377758000')
        self.assertEqual(len(m['terms']),3)
        earlier=financials.rolling('000333','2026-04-01')
        self.assertEqual(earlier['latest_period'],'2025-FY')
        self.assertEqual(earlier['amount_yuan'],'43945411000')

    def test_historical_disclosure_dates_use_verified_corrections(self):
        s=core.source('SINA_000333_8507661')
        self.assertEqual(s['publication_date'],'2022-08-31')
        self.assertEqual(s['date_correction']['original_publication_date'],'2026-08-29')
        self.assertTrue(any(r['source_id']==s['source_id'] for r in financials.history('000333','2022-09-01')['data']))
        self.assertFalse(any(r['source_id']==s['source_id'] for r in financials.history('000333','2022-08-30')['data']))

    def test_pe_uses_unrounded_earnings_and_optional_shares(self):
        result=valuation.calculate({'code':'000333','cutoff':'2026-10-06','assumptions':{}})
        self.assertEqual(result['pe_scenarios'][1]['equity_value_yi'],'5325.33')
        self.assertIsNone(result['pe_scenarios'][1]['per_share_yuan'])
        self.assertFalse(result['dcf']['available'])

    def test_fcfe_discounting_and_sensitivity(self):
        value,rows,tv=valuation.discounted_cashflow(Decimal(10),Decimal(0),Decimal('.1'),Decimal(0),5)
        self.assertAlmostEqual(float(value),100,7)
        with self.assertRaises(ValueError):valuation.calculate({'assumptions':{'fcfe_yi':10,'discount_pct':2,'terminal_pct':2}})
        with self.assertRaises(ValueError):valuation.calculate({'assumptions':{'pe_base':'NaN'}})
        with self.assertRaises(ValueError):valuation.calculate({'assumptions':{'fcfe_yi':10,'years':4.5}})

    def test_supplement_dates_disable_and_references_survive(self):
        with isolated_directory() as tmp,patch.object(knowledge,'DB',Path(tmp)/'library.sqlite3'),patch.object(core,'DATA',Path(tmp)):
            payload={'title':'风险核验测试','publication_date':'2026-10-06','code':'000333','text':'研究工作清单：应核对汇兑损失、经营性应收项目与回款，不能仅根据公司解释直接判断风险消失。'}
            result=knowledge.import_document(payload);sid=result['source_id']
            self.assertTrue(knowledge.search('汇兑损失','000333','2026-10-06',3))
            self.assertFalse(knowledge.search('汇兑损失','000333','2026-09-30',3))
            self.assertTrue(knowledge.import_document(payload)['duplicate'])
            knowledge.set_enabled(sid,False)
            self.assertEqual(knowledge.search('汇兑损失','000333','2026-10-06',3),[])
            self.assertTrue(knowledge.source(sid));self.assertTrue(knowledge.passage(sid))

    def test_source_url_and_financial_period_validation(self):
        with self.assertRaises(ValueError):knowledge.allowed_url('https://127.0.0.1/private')
        with self.assertRaises(ValueError):knowledge.allowed_url('https://nbs.gov.cn.example.org/')
        with self.assertRaises(ValueError):knowledge.import_document({'title':'预测','code':'000333','publication_date':'2026-10-06','period':'2026-FY','text':'x'*40})

    def test_monitor_triggers_review_and_can_be_disabled(self):
        with isolated_directory() as tmp,patch.object(workbench,'DB',Path(tmp)/'workbench.sqlite3'):
            w=workbench.create_watch({'code':'000333','metric':'core_profit_growth','operator':'lt','threshold':-10})
            result=workbench.watchlist('2026-10-06')['data'][0]
            self.assertEqual(result['current_value'],'-25.31');self.assertTrue(result['triggered'])
            workbench.set_watch_enabled(w['id'],False)
            self.assertIsNone(workbench.watchlist('2026-10-06')['data'][0]['triggered'])
            cross=workbench.create_watch({'code':'600690','metric':'cashflow_growth','operator':'lt','threshold':20})
            row=next(r for r in workbench.watchlist('2023-05-01')['data'] if r['id']==cross['id'])
            self.assertEqual(row['page'],2)

    def test_revisions_are_bounded_and_original_review_preserved(self):
        plan={'questions':[{'topic':'经营','query':'营业收入'}],'hypotheses':[],'missing':[]}
        draft={'summary':'事实[E1]','thesis':[{'text':'待核验','citations':['E1']}],'risks':[],'invalidation':[],'monitoring':[],'open_questions':[]}
        bad={'summary':'需要核验','issues':[{'severity':'高','claim':'过度推断','reason':'证据不足','citations':['E1']}]}
        good={'summary':'仍待人工核验','issues':[]};log={'provider':'test','model':'test'}
        with patch('model.complete',side_effect=[(plan,log),(draft,log),(bad,log),(draft,log),(good,log)]) as complete,patch('core.save_run'):
            result=research.run('000333','2026-10-06','美的2026年上半年经营表现','llm')
        self.assertEqual(complete.call_count,5);self.assertEqual(result['previous_review'],bad)
        self.assertEqual(result['review'],good)

    def test_export_escapes_text_and_csv_keeps_source_pages(self):
        with patch('core.save_run'):
            run=research.run('000333','2026-10-06','美的2026年上半年经营表现','local')
        run['draft']['summary']='<script>alert(1)</script>'
        html=exporting.memo_html(run)
        self.assertNotIn('<script>alert(1)</script>',html);self.assertIn('&lt;script&gt;',html)
        text=exporting.financial_csv('600690','2023-05-01')
        self.assertIn('SSE_600690_600690_20230428_6J5C',text)

    def test_question_repairs_format_once_and_keeps_citation_namespace(self):
        good={'text':'事实[Q1_1]','citations':['Q1_1'],'limitations':['仍需人审']};log={'provider':'test','model':'test'}
        with isolated_directory() as tmp,patch.object(workbench,'DB',Path(tmp)/'workbench.sqlite3'),patch('model.complete',side_effect=[({'answer':'错误结构'},log),(good,log)]) as complete:
            result=questions.answer({'question':'美的扣非利润如何？','code':'000333','mode':'llm','cutoff':'2026-10-06'})
        self.assertEqual(complete.call_count,2);self.assertEqual(len(result['model_calls']),2)
        self.assertTrue(all(e['citation'].startswith('Q1_') for e in result['evidence']))

    def test_question_rejects_inline_references_from_main_memo(self):
        bad={'text':'事实[E1]','citations':['Q1_1'],'limitations':[]};log={'provider':'test','model':'test'}
        with isolated_directory() as tmp,patch.object(workbench,'DB',Path(tmp)/'workbench.sqlite3'),patch('model.complete',return_value=(bad,log)) as complete:
            with self.assertRaisesRegex(ValueError,'无法追溯'):questions.answer({'question':'美的扣非利润如何？','mode':'llm','cutoff':'2026-10-06'})
        self.assertEqual(complete.call_count,2)

if __name__=='__main__':unittest.main()
