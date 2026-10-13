"""A restored run must retain its recorded audit without inventing new attempts."""
import copy
import unittest
from unittest.mock import patch
import exporting


class HistoricalAuditTests(unittest.TestCase):
    def test_restore_preserves_generation_audit_separately(self):
        history={'available':True,'event_count':100,'model_attempts':[{'status':'success'}]}
        run={'id':'restored','demo_original':{'id':'original'},'audit':history,'decision':{'status':'暂缓投资判断'}}
        before=copy.deepcopy(run)
        current={'available':False,'event_count':0,'model_attempts':[],'historical_note':'无当前记录'}
        with patch('workbench.quality',return_value={}),patch('decision.comparison_checks',return_value=[]),patch('decision.build',return_value={}),patch('audit.snapshot',return_value=current):
            result=exporting.prepare_run(run)
        self.assertEqual(result['audit_at_generation'],history)
        self.assertEqual(result['audit']['model_attempts'],[])
        self.assertIn('没有发起新的模型请求',result['audit']['historical_note'])
        self.assertEqual(run,before)
