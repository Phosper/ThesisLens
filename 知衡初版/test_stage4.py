"""Financial meaning, registered raw facts, unsupported periods and logic-link guards."""
import copy
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
import core
import financial_depth as depth
import financials
import research
import valuation
import exporting
import knowledge
import workbench
import demo_case

class DepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):core.ensure_index()

    def test_twelve_reports_reconcile_current_and_prior_balance_sheets(self):
        self.assertEqual(len(depth.registry()),12)
        for record in depth.registry():
            p=depth.extract(record,core.source(record['source_id']));f=p['fields']
            for key in ['amount_yuan','prior']:
                self.assertEqual(Decimal(f['assets'][key]),Decimal(f['liabilities'][key])+Decimal(f['equity'][key]))
            self.assertTrue(all(f['pdf_page'] in record['balance_pages'] for k,f in f.items() if k!='capex'))

    def test_midea_consolidated_columns_and_cash_outflow_sign(self):
        p=depth.snapshot('000333','2026-10-06','2026-H1');f=p['fields']
        self.assertEqual(f['assets']['amount_yuan'],'643101789000')
        self.assertEqual(f['cash']['value'],'90642783')
        self.assertEqual(f['receivables']['value'],'61954826')
        self.assertEqual(f['inventory']['value'],'55440969')
        self.assertEqual(f['capex']['amount_yuan'],'2634210000')
        self.assertEqual(p['cash_proxy']['amount_yi'],'349.18')
        self.assertIn('不能直接充当FCFE',p['cash_proxy']['note'])

    def test_haier_parent_table_on_same_page_cannot_leak(self):
        p=depth.snapshot('600690','2026-10-06','2026-H1')
        self.assertEqual(p['fields']['cash']['amount_yuan'],'50859093158.21')
        self.assertEqual(p['fields']['inventory']['amount_yuan'],'45317406207.70')
        self.assertEqual(p['fields']['equity']['amount_yuan'],'129375488303.65')

    def test_blank_bond_row_does_not_become_lease_debt(self):
        p=depth.snapshot('000651','2026-10-06','2026-H1')
        self.assertNotIn('bonds',p['fields'])
        self.assertIsNone(depth.row_values('应付债券\n租赁负债 654,153,057.50 652,797,306.31','应付债券'))

    def test_segments_use_external_revenue_and_report_specific_categories(self):
        p=depth.snapshot('600690','2026-10-06','2026-H1')
        products=[x for x in p['segments'] if x['group']=='产品']
        self.assertEqual(products[0]['value'],'89356378603.19')
        self.assertEqual(sum(Decimal(x['value']) for x in products),Decimal('152115050237.63'))
        self.assertEqual(len(products),3)
        annual=depth.snapshot('600690','2026-04-01','2025-FY')
        self.assertEqual(len([x for x in annual['segments'] if x['group']=='产品']),6)
        self.assertEqual(p['shares']['classes'][1]['label'],'境外上市股份（H/D合计）')

    def test_period_and_disclosure_filters_never_borrow_future_or_other_period(self):
        self.assertFalse(depth.snapshot('000333','2026-08-28','2026-H1')['available'])
        self.assertFalse(depth.snapshot('000333','2026-10-06','2024-H1')['available'])
        self.assertEqual(depth.snapshot('000333','2026-04-01')['period'],'2025-FY')
        with self.assertRaises(ValueError):depth.snapshot('bad','2026-10-06')

    def test_changed_raw_hash_and_curated_numbers_are_quarantined(self):
        r=copy.deepcopy(depth.registry()[0]);s=core.source(r['source_id'])
        with self.assertRaises(ValueError):depth.extract(r,dict(s,sha256='changed'))
        r['segments'][0]['value']='123.45'
        with self.assertRaises(ValueError):depth.extract(r,s)

    def test_revised_unregistered_report_does_not_reuse_old_registration(self):
        manifest=copy.deepcopy(core.manifest());s=copy.deepcopy(core.source('CNINFO_000333_1225531404'))
        s.update(source_id='REVISION',publication_date='2026-09-01');manifest['sources'].append(s)
        with patch('core.manifest',return_value=manifest):self.assertFalse(depth.snapshot('000333','2026-10-06','2026-H1')['available'])

    def test_reported_shares_are_exact_and_cannot_be_mislabelled(self):
        c=valuation.context('000333','2026-10-06');sh=c['reported_shares']
        self.assertEqual(sh['total'],7613438907)
        p={'shares_yi':sh['total_yi'],'shares_source_id':sh['source_id']}
        v=valuation.calculate({'code':'000333','cutoff':'2026-10-06','assumptions':p})
        self.assertIn('未扣库存股',v['assumptions']['shares_basis'])
        with self.assertRaises(ValueError):valuation.calculate({'code':'000333','cutoff':'2026-10-06','assumptions':dict(p,shares_yi='1')})

    def test_local_research_reserves_all_depth_pages_and_maps_theses(self):
        with patch('core.save_run'):r=research.run('000333','2026-10-06','2026年上半年应收与存货核验','local')
        selected={(e['source_id'],e.get('pdf_page')) for e in r['evidence']}
        self.assertTrue(set(depth.evidence_locations(r['financial_depth'])).issubset(selected))
        self.assertTrue(all(x['thesis_ids'] for key in ['risks','invalidation','monitoring'] for x in r['draft'][key]))
        self.assertIn('财务解剖与口径',r['markdown'])
        self.assertIn('财务解剖与口径',exporting.memo_html(r))
        self.assertIn('7613438907股',r['markdown'])
        self.assertIn('关联论据 T',exporting.memo_html(r))

    def test_attached_valuation_does_not_overwrite_working_capital_risk(self):
        v=dict(valuation.calculate({'code':'000333','cutoff':'2026-10-06','assumptions':{}}),id='test-valuation')
        with patch('workbench.get_valuation',return_value=v),patch('core.save_run'):
            r=research.run('000333','2026-10-06','2026年上半年利润和营运资本','local',options={'valuation_id':v['id']})
        self.assertTrue(any('期末存货' in row['text'] for row in r['draft']['risks']))
        self.assertFalse(any('估值证据不足' in row['text'] for row in r['draft']['risks']))
        self.assertEqual(r['valuation']['id'],v['id'])

    def test_portable_historical_demo_imports_into_empty_databases_without_model(self):
        with tempfile.TemporaryDirectory(dir=core.DATA) as folder:
            tmp=Path(folder).resolve()
            self.assertTrue(tmp.is_relative_to(core.DATA.resolve()))
            with patch.object(core,'DATA',tmp),patch.object(core,'RUNS',tmp/'runs.sqlite3'),patch.object(knowledge,'DB',tmp/'library.sqlite3'),patch.object(workbench,'DB',tmp/'workbench.sqlite3'),patch('core.save_run',wraps=core.save_run) as save,patch('model.complete',side_effect=AssertionError('No model request for demo')):
                r=demo_case.restore('v04');run=save.call_args.args[0]
                self.assertEqual(len(knowledge.sources()),1)
                self.assertEqual(r['original_run_id'],'8d74405af148')
                self.assertEqual(run['demo_original']['id'],r['original_run_id'])
                self.assertIn('历史大模型',run['mode_label'])
                self.assertIn('历史大模型',core.list_runs()[0]['mode_label'])
                self.assertEqual(workbench.get_valuation(run['valuation']['id'])['id'],run['valuation']['id'])
                for e in run['evidence']:self.assertIsNotNone(core.source(e['source_id']))

    def test_logic_links_reject_nonexistent_thesis(self):
        d={'summary':'摘要','thesis':[{'text':'论据','citations':['E1']}],
           'risks':[{'text':'风险','citations':['E1'],'thesis_ids':['T99']}], 'invalidation':[],'monitoring':[],'open_questions':[]}
        with self.assertRaises(ValueError):research.validate_draft(d,[{'citation':'E1'}])

    def test_csv_keeps_dates_basis_and_physical_pages(self):
        text=depth.export_csv('000333','2026-10-06','2026-H1')
        self.assertTrue(text.startswith('\ufeff'))
        self.assertIn('2026-08-29',text);self.assertIn('期末对比',text);self.assertIn('96',text)

if __name__=='__main__':unittest.main()
