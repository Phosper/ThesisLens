"""Meaningful checks: units, periods, date isolation, references, retrieval and export."""
import json
import unittest
from decimal import Decimal
from unittest.mock import patch

import core
import model
import research

class ResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): core.ensure_index()

    def test_units_and_recomputed_yoy(self):
        half=core.metric_rows('2026-H1');annual=core.metric_rows('2025-FY')
        self.assertEqual(len(half),3);self.assertEqual(len(annual),3)
        m=next(r for r in half if r['code']=='000333')
        self.assertEqual(m['revenue_yi'],'2600.42')
        self.assertEqual(m['core_profit_yi'],'195.95')
        self.assertEqual(m['calculations']['core_profit']['computed_yoy'],'-25.31')
        g=next(r for r in half if r['code']=='000651')
        self.assertEqual(g['revenue_yi'],'893.98')
        h=next(r for r in annual if r['code']=='600690')
        self.assertEqual(h['revenue_prior'],'286015294936.52')

    def test_no_future_disclosures(self):
        cutoff='2026-05-01'
        rows=core.search('2026半年营业收入现金流','000333',cutoff,30)
        self.assertTrue(rows)
        self.assertTrue(all(r['publication_date']<=cutoff for r in rows))
        self.assertEqual(core.metric_rows('2026-H1',cutoff),[])
        self.assertEqual(core.available_period('000333',cutoff),'2026-Q1')
        self.assertTrue(all(r['day'][:10]<=cutoff for r in core.prices('000333',cutoff)['data']))

    def test_chinese_alias_and_company_filter(self):
        rows=core.search('美的2026上半年营收利润现金流','000333',limit=10,period='2026-H1',include_industry=False)
        self.assertTrue(rows)
        self.assertTrue(all(r['stock_code']=='000333' for r in rows))
        self.assertTrue(any('营业收入' in r['text'] and '现金流量净额' in r['text'] for r in rows))

    def test_rejects_unknown_references(self):
        with self.assertRaises(ValueError):
            research.validate_draft({'summary':'test','thesis':[{'text':'claim','citations':['E999']}]},[{'citation':'E1'}])

    def test_local_result_has_calculations_and_exportable_references(self):
        with patch('core.save_run') as save:
            result=research.run('000333','2026-10-06','美的2026年上半年经营表现和扣非利润','local')
        self.assertEqual(result['period'],'2026-H1');self.assertFalse(result['model_calls']);save.assert_called_once()
        allowed={e['citation'] for e in result['evidence']}
        self.assertTrue(all(ref in allowed for key,_ in research.SECTIONS for row in result['draft'][key] for ref in row['citations']))
        self.assertTrue(all(e['publication_date']<=result['cutoff'] for e in result['evidence']))
        self.assertIn('PDF第7页',result['markdown']);self.assertIn('2600.42',result['markdown'])
        self.assertEqual([row['step'] for row in result['trace']],list(range(1,len(result['trace'])+1)))
        self.assertTrue(any('投资判断' in row['title'] for row in result['trace']))
        self.assertEqual(result['trace'][-1]['title'],'保存与导出')
        self.assertTrue(result['plan']['questions']);self.assertTrue(result['tool_calls'])

    def test_question_period_is_respected(self):
        with patch('core.save_run'):
            result=research.run('000333','2026-10-06','美的2025年年报现金流风险','local')
        self.assertEqual(result['period'],'2025-FY')
        self.assertTrue(all(m['period']=='2025-FY' for m in result['metrics']))

    def test_latest_retail_release_and_dated_policy(self):
        evidence,_=research.collect_evidence('000333','2026-10-06','美的上半年经营表现','2026-H1')
        self.assertTrue(any(e['source_id']=='IND_010' for e in evidence))
        self.assertTrue(any(e['source_id']=='IND_022' for e in evidence))
        earlier,_=research.collect_evidence('000333','2026-05-01','美的经营表现','2025-FY')
        self.assertFalse(any(e['source_id']=='IND_010' for e in earlier))
        self.assertTrue(all(e['publication_date']<='2026-05-01' for e in earlier))

    def test_model_pipeline_and_critic_without_network(self):
        draft={'summary':'根据财报研究[E1]','thesis':[{'text':'有待核验','citations':['E1']}],
               'risks':[],'invalidation':[],'monitoring':[],'open_questions':[]}
        review={'summary':'仍需人工核验','issues':[]}
        log={'provider':'test','model':'test','usage':{},'response':{}}
        plan={'questions':[{'topic':'现金流','query':'现金流量表补充资料'}],'hypotheses':[],'missing':[]}
        with patch('model.complete',side_effect=[(plan,log),(draft,log),(review,log)]) as complete,patch('core.save_run'):
            result=research.run('000333','2026-10-06','美的2026年上半年经营表现','llm')
        self.assertEqual(complete.call_count,3);self.assertEqual(len(result['model_calls']),3)
        self.assertEqual(result['review']['summary'],'仍需人工核验')

    def test_config_never_returns_secrets_and_rejects_bad_url(self):
        with self.assertRaises(ValueError): model.configure({'base_url':'file:///etc/passwd','model':'test'})
        self.assertNotIn('api_key',model.get_config())
        self.assertNotIn('key',model.get_config())

if __name__=='__main__': unittest.main(verbosity=2)
