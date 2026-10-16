"""Transparent PE and user-supplied FCFE scenarios; never an automatic rating."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import core
import financials
import financial_depth
import companies
import operating_scenarios

def decimal(value,name,low,high):
    if isinstance(value,bool):raise ValueError(name+'需要数字')
    try:n=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):raise ValueError(name+'需要有效数字') from None
    if not n.is_finite() or not Decimal(str(low))<=n<=Decimal(str(high)):raise ValueError(name+'超出可接受范围')
    return n

def rounded(n,places='.01'):
    return str(n.quantize(Decimal(places),rounding=ROUND_HALF_UP))

def market_pe(ctx,shares=None,assumptions=None):
    """A dated A-share quote divided by TTM earnings per selected share count."""
    p=assumptions or {};price=ctx.get('price') or {}
    result={'available':False,'pe':None,'eps_yuan':None,
            'basis':'A股报价对应的参考PE（期末/输入股数口径）','reason':'',
            'price_date':price.get('date'),'price_yuan':price.get('close'),
            'price_currency':'CNY','price_share_class':'A',
            'shares_yi':str(shares) if shares is not None else None,
            'shares_basis':str(p.get('shares_basis') or '用户输入的普通股分摊数量；尚未独立核验'),
            'shares_report_date':p.get('shares_report_date'),'shares_source_id':p.get('shares_source_id'),
            'formula':'保存A股报价 ÷（未舍入TTM归母净利润 ÷ 所选股数）',
            'note':'这是保存日期的A股人民币报价与所选股数口径的参考值，不是官方当前PE；EPS未采用加权平均股数，未完整处理库存股及潜在稀释。A/H/D各类股份不共用市场价格，不能以A股价乘全部股数认定真实总市值。'}
    profit=ctx.get('ttm_profit') or {}
    if not profit.get('available'):
        result['reason']=profit.get('reason') or 'TTM归母净利润不可用'
        return result
    amount=Decimal(profit['amount_yuan'])
    if amount<=0:
        result['reason']='TTM归母净利润为零或负数，参考PE不适用。'
        return result
    if shares is None:
        result['reason']='尚未选择已核对的股数，暂不计算参考PE或每股盈利。'
        return result
    if not price:
        result['reason']='研究截止日前没有保存的A股人民币报价，暂不计算参考PE。'
        return result
    try:quote=Decimal(str(price.get('close')))
    except (InvalidOperation,ValueError,TypeError):quote=Decimal(0)
    if not quote.is_finite() or quote<=0:
        result['reason']='保存的A股报价无效，暂不计算参考PE。'
        return result
    eps=amount/(shares*100000000)
    result.update(available=True,pe=str(quote/eps),eps_yuan=str(eps))
    return result

def context(code,cutoff):
    if code not in core.COMPANIES:raise ValueError('请选择公司')
    if not companies.get(code)['listed']:raise ValueError('非上市企业当前按资料研究处理，不套用上市公司PE情景')
    core.validate_cutoff(cutoff)
    profit=financials.rolling(code,cutoff,'profit')
    cash=financials.rolling(code,cutoff,'cashflow')
    price_data=core.prices(code,cutoff);prices=price_data['data']
    last=prices[-1] if prices else None
    depth=financial_depth.snapshot(code,cutoff)
    result={'company':core.COMPANIES[code],'code':code,'cutoff':cutoff,'ttm_profit':profit,'ttm_cashflow':cash,
            'reported_shares':depth.get('shares'),'cash_proxy':depth.get('cash_proxy'),
            'price':{'date':last['day'][:10],'close':last['close'],'source_id':price_data['metadata']['source_id'],
                     'share_class':'A','currency':'CNY','basis':'研究截止日前保存的A股人民币报价'} if last else None,
            'defaults':{'pe_low':'8','pe_base':'12','pe_high':'16','earnings_change_pct':'0','shares_yi':'',
                        'pe_basis':'','pe_basis_reviewed':False,'dividend_per_share_yuan':'','fees_pct':'',
                        'fcfe_yi':'','growth_pct':'3','discount_pct':'10','terminal_pct':'2','years':5},
            'notes':['PE倍数是演示假设，没有声称来自行业可比估值。','股数需填已核对的普通股分摊数量；不能用报告EPS反推期末股本。',
                     '股权现金流需单独输入，不能把经营现金流直接当成FCFE。','A/H/D股价格差异、库存股和潜在稀释未完整建模；每股数值仅为所填分母下的情景参考。']}
    result['market_pe']=market_pe(result)
    result['operating_baseline']=operating_scenarios.context(code,cutoff)
    return result

def discounted_cashflow(fcfe,growth,discount,terminal,years):
    if discount<=terminal:raise ValueError('折现率必须高于永续增长率')
    pv=Decimal(0);schedule=[]
    for year in range(1,years+1):
        cash=fcfe*(1+growth)**year;factor=(1+discount)**year;value=cash/factor;pv+=value
        schedule.append({'year':year,'fcfe_yi':rounded(cash),'discount_factor':rounded(factor,'.0001'),'present_value_yi':rounded(value)})
    terminal_cash=fcfe*(1+growth)**years*(1+terminal)
    terminal_value=terminal_cash/(discount-terminal);terminal_pv=terminal_value/(1+discount)**years
    return pv+terminal_pv,schedule,terminal_pv

def calculate(body):
    code=body.get('code','000333');cutoff=body.get('cutoff','2026-10-06');ctx=context(code,cutoff)
    if not ctx['ttm_profit']['available']:raise ValueError(ctx['ttm_profit']['reason'])
    p=body.get('assumptions',{})
    if not isinstance(p,dict):raise ValueError('假设应为对象')
    basis=p.get('pe_basis','')
    if not isinstance(basis,str):raise ValueError('PE倍数依据需要文本')
    reviewed=p.get('pe_basis_reviewed',False)
    if type(reviewed) is not bool:raise ValueError('PE倍数人工复核声明需要布尔值')
    basis=basis.strip()[:2000]
    p=dict(p,pe_basis=basis,pe_basis_reviewed=reviewed)
    operating=operating_scenarios.calculate(ctx.get('operating_baseline') or {'available':False,'reason':'海外经营基数不可用'},p)
    pe_basis={'text':basis,'reviewed':reviewed,
              'status':'missing' if not basis else ('user_reviewed' if reviewed else 'unreviewed')}
    dividend=decimal(p['dividend_per_share_yuan'],'每股期间股利假设',0,10000) if p.get('dividend_per_share_yuan') not in [None,''] else None
    fees=decimal(p['fees_pct'],'总交易费率假设',0,100) if p.get('fees_pct') not in [None,''] else None
    changes=decimal(p.get('earnings_change_pct',0),'盈利变化假设',-95,300)/100
    multiples=[decimal(p.get(k,v),'PE倍数',1,100) for k,v in [('pe_low',8),('pe_base',12),('pe_high',16)]]
    if not multiples[0]<=multiples[1]<=multiples[2]:raise ValueError('PE倍数应按谨慎、基准、乐观递增')
    shares=decimal(p['shares_yi'],'股数（亿股）',.01,10000) if p.get('shares_yi') not in [None,''] else None
    if p.get('shares_source_id'):
        reported=ctx.get('reported_shares')
        if not reported or reported['source_id']!=p['shares_source_id'] or shares!=Decimal(reported['total_yi']):
            raise ValueError('报告期末股数或来源不匹配；请重新核对后选用')
        p=dict(p,shares_basis=reported['note'],shares_report_date=financials.period_end(ctx['ttm_profit']['latest_period']))
    profit=Decimal(ctx['ttm_profit']['amount_yuan'])/100000000;adjusted=profit*(1+changes)
    if adjusted<=0:raise ValueError('PE情景需要正的盈利基数；亏损公司不能套用本模型')
    reference=market_pe(ctx,shares,p)
    quote=Decimal(str(ctx['price']['close'])) if reference['available'] else None
    assumption_label=('用户已声明人工复核倍数依据；该声明不代表专家认证' if pe_basis['status']=='user_reviewed' else
                      '倍数依据尚未人工复核，估值论证仍有缺口' if basis else '演示假设：尚未提供倍数依据，估值论证仍有缺口')
    if not any(k in p for k in ['pe_low','pe_base','pe_high']):
        assumption_label+='；8/12/16倍为演示默认值'
    scenarios=[]
    for label,multiple in zip(['谨慎','基准','乐观'],multiples):
        value=adjusted*multiple
        per_share=value/shares if shares else None
        price_return=(per_share/quote-1)*100 if per_share is not None and quote is not None else None
        total_return=(per_share+dividend-quote)/quote*100-fees if price_return is not None and dividend is not None and fees is not None else None
        scenarios.append({'label':label,'pe':str(multiple),'earnings_yi':rounded(adjusted),'equity_value_yi':rounded(value),
                          'per_share_yuan':rounded(per_share) if per_share is not None else None,'formula':f'{rounded(adjusted,".000001")}亿元 × {multiple}倍',
                          'price_return_pct':rounded(price_return) if price_return is not None else None,
                          'total_return_pct':rounded(total_return) if total_return is not None else None,
                          'comparison_price':ctx['price'],'assumption_label':assumption_label,
                          'price_return_formula':'（未舍入情景每股值 ÷ 保存A股人民币报价 − 1）× 100%',
                          'total_return_formula':'（未舍入情景每股值 + 期间每股股利 − 保存A股人民币报价）÷ 保存A股人民币报价 × 100% − 总交易费率%',
                          'return_assumptions':{'dividend_per_share_yuan':str(dividend) if dividend is not None else None,
                                                'fees_pct':str(fees) if fees is not None else None,'taxes_modelled':False,
                                                'fees_basis':'总交易费用占初始投资额的百分比；直接从价格及股利回报率中扣除',
                                                'note':'情景差额不代表预期收益。期间每股股利与总交易费率均明确输入才计算总回报，税未建模；股利期间及情景兑现时间需人工确认。'}})
    dcf={'available':False,'reason':'尚未输入股权自由现金流FCFE基数；经营现金流不会自动代替FCFE。'}
    if p.get('fcfe_yi') not in [None,'']:
        fcfe=decimal(p['fcfe_yi'],'FCFE基数',.01,10000)
        growth=decimal(p.get('growth_pct',3),'现金流增长率',-50,50)/100
        discount=decimal(p.get('discount_pct',10),'股权资本成本',1,40)/100
        terminal=decimal(p.get('terminal_pct',2),'永续增长率',-5,8)/100
        year_value=decimal(p.get('years',5),'预测年数',3,10)
        if year_value!=year_value.to_integral_value():raise ValueError('预测年数需要整数')
        years=int(year_value)
        value,schedule,terminal_pv=discounted_cashflow(fcfe,growth,discount,terminal,years)
        rates=[discount-Decimal('.02'),discount,discount+Decimal('.02')]
        growths=[terminal-Decimal('.01'),terminal,terminal+Decimal('.01')]
        sensitivity=[]
        for r in rates:
            cells=[]
            for g in growths:
                v=discounted_cashflow(fcfe,growth,r,g,years)[0] if r>g and r>0 else None
                cells.append(rounded(v) if v is not None else None)
            sensitivity.append({'discount_pct':rounded(r*100),'values_yi':cells})
        dcf={'available':True,'equity_value_yi':rounded(value),'per_share_yuan':rounded(value/shares) if shares else None,
             'schedule':schedule,'terminal_value_share_pct':rounded(terminal_pv/value*100),'terminal_growth_columns':[rounded(g*100) for g in growths],
             'sensitivity':sensitivity,'formula':'股权价值 = 各年FCFE折现值之和 + 末年FCFE×(1+永续增长率)/(股权资本成本−永续增长率)的折现值',
             'input_basis':str(p.get('fcfe_basis','用户自行设定的情景假设'))[:500],
             'note':'采用股权现金流折现，直接得到股权价值，未再次加现金或减净债务；这不是FCFF/WACC模型。'}
    return dict(ctx,assumptions=p,assumption_status='用户假设，未经独立验证',pe_basis=pe_basis,market_pe=reference,pe_scenarios=scenarios,dcf=dcf,operating_scenario=operating,
                earnings_formula=f"{ctx['ttm_profit']['amount_yi']} × (1 + {changes*100}%)",
                notes=ctx['notes']+['情景值不是目标价，不形成买卖评级；未经核验的FCFE、倍数与股数会直接影响结果。'])
