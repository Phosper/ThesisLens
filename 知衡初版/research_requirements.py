"""Development research requirements; data coverage is not an expert sign-off."""
import companies

METHODS = {
    'white_goods': {'focus': '地区与产品结构、渠道结算、营运资本及海外风险',
                   'query': '分地区 分产品 毛利率 现金流 应收账款 存货 汇率 关税'},
    'small_appliance': {'focus': '炊具与电器结构、内外销、渠道与关联交易',
                       'query': '炊具 烹饪电器 内销 外销 毛利率 SEB 关联交易 渠道'},
    'kitchen': {'focus': '厨电品类、零售与工程渠道、地产敞口及回款',
               'query': '吸油烟机 燃气灶 工程渠道 房地产 应收账款 现金流 信用减值'},
    'display': {'focus': '显示产品结构、面板成本、海外业务与产品周期',
                'query': '显示 面板 成本 海外 境外 产品结构 毛利率 研发'},
    'custom': {'focus': '先核对业务结构和披露条件，再选择适用指标',
               'query': '主营业务 分产品 分地区 收入 成本 风险 现金流'},
    'documents': {'focus': '业务与竞争格局、资料出处、风险和信息缺口',
                  'query': '主营业务 产品 客户 竞争 风险 经营 财务披露'},
}

REQUIREMENTS = [
    {'id': 'growth', 'name': '增长与业务结构', 'input': '累计收入、同期间同比、产品和地区结构',
     'check': '金额、单位、合并范围和基期一致；企业分类不同不直接推导市场份额。'},
    {'id': 'profit', 'name': '利润质量', 'input': '归母、扣非、非经常性损益和减值附注',
     'check': '公司解释与量化归因分开；没有利润桥不推出核心盈利稳定。'},
    {'id': 'cash', 'name': '现金流与营运资本', 'input': '经营现金流、应收和存货原页、同口径比较基准',
     'check': '余额变动不与流量同比混比；净额与账面余额、单期与累计分别核对。'},
    {'id': 'external', 'name': '行业与海外变量', 'input': '有披露日期的政策、公司敞口和地区经营数据',
     'check': '统计期间与公司期间分开；定性风险和用户压力情景不写成预测事实。'},
    {'id': 'valuation', 'name': '估值情景', 'input': '可复算盈利基数、用户倍数、适用股数及价格日期',
     'check': '计算完成与假设依据分开；不同股类、亏损、缺数据不得套用。'},
    {'id': 'invalidation', 'name': '反向验证与跟踪', 'input': '明确方向的经营假设、对应反证和同口径指标',
     'check': '反证指向实际论据；历史事实不会被未来变化推翻。'},
]


def context(code):
    profile = companies.get(code)
    if not profile:
        raise ValueError('请选择已登记企业')
    method = METHODS[profile['method']]
    rows = [dict(row) for row in REQUIREMENTS]
    if not profile['listed']:
        rows = [row for row in rows if row['id'] not in ['profit', 'cash', 'valuation']]
        rows.append({'id': 'private_disclosure', 'name': '非上市信息边界',
                     'input': '可引用的业务资料；财务数字需独立原件及明确主体范围',
                     'check': '当前按资料研究处理，不套用上市公司归母、公开交易价格或PE流程。'})
    return {'version': '0.7.0', 'owner': '开发侧提出的研究规范，待金融同学确认',
            'financial_confirmation': '未登记金融需求确认', 'company_profile': profile,
            'focus': method['focus'], 'research_query': method['query'], 'requirements': rows,
            'comparison_note': '参考企业可能跨细分业务，财务对照不自动构成估值可比公司组。',
            'quality_boundary': '检查数据与流程，不声称独立金融准确率或实际投资效果。'}


def coverage(run):
    requirement = run.get('research_requirements')
    if not requirement:
        return None
    mine = next((row for row in run.get('metrics', []) if row['code'] == run['code']), None)
    references = [row['citation'] for row in run.get('evidence', []) if row.get('company') == run['company']]
    depth = run.get('financial_depth') or {}
    valuation = run.get('valuation') or {}
    operating = valuation.get('operating_scenario') or {}
    rows = [
        {'name':'金额附注取回','status':'已记录原页取回情况','detail':'; '.join(r['name']+'：'+r['status'] for r in (run.get('disclosure_coverage') or {}).get('rows',[])) or '该报告尚未登记附注定位；不等于公司未披露。'},
        {'name': '本企业财务主表', 'status': '已提供原值及原页' if mine else '尚未取得完整主表',
         'detail': f"{mine['period']}，四项累计流量" if mine else '不以其他企业数字补齐；资料研究仍可保留原文。'},
        {'name': '资产负债与经营结构', 'status': '已登记原页' if depth.get('available') else '深度原页登记待补',
         'detail': depth.get('verification') if depth.get('available') else depth.get('reason', '尚无登记')},
        {'name': '估值情景', 'status': '已计算用户情景' if valuation else '未附带估值',
         'detail': '倍数依据与分母另行核验。' if valuation else '不因此编造估值或目标价。'},
        {'name': '海外经营压力', 'status': '已计算用户情景' if operating.get('available') else '未计算压力情景',
         'detail': operating.get('note') if operating.get('available') else '定性风险分析与量化情景分别说明。'},
        {'name': '引用支持与金融判断', 'status': '待人工审阅',
         'detail': '有引用不等于论据获得支持；在跟踪与人审中登记依据。'},
    ]
    if not requirement['company_profile']['listed']:
        rows = [{'name': '本企业原文', 'status': '已提供可回看引用' if references else '尚缺本企业原文',
                 'detail': '企业登记是用户说明，具体事实以原文为准。'},
                {'name': '财务与估值适用性', 'status': '资料研究',
                 'detail': '不套用上市公司归母、公开交易报价或PE。'}, rows[-1]]
    return {'rows': rows, 'company_references': references,
            'expert_review': '待人工判断，不由数据齐全自动签认',
            'investment_effect': '未验证，情景回报不代表实际投资收益'}


def markdown(run):
    requirement = run.get('research_requirements')
    if not requirement:
        return ''
    profile = requirement['company_profile']
    lines = ['\n## 研究要求与数据覆盖\n',
             f"企业类型：{profile['segment']}；研究重点：{requirement['focus']}。\n",
             requirement['owner'] + '。' + requirement['comparison_note'] + '\n']
    for row in requirement['requirements']:
        lines.append(f"- {row['name']}：输入需有{row['input']}。核对要求：{row['check']}\n")
    for row in (run.get('research_coverage') or {}).get('rows', []):
        lines.append(f"- {row['name']}：{row['status']}。{row['detail']}\n")
    lines.append(requirement['quality_boundary'] + '\n')
    return ''.join(lines)
