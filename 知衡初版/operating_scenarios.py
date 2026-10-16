"""A sourced regional gross-profit stress calculation, separate from PE earnings."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re

import core
import financials

NOTE = '仅为同报告期间海外业务毛利压力情景，不是盈利预测；未处理费用、汇兑、套保、税项及少数股东，不直接映射归母利润或PE。'


def number(value, name, low, high):
    if isinstance(value, bool) or value in [None, '']:
        raise ValueError(name + '需要明确数字，0与未填写不同')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(name + '需要有效数字') from None
    if not result.is_finite() or not Decimal(str(low)) <= result <= Decimal(str(high)):
        raise ValueError(name + '超出可接受范围')
    return result


def display(value):
    return str(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def context(code, cutoff):
    core.validate_cutoff(cutoff)
    result = {'available': False, 'reason': '尚未登记本企业当期海外收入及成本原页，不能套用其他企业或期间。', 'note': NOTE}
    path = core.APP / 'operating_baselines.json'
    if not path.exists():
        return result
    period = financials.latest_period(code, cutoff)
    records = json.loads(path.read_text(encoding='utf-8'))['baselines']
    record = next((r for r in records if r['code'] == code and r['period'] == period), None)
    if not record:
        gaps={'002508':'已取得境外收入，尚未登记对应地区成本，不能由收入直接计算海外毛利。',
              '600690':'已取得其他国家/地区收入，尚未登记同口径地区成本；分部总成本不能当作海外营业成本。',
              '600060':'当期半年报未登记地区收入与成本；2025年主营业务境外基数不能套用到2026年半年报。'}
        result['reason']=gaps.get(code,result['reason'])
        return result
    eligible = [s for s in core.manifest()['sources'] if s.get('stock_code') == code
                and s.get('report_period') == period and s['publication_date'] <= cutoff]
    if not eligible:
        return result
    source = max(eligible, key=lambda s: s['publication_date'])
    if source['source_id'] != record['source_id'] or source['sha256'] != record['source_sha256']:
        result['reason'] = '当期原件或修订版与海外经营基数登记不一致，需重新核对。'
        return result
    factor = {'元': Decimal(1), '千元': Decimal(1000), '万元':Decimal(10000)}[record['unit']]
    page=core.page_evidence(source['source_id'],record['pdf_page'])
    compact=re.sub(r'\s+','',(page or {}).get('text','')).replace(',','')
    if any(str(Decimal(record[k])) not in compact for k in ['overseas_revenue','overseas_cost']):
        result['reason']='海外收入或成本登记金额未能匹配原页，暂停使用基数。'
        return result
    revenue = Decimal(record['overseas_revenue']) * factor
    cost = Decimal(record['overseas_cost']) * factor
    if revenue <= 0 or cost<0 or not revenue.is_finite() or not cost.is_finite():
        result['reason'] = '海外收入或成本基数无效。'
        return result
    gross = revenue - cost
    return dict(result, available=True, reason='', code=code, period=period,
                source_id=source['source_id'], source_sha256=source['sha256'],
                publication_date=source['publication_date'], pdf_page=record['pdf_page'],
                revenue_yuan=str(revenue), cost_yuan=str(cost), revenue_yi=display(revenue / 100000000),
                cost_yi=display(cost / 100000000), gross_profit_yi=display(gross / 100000000),
                gross_margin_pct=str(gross / revenue * 100), reported_margin_pct=record['reported_margin_pct'],
                basis=record.get('basis','海外口径按原页收入和成本；毛利率由未舍入原值复算，报告毛利率为显示舍入值。'))


def calculate(baseline, assumptions):
    enabled = assumptions.get('overseas_scenario_enabled', False)
    if type(enabled) is not bool:
        raise ValueError('海外经营情景开关需要布尔值')
    if not enabled:
        return {'available': False, 'reason': '未启用海外经营压力情景。', 'note': NOTE}
    if not baseline.get('available'):
        raise ValueError(baseline.get('reason') or '缺少海外经营基数')
    revenue_change = number(assumptions.get('overseas_revenue_change_pct'), '海外收入变化假设', -100, 300)
    margin_change = number(assumptions.get('overseas_margin_change_pp'), '海外毛利率变化假设（百分点）', -100, 100)
    reason = assumptions.get('overseas_scenario_basis', '')
    if not isinstance(reason, str) or len(reason) > 400:
        raise ValueError('海外情景背景最多400字')
    revenue = Decimal(baseline['revenue_yuan'])
    cost = Decimal(baseline['cost_yuan'])
    margin = (revenue - cost) / revenue * 100
    changed_margin = margin + margin_change
    if not -100 <= changed_margin <= 100:
        raise ValueError('压力情景的毛利率应在-100%至100%之间')
    changed_revenue = revenue * (1 + revenue_change / 100)
    # Algebraically equivalent, without dividing and multiplying the baseline
    # margin: a zero shock must reconcile exactly to original revenue less cost.
    changed_gross = (revenue - cost) * (1 + revenue_change / 100) + changed_revenue * margin_change / 100
    delta = changed_gross - (revenue - cost)
    return {'available': True, 'baseline': baseline,
            'inputs': {'revenue_change_pct': str(revenue_change), 'margin_change_pp': str(margin_change),
                       'basis': reason.strip(), 'classification': '用户假设，未经独立核验'},
            'revenue_yi': display(changed_revenue / 100000000), 'gross_margin_pct': display(changed_margin),
            'gross_profit_yi': display(changed_gross / 100000000), 'gross_profit_change_yi': display(delta / 100000000),
            'gross_profit_change_yuan': str(delta),
            'formula': '情景收入 = 原海外收入 × (1 + 收入变化%)；情景毛利 = 情景收入 × (按收入成本复算的原毛利率 + 毛利率变化百分点)。',
            'note': NOTE}


def markdown(scenario):
    if not scenario or not scenario.get('available'):
        return ''
    base = scenario['baseline']; inputs = scenario['inputs']
    return ('\n## 海外经营压力情景\n'
            f"原海外收入{base['revenue_yi']}亿元，原毛利{base['gross_profit_yi']}亿元；"
            f"期间{base['period']}；{base['source_id']}物理第{base['pdf_page']}页。\n"
            f"用户假设：收入变化{inputs['revenue_change_pct']}%，毛利率变化{inputs['margin_change_pp']}个百分点。"
            f"情景背景：{inputs['basis'] or '未填写，仍为用户设定'}。\n"
            f"情景海外收入{scenario['revenue_yi']}亿元，毛利{scenario['gross_profit_yi']}亿元，毛利变化{scenario['gross_profit_change_yi']}亿元。\n"
            + scenario['formula'] + '\n' + scenario['note'] + '\n')
