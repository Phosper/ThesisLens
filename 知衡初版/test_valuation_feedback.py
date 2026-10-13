"""Financial feedback: dated quote ratios, explicit assumptions and return scope."""
import copy
import unittest
from decimal import Decimal
from unittest.mock import patch

import valuation


def context_fixture(profit='44377758000',price='80.1'):
    return {'company':'美的集团','code':'000333','cutoff':'2026-10-06',
            'ttm_profit':{'available':True,'amount_yuan':profit,'amount_yi':valuation.rounded(Decimal(profit)/100000000),'latest_period':'2026-H1'},
            'ttm_cashflow':{'available':True,'amount_yuan':'53617005000'},
            'reported_shares':{'source_id':'REPORT','total_yi':'76.13438907','note':'报告期末已发行股份，未扣库存股；非EPS加权股数'},
            'price':{'date':'2026-09-30','close':price,'source_id':'SAVED_PRICE','share_class':'A','currency':'CNY'} if price is not None else None,
            'notes':[]}


class ValuationFeedbackTests(unittest.TestCase):
    def calculate(self,assumptions=None,ctx=None):
        with patch('valuation.context',return_value=copy.deepcopy(ctx or context_fixture())):
            return valuation.calculate({'code':'000333','cutoff':'2026-10-06','assumptions':assumptions or {}})

    def test_context_does_not_silently_choose_reported_shares(self):
        def rolling(code,cutoff,metric):
            return context_fixture()['ttm_profit' if metric=='profit' else 'ttm_cashflow']
        with patch('valuation.core.validate_cutoff'),patch('valuation.financials.rolling',side_effect=rolling),\
             patch('valuation.core.prices',return_value={'data':[{'day':'2026-09-30','close':'80.1'}],'metadata':{'source_id':'SAVED_PRICE'}}),\
             patch('valuation.financial_depth.snapshot',return_value={'shares':context_fixture()['reported_shares']}):
            ctx=valuation.context('000333','2026-10-06')
        self.assertFalse(ctx['market_pe']['available'])
        self.assertIsNone(ctx['market_pe']['eps_yuan'])
        self.assertEqual(ctx['price']['currency'],'CNY')
        self.assertEqual(ctx['defaults']['pe_basis_reviewed'],False)

    def test_missing_shares_leave_pe_and_returns_unavailable(self):
        result=self.calculate({'dividend_per_share_yuan':'0','fees_pct':'0'})
        self.assertFalse(result['market_pe']['available'])
        self.assertIsNone(result['market_pe']['pe'])
        self.assertIn('尚未选择',result['market_pe']['reason'])
        self.assertEqual(result['pe_scenarios'][1]['equity_value_yi'],'5325.33')
        for scenario in result['pe_scenarios']:
            self.assertIsNone(scenario['per_share_yuan'])
            self.assertIsNone(scenario['price_return_pct'])
            self.assertIsNone(scenario['total_return_pct'])

    def test_reference_pe_uses_raw_ttm_and_selected_share_count(self):
        result=self.calculate({'shares_yi':'76.13438907','shares_source_id':'REPORT','earnings_change_pct':'10'})
        pe=result['market_pe']
        eps=Decimal('44377758000')/Decimal('7613438907')
        self.assertEqual(Decimal(pe['eps_yuan']),eps)
        self.assertEqual(Decimal(pe['pe']),Decimal('80.1')/eps)
        self.assertEqual(pe['price_date'],'2026-09-30')
        self.assertEqual(pe['shares_report_date'],'2026-06-30')
        self.assertEqual(pe['shares_source_id'],'REPORT')
        self.assertIn('未扣库存股',pe['shares_basis'])
        self.assertIn('不是官方当前PE',pe['note'])
        self.assertIn('不共用市场价格',pe['note'])
        # Earnings scenarios may change while the observed TTM reference PE stays fixed.
        self.assertNotEqual(result['pe_scenarios'][1]['earnings_yi'],result['ttm_profit']['amount_yi'])

    def test_zero_or_negative_profit_does_not_generate_pe(self):
        for amount in ['0','-1']:
            with self.subTest(profit=amount):
                ctx=context_fixture(profit=amount)
                reference=valuation.market_pe(ctx,Decimal('76.13438907'))
                self.assertFalse(reference['available'])
                self.assertIsNone(reference['pe'])
                self.assertIn('不适用',reference['reason'])
                with self.assertRaisesRegex(ValueError,'正的盈利基数'):
                    self.calculate({'shares_yi':'76.13438907'},ctx)

    def test_missing_and_unreviewed_basis_remain_an_explicit_gap(self):
        default=self.calculate()
        self.assertEqual(default['pe_basis'],{'text':'','reviewed':False,'status':'missing'})
        self.assertIn('演示默认值',default['pe_scenarios'][1]['assumption_label'])
        unreviewed=self.calculate({'pe_basis':'同行历史PE区间尚待核对'})
        self.assertEqual(unreviewed['pe_basis']['status'],'unreviewed')
        self.assertIn('仍有缺口',unreviewed['pe_scenarios'][1]['assumption_label'])
        missing=self.calculate({'pe_basis_reviewed':True})
        self.assertEqual(missing['pe_basis']['status'],'missing')
        reviewed=self.calculate({'pe_basis':'三档分别参考已核对的可比区间及折价说明','pe_basis_reviewed':True})
        self.assertEqual(reviewed['pe_basis']['status'],'user_reviewed')
        self.assertIn('不代表专家认证',reviewed['pe_scenarios'][1]['assumption_label'])

    def test_total_return_requires_both_explicit_dividend_and_fees(self):
        for optional in [{},{'dividend_per_share_yuan':'2'},{'fees_pct':'0.3'}]:
            with self.subTest(optional=optional):
                scenario=self.calculate(dict(shares_yi='76.13438907',**optional))['pe_scenarios'][1]
                self.assertIsNotNone(scenario['price_return_pct'])
                self.assertIsNone(scenario['total_return_pct'])
        result=self.calculate({'shares_yi':'76.13438907','dividend_per_share_yuan':'2','fees_pct':'0.3'})
        scenario=result['pe_scenarios'][1]
        value=Decimal('44377758000')/Decimal('7613438907')*12
        self.assertEqual(scenario['price_return_pct'],valuation.rounded((value/Decimal('80.1')-1)*100))
        self.assertEqual(scenario['total_return_pct'],valuation.rounded((value+2-Decimal('80.1'))/Decimal('80.1')*100-Decimal('.3')))
        self.assertFalse(scenario['return_assumptions']['taxes_modelled'])
        self.assertEqual(scenario['comparison_price']['date'],'2026-09-30')
        zero=self.calculate({'shares_yi':'76.13438907','dividend_per_share_yuan':0,'fees_pct':0})['pe_scenarios'][1]
        self.assertEqual(zero['total_return_pct'],zero['price_return_pct'])

    def test_return_uses_raw_scenario_not_display_rounded_price(self):
        ctx=context_fixture(profit='104994999.9',price='10')
        result=self.calculate({'shares_yi':'0.01','pe_low':1,'pe_base':1,'pe_high':1},ctx)
        scenario=result['pe_scenarios'][1]
        self.assertEqual(scenario['per_share_yuan'],'104.99')
        self.assertEqual(result['market_pe']['eps_yuan'],'104.9949999')
        self.assertEqual(scenario['price_return_pct'],'949.95')
        self.assertNotEqual(Decimal(result['market_pe']['pe']),Decimal(10)/Decimal('104.99'))
        # Rounding the displayed per-share value first would incorrectly produce 949.90%.
        rounded_first=valuation.rounded((Decimal(scenario['per_share_yuan'])/10-1)*100)
        self.assertNotEqual(scenario['price_return_pct'],rounded_first)

    def test_missing_quote_does_not_invent_return_or_pe(self):
        result=self.calculate({'shares_yi':'76.13438907','dividend_per_share_yuan':2,'fees_pct':0},context_fixture(price=None))
        self.assertFalse(result['market_pe']['available'])
        self.assertIn('没有保存',result['market_pe']['reason'])
        self.assertIsNone(result['pe_scenarios'][1]['price_return_pct'])
        self.assertIsNone(result['pe_scenarios'][1]['total_return_pct'])

    def test_review_flag_is_strict_bool_and_numeric_assumptions_reject_bool(self):
        for value in ['false','true',0,1,None,[]]:
            with self.subTest(reviewed=value),self.assertRaisesRegex(ValueError,'布尔值'):
                self.calculate({'pe_basis_reviewed':value})
        for key in ['dividend_per_share_yuan','fees_pct']:
            for value in [True,False]:
                with self.subTest(key=key,value=value),self.assertRaisesRegex(ValueError,'需要数字'):
                    self.calculate({key:value})
        for key,value in [('pe_basis',True),('fees_pct',-1),('dividend_per_share_yuan',-1)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                self.calculate({key:value})


if __name__=='__main__':unittest.main()
