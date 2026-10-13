"""Report views retain unresolved issues and the original saved research."""
import copy
import unittest
from unittest.mock import patch

import core
import exporting
import research
import valuation


class FeedbackExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.ensure_index()

    def setUp(self):
        with patch('core.save_run'):
            self.run_record=research.run('000333','2026-10-06','美的2026年上半年经营与现金流核验','local')

    def test_historical_view_is_idempotent_and_never_rewrites_saved_draft(self):
        old=copy.deepcopy(self.run_record)
        old.pop('decision',None)
        old.pop('investment_profile',None)
        original=copy.deepcopy(old)
        first=exporting.prepare_run(old)
        second=exporting.prepare_run(first)
        self.assertEqual(old,original)
        self.assertTrue(first['decision']['review_status']['compatibility_view'])
        self.assertTrue(second['decision']['review_status']['compatibility_view'])
        self.assertIsNone(second['decision_at_generation'])
        self.assertEqual(first['draft'],original['draft'])
        self.assertEqual(first['markdown'],original['markdown'])
        self.assertEqual(first['decision'],second['decision'])

    def test_brief_and_full_keep_identical_decision_and_all_material_risks(self):
        run=copy.deepcopy(self.run_record)
        run['draft']['thesis'][0]['text']='应收账款较期初增长53.16%，高于营收同比增长3.55%，说明回款质量恶化。'
        run['review']['issues']=[{'severity':'高','claim':'必须保留的未决核验项','reason':'证据尚未补齐','citations':['E1']}]
        for view in ['brief','full']:
            html=exporting.memo_html(run,view)
            md=exporting.memo_markdown(run,view)
            for text in [html,md]:
                self.assertIn('暂缓投资判断',text)
                self.assertIn('必须保留的未决核验项',text)
                self.assertIn('基期不同',text)
                self.assertIn(run['draft']['risks'][0]['text'],text)
                self.assertIn('E1',text)
        self.assertNotIn('财务解剖与口径',exporting.memo_html(run,'brief'))
        self.assertIn('财务解剖与口径',exporting.memo_html(run,'full'))

    def test_html_escapes_profile_basis_and_issue_text(self):
        run=copy.deepcopy(self.run_record)
        run['investment_profile']={'goal':'<img src=x onerror=alert(1)>','horizon_months':12}
        run['review']['issues']=[{'severity':'高','claim':'<script>alert(2)</script>','reason':'待复核','citations':[]}]
        run['valuation']=valuation.calculate({'assumptions':{'pe_basis':'<svg onload=alert(3)>'}})
        for view in ['brief','full']:
            text=exporting.memo_html(run,view)
            self.assertNotIn('<script>alert(2)</script>',text)
            self.assertNotIn('<img src=x',text)
            self.assertNotIn('<svg onload=',text)
            self.assertIn('&lt;img',text)
            self.assertIn('&lt;script&gt;',text)
            self.assertIn('&lt;svg',text)

    def test_both_views_use_same_market_price_and_valuation_basis(self):
        run=copy.deepcopy(self.run_record)
        context=valuation.context('000333','2026-10-06')
        shares=context['reported_shares']
        run['valuation']=valuation.calculate({'assumptions':{'shares_yi':shares['total_yi'],'shares_source_id':shares['source_id'],
            'pe_basis':'历史及同行倍数尚待金融同学核验','pe_basis_reviewed':False}})
        for view in ['brief','full']:
            for render in [exporting.memo_html,exporting.memo_markdown]:
                text=render(run,view)
                self.assertIn('2026-09-30',text)
                self.assertIn('不是官方当前PE',text)
                self.assertIn('历史及同行倍数尚待金融同学核验',text)
                self.assertIn('尚未完成人工复核',text)

    def test_refresh_keeps_generation_decision_separate_from_current_notes(self):
        run=copy.deepcopy(self.run_record)
        before=copy.deepcopy(run['decision'])
        with patch('workbench.notes',return_value=[{'claim_id':'thesis:0','state':'refuted','note':'核对原件发现反证','updated_at':'2026-10-12'}]):
            view=exporting.prepare_run(run)
        self.assertEqual(view['decision_at_generation'],before)
        self.assertEqual(view['decision']['review_status']['refuted_theses'],1)
        self.assertEqual(run['decision'],before)

    def test_invalid_view_is_rejected(self):
        for render in [exporting.memo_html,exporting.memo_markdown]:
            with self.assertRaises(ValueError):render(self.run_record,'unexpected')


if __name__=='__main__':unittest.main()
