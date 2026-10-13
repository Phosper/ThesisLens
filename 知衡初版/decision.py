"""Deterministic research decisions and comparison guards; no model calls or trading."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

SECTIONS = ('thesis', 'risks', 'invalidation', 'monitoring', 'open_questions')
SCOPE = '依据保存的论据、证据、估值假设与人工核验状态整理；条件化研究结论，不是买卖评级。'


def _number(value, label, minimum, maximum=None, optional=False):
    if optional and value in (None, ''):
        return None
    if isinstance(value, bool):
        raise ValueError(label + '需要有效数字')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(label + '需要有效数字') from None
    if not number.is_finite() or number < minimum or (maximum is not None and number > maximum):
        raise ValueError(label + '超出可接受范围')
    return number


def validate_profile(value=None):
    """Keep user constraints distinct from company facts and computed forecasts."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError('投资目标与约束应为对象')
    goal = value.get('goal', '评估中期投资价值')
    if not isinstance(goal, str) or not 1 <= len(goal.strip()) <= 200:
        raise ValueError('投资目标应为1至200字')
    horizon = _number(value.get('horizon_months', 12), '研究持有期（月）', Decimal(1), Decimal(60))
    if horizon != horizon.to_integral_value():
        raise ValueError('研究持有期（月）需要整数')
    budget = _number(value.get('budget_yuan'), '投入上限（元）', Decimal(0), optional=True)
    if budget is not None and budget <= 0:
        raise ValueError('投入上限（元）应为正数')
    loss = _number(value.get('max_loss_pct'), '最大可接受损失（%）', Decimal(0), Decimal(100), optional=True)
    return {'goal': goal.strip(), 'horizon_months': int(horizon),
            'budget_yuan': str(budget) if budget is not None else None,
            'max_loss_pct': str(loss) if loss is not None else None,
            'assumption_status': '用户研究假设',
            'budget_note': '投入上限由用户提供；金额不构成仓位建议。'}


def _draft_items(run):
    draft = run.get('draft') or {}
    yield 'summary', 'summary', {'text': draft.get('summary', ''), 'citations': re.findall(r'\[(E\d+)\]', draft.get('summary', ''))}
    for section in SECTIONS:
        for index, row in enumerate(draft.get(section, [])):
            if isinstance(row, dict):
                yield section, f'{section}:{index}', row


def _negated_comparison(text, match):
    # Negation must govern this comparator, not an unrelated later warning.
    prefix = text[max(0, match.start() - 24):match.end()]
    suffix = text[match.end():match.end() + 20]
    return bool(re.search(r'(?:不能|不可|不应|无法|不宜)[^。；;]{0,20}(?:高于|超过|快于|大于|更快|跑赢)$', prefix)
                or re.match(r'[^。；;]{0,10}(?:的说法)?(?:不可比|不成立|不能成立|口径不同)', suffix))


def _same_basis_comparison(text, match):
    prefix = re.split(r'[，,]', text[max(0, match.start() - 55):match.start()])[-1]
    return bool(re.search(r'同(?:基期|期间|口径).{0,12}应收.{0,20}(?:同比|增速|增长)', prefix)
                and not re.search(r'较期初|比期初|较年初|期末对期初|环比', prefix))


def _start_basis(text):
    return bool(re.search(r'应收.{0,65}(?:较期初|比期初|对期初|较年初|比年初|对年初|环比|期末对期初)|(?:期末对期初|较期初|较年初|环比).{0,30}应收', text))


_STABILITY_TARGET = r'(?:核心|主营|基础)[^，,。；;\n]{0,8}(?:盈利|利润|经营)[^，,。；;\n]{0,10}(?:稳定|稳健|改善)'


def _has_stability_prediction(text, predicate):
    """Recognise this narrow target, without promoting a disclaimer to a thesis."""
    for match in re.finditer(_STABILITY_TARGET, text):
        if not match.group().endswith(predicate):
            continue
        within = match.group()[:-len(predicate)]
        if re.search(r'是否|能否|不能|无法|尚未|未能|未见|不足以|并非|不代表|尚不能|不(?:会|再|够|太)?(?:保持|维持|持续|继续|恢复|更)?$', within):
            continue
        prefix = re.split(r'[，,；;。\n]', text[max(0, match.start() - 40):match.start()])[-1]
        suffix = re.split(r'[，,；;。\n]', text[match.end():])[0]
        if re.search(r'(?:不能|无法|不足以|尚不能|不代表|未能|尚未).{0,24}(?:证明|说明|判断|推断|推出|确认)|是否|能否', prefix):
            continue
        if re.search(r'^(?:判断)?(?:仍|尚|有)?待(?:核验|验证)|^(?:判断)?(?:不能|无法|不成立|被推翻|被否定)', suffix):
            continue
        return True
    return False


def _future_receivables_baseline_mixed(text):
    """Finite relation check: days/YOY cannot use a start-of-year increase."""
    metric = r'(?:同(?:基期|期间|口径).{0,12}应收.{0,12}(?:同比|增速)|应收.{0,12}(?:同基期|同期).{0,8}(?:同比|增速)|应收(?:账款)?(?:余额|净额)?同比|周转天数)'
    baseline = r'(?:(?:较|比|对)(?:期初|年初)(?:增幅|增速|变动|变化)?|期末对期初)'
    relation = r'不高于|不低于|不超过|不小于|高于|低于|超过|小于|大于|比较|作为.{0,8}基准|作.{0,8}基准'
    for clause in re.split(r'[。；;\n]', text):
        # A semicolon separates an actual assertion from a later disclaimer.
        for pattern in [metric + r'.{0,65}?(?P<relation>' + relation + r').{0,45}?' + baseline,
                        baseline + r'.{0,65}?(?P<relation>' + relation + r').{0,45}?' + metric,
                        metric + r'.{0,40}?' + baseline + r'.{0,35}?(?P<relation>' + relation + r')',
                        baseline + r'.{0,45}?(?P<relation>作为|用作|作).{0,35}?' + metric + r'.{0,35}(?:上限|下限|阈值|基准)']:
            for match in re.finditer(pattern, clause):
                prefix = clause[max(0, match.start('relation') - 45):match.start('relation')]
                suffix = clause[match.end():match.end() + 16]
                if re.search(r'(?:不能|不可|不应|不宜|无法|不得|不直接)[^，,]{0,38}$', prefix):
                    continue
                if re.match(r'[^，,]{0,8}(?:不可比|不成立|口径不同)', suffix):
                    continue
                return True
    return False


def _parsed_number(value):
    try:
        n = Decimal(str(value).replace(',', '').replace('−', '-'))
        return n if n.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _table_values(text, label):
    """Only labelled table rows, never an unrelated occurrence of an amount."""
    match = re.search(r'(?:^|\n)\s*' + label + r'(?=\s|[（(]|[-−\d])', text)
    if not match:
        return []
    content = []
    for index, line in enumerate(text[match.end():].splitlines()[:4]):
        line = re.sub(r'[一二三四五六七八九十]+[（(]\d+[）)]', '', line)
        if index and re.search(r'[\u4e00-\u9fffA-Za-z]', line):
            break
        content.append(line)
    raw = ' '.join(content)
    raw = re.sub(r'[（(]([\d,]+(?:\.\d+)?)[）)]', r'-\1', raw)
    tokens = re.findall(r'[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-−]?\d+(?:\.\d+)?', raw)
    return [n for token in tokens if (n := _parsed_number(token)) is not None]


def _yuan_factor(evidence):
    compact = re.sub(r'\s+', '', evidence.get('text', ''))
    match = re.search(r'单位(?:为|[:：])(?:人民币)?(千元|元)', compact)
    unit = match.group(1) if match else evidence.get('unit')
    return Decimal(1000) if unit == '千元' else (Decimal(1) if unit == '元' else None)


def _display_amount_matches(raw, factor, shown):
    value = _parsed_number(shown)
    if value is None or factor is None:
        return False
    precision = Decimal(1).scaleb(value.as_tuple().exponent)
    return (raw * factor / Decimal(100000000)).quantize(precision, rounding=ROUND_HALF_UP) == value


def _financial_guards(run, text, row):
    """Finite checks supported by the supplied original rows, not keyword audits."""
    evidence = {e.get('citation'): e for e in run.get('evidence', []) if isinstance(e, dict) and e.get('citation')}
    refs = list(dict.fromkeys(list(row.get('citations', [])) + re.findall(r'\[(E\d+)\]', text)))
    cited = [evidence[ref] for ref in refs if ref in evidence]
    regions = {s.get('label'): s for s in (run.get('financial_depth') or {}).get('segments', [])
               if isinstance(s, dict) and s.get('group') == '地区'}
    overseas = _parsed_number(regions.get('海外', {}).get('change_pct'))
    domestic = _parsed_number(regions.get('国内', {}).get('change_pct'))
    for match in re.finditer(r'两者(?:的)?增速差(?:约为|大约|约|为|达)?\s*([+\-]?\d+(?:\.\d+)?)\s*个?百分点', text):
        prefix = text[max(0, match.start() - 180):match.start()]
        local = re.split(r'[。；;]', prefix)[-1]
        if re.search(r'(?:用户假设|假设未来|情景设定).{0,100}(?:海外|国内)', local):
            continue
        if overseas is None or domestic is None or not re.search(r'海外[^。]{0,45}国内|国内[^。]{0,45}海外', prefix):
            continue
        shown = Decimal(match.group(1));actual = abs(overseas - domestic)
        tolerance = Decimal('0.5').scaleb(shown.as_tuple().exponent)
        if abs(shown - actual) > tolerance:
            yield ('regional_growth_gap_mismatch', f'所提供地区收入数据：海外{overseas}%、国内{domestic}%，增速差为{actual}个百分点；“{match.group(0)}”与原值不符，需更正，不能把模型复核建议当成财务来源。', '高')

    age_labels = {'一年以内': r'一年以内', '一至二年': r'一(?:至|到)二年', '一到二年': r'一(?:至|到)二年'}
    for match in re.finditer(r'(一年以内|一至二年|一到二年)(?:(?:账龄|期末|账面余额|余额|金额|为|约为|约|[：:])\s*){0,3}(\d+(?:\.\d+)?)\s*亿(?:元)?', text):
        if not cited:
            continue
        local = re.split(r'[。；;，,]', text[max(0, match.start() - 45):match.start()])[-1]
        if re.search(r'用户假设|若|假设|阈值|情景设定', local):
            continue
        label, shown = match.groups();pattern = age_labels[label]
        supported = any(values and _display_amount_matches(values[0], _yuan_factor(e), shown)
                        for e in cited if (values := _table_values(e.get('text', ''), pattern)))
        if supported:
            continue
        if any(_table_values(e.get('text', ''), pattern) and _yuan_factor(e) is None for e in cited):
            # A labelled row without a monetary unit cannot establish a numerical mismatch.
            continue
        sources = {e.get('source_id') for e in cited if e.get('source_id')}
        alternatives = [e for e in evidence.values() if e.get('source_id') in sources
                        and (values := _table_values(e.get('text', ''), pattern))
                        and _display_amount_matches(values[0], _yuan_factor(e), shown)]
        if alternatives:
            locations = '、'.join(f"{e['citation']}物理第{e.get('pdf_page')}页" for e in alternatives)
            yield ('receivables_age_amount_wrong_citation', f'{label}{shown}亿元未由所引原页的对应账龄行支持；已提供材料中对应行位于{locations}。请修正引用并区分未扣坏账的账面余额和应收净额，不能靠别处出现相同数字证明。', '高')
        elif any(_yuan_factor(e) is not None for e in cited):
            yield ('receivables_age_amount_support_pending', f'所引原页尚未找到可按明确元/千元单位核对的“{label}{shown}亿元”对应账龄行；需补原页，不能仅按数字出现认定支持。', '中')

    for label in ['信用减值损失', '资产减值损失']:
        statement = re.search(re.escape(label) + r'[^。]{0,120}', text)
        if not statement:
            continue
        claim = label + re.split(r'信用减值损失|资产减值损失', statement.group()[len(label):])[0]
        values = next((values for e in cited if len(values := _table_values(e.get('text', ''), re.escape(label))) >= 2), [])
        if len(values) < 2 or values[0] >= 0 or values[1] >= 0 or abs(values[0]) <= abs(values[1]):
            continue
        if re.search(r'绝对(?:额|值)|损失(?:额)?(?:扩大|增加|上升|加重)|由.{0,20}(?:增至|升至)', claim):
            continue
        increased = (abs(values[0]) / abs(values[1]) - 1) * 100
        if re.search(r'(?:减少|下降|收窄|减轻|改善)', claim):
            yield ('impairment_loss_direction_reversed', f'所引损益表{label}为{values[0]}对{values[1]}，损失绝对额实际增加约{increased.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)}%，不能写成损失减少/改善。', '高')
        elif re.search(r'(?:同比|变动|增减)[^%]{0,10}[-−]\d+(?:\.\d+)?%', claim):
            yield ('signed_impairment_loss_needs_direction', f'{label}的负同比来自带符号损益列示；损失绝对额实际扩大约{increased.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)}%。需明确经济方向，避免读成损失减少。', '中')

    income_tables = [e for e in cited if re.search(r'合并(?:及公司)?利润表', e.get('text', '')) and _yuan_factor(e) is not None]
    nonrecurring_claim = re.search(r'非经常性损益(?:各项目|项目|包括|构成)[^。；;]{0,220}', text)
    if nonrecurring_claim and not re.search(r'不能|不等同|并非|不应|口径不同|不代表', nonrecurring_claim.group()):
        named = 0
        for name, table_label in [('公允价值变动收益', r'公允价值变动收益(?:[/／][（(]损失[）)])?'),
                                  ('投资收益', r'投资收益'), ('其他收益', r'其他收益')]:
            amount = re.search(re.escape(name) + r'\s*(\d+(?:\.\d+)?)\s*亿', nonrecurring_claim.group())
            if amount and any(values and _display_amount_matches(values[0], _yuan_factor(e), amount.group(1))
                              for e in income_tables if (values := _table_values(e.get('text', ''), table_label))):
                named += 1
        if named >= 2:
            yield ('income_statement_items_not_all_nonrecurring', '所列金额对应合并利润表完整科目，不能整体称为非经常性损益各项目；需与非经常性损益表逐项映射，排除经常性部分并处理所得税/少数股东影响。', '高')

    scenarios = (run.get('valuation') or {}).get('pe_scenarios') or []
    completed = scenarios and all(s.get('equity_value_yi') is not None and s.get('per_share_yuan') is not None for s in scenarios)
    incomplete = re.search(r'PE[^。，,；;]{0,28}(?:结果|计算)[^。，,；;]{0,18}(?:未完成|没有完成|未计算|没算出)', text, re.I)
    conditional = incomplete and re.search(r'若|如果|假如|除非', text[max(0, incomplete.start() - 12):incomplete.end()])
    distinguishes_dcf = incomplete and re.search(r'(?<!未)完成.{0,4}(?:但|而).{0,8}(?:DCF|FCFE|现金流)', incomplete.group(), re.I)
    if completed and incomplete and not conditional and not distinguishes_dcf and not re.search(r'依据|核验', incomplete.group()):
        yield ('completed_pe_output_called_incomplete', '附带估值已保存PE股权及每股情景计算，不能再称PE结果未完成；应分别说明“计算完成但倍数依据待核验”和“未输入FCFE所以DCF不可用”。', '高')


def comparison_checks(run):
    """Flag risky reasoning without rewriting the saved/model draft.

    These bounded text rules are gates for human review, not a general factual audit.
    """
    items = list(_draft_items(run))
    theses = {row.get('id', f'T{index + 1}'): row for index, row in enumerate((run.get('draft') or {}).get('thesis', []))
              if isinstance(row, dict)}
    revenue_yoy_context = any(re.search(r'(?:营收|营业收入|营业总收入).{0,35}同比|同比.{0,20}(?:营收|营业收入)', row.get('text', '')) for _, _, row in items)
    issues = []
    for section, claim_id, row in items:
        text = row.get('text', '')
        if not isinstance(text, str):
            continue
        thesis_ids = ([row['id']] if section == 'thesis' and row.get('id') else row.get('thesis_ids', []))
        def flag(rule, reason, severity='高'):
            if any(issue['rule'] == rule and issue['claim_id'] == claim_id for issue in issues):
                return
            issues.append({'rule': rule, 'source': 'deterministic', 'severity': severity, 'claim': text, 'reason': reason,
                           'citations': list(row.get('citations', [])), 'thesis_ids': list(thesis_ids),
                           'section': section, 'claim_id': claim_id, 'status': '待人工核验',
                           'blocks_decision': True})
        mixed = False
        clauses = []
        for paragraph in re.split(r'[。！？\n]', text):
            prior_balance = False
            for sentence in re.split(r'[；;]', paragraph):
                local_balance = _start_basis(sentence)
                refers_back = '应收' in sentence or re.match(r'\s*(?:增幅|增速|其增幅|该增幅)', sentence)
                clauses.append((sentence, local_balance or (prior_balance and bool(refers_back))))
                prior_balance = prior_balance or local_balance
        for sentence, sentence_balance in clauses:
            sentence_revenue = bool(re.search(r'营收|营业收入|营业总收入', sentence))
            revenue_yoy = bool(re.search(r'(?:营收|营业收入|营业总收入).{0,35}同比|同比.{0,20}(?:营收|营业收入)', sentence))
            implied_yoy = revenue_yoy_context and bool(re.search(r'(?:营收|营业收入|营业总收入).{0,25}(?:增速|增幅|增长|[+\-]?\d+(?:\.\d+)?%)', sentence))
            explicit = any(not _negated_comparison(sentence, match) and not _same_basis_comparison(sentence, match)
                           for match in re.finditer(r'高于|超过|快于|大于|更快|跑赢', sentence))
            same_basis = bool(re.search(r'同(?:基期|期间|口径).{0,12}应收.{0,20}(?:同比|增速|增长)', sentence))
            contrast = bool(re.search(r'(?:而|却|但).{0,12}(?:营收|营业收入|营业总收入)|(?:营收|营业收入|营业总收入).{0,12}仅', sentence))
            causal = bool(re.search(r'反映|表明|说明|导致|意味着|体现|回款恶化|回款变差', sentence))
            denied_causal = bool(re.search(r'(?:不能|不可|无法|不足以|尚未)[^。；;]{0,15}(?:证明|说明|认定|推断|判断).{0,12}(?:回款|信用|恶化|经营)', sentence))
            if sentence_balance and sentence_revenue and (revenue_yoy or implied_yoy) and (explicit or (contrast and causal and not denied_causal and not same_basis)):
                mixed = True
        if mixed:
            flag('period_end_vs_start_vs_revenue_yoy', '应收期末对期初/年初变动与营收同比的基期不同，不能直接比较增速或据此归因为回款恶化；需补同口径应收同比、周转指标及季节性证据。')
        ambiguous = re.search(r'同基期应收.{0,20}(?:同比|周转天数).{0,35}与.{0,20}(?:较期初|期末对期初).{0,35}比较', text)
        if ambiguous and not re.search(r'不能|不可|不应|不宜|不直接', ambiguous.group()):
            flag('receivables_monitoring_baseline_ambiguous', '跟踪项将同基期应收同比/周转天数与历史期末较期初变动并列为比较基准，指标及基期含糊。应收余额用同年同月同比，周转天数比上年同期间，营收用相应累计同比，分别比较同指标。', '中')
        if _future_receivables_baseline_mixed(text):
            flag('receivables_future_baseline_incompatible', '应收同比百分比、周转天数和期末对期初增幅不是同指标同基期，不能以较期初增幅或其“隐含趋势”设未来同比/周转上限。应收余额用同日期同比并核对范围，周转天数比上年同期间；缺基准时保留待补，不据此判断回款方向。', '中')
        if section == 'invalidation':
            for target in re.finditer(_STABILITY_TARGET + r'[^。；;]{0,20}(?:被推翻|被否定|不成立|失效|需撤回)', text):
                prefix = re.split(r'[，,；;。\n]', text[max(0, target.start() - 30):target.start()])[-1]
                if re.search(r'(?:不能|不得|不应|不要).{0,22}$', prefix):
                    continue
                linked = [theses[tid] for tid in thesis_ids if tid in theses]
                predicate = re.findall(r'稳定|稳健|改善', re.match(_STABILITY_TARGET, target.group()).group())[-1]
                if not linked or not any(_has_stability_prediction(thesis.get('text', ''), predicate) for thesis in linked):
                    flag('invalidation_target_not_in_thesis', '该失效条件撤回的是“核心/主营盈利稳定或改善”，但所关联论据没有提出这一方向，或仅说明不能证明/是否稳定待核验。反证对象须与实际经营假设一致；纯事实、管理层解释和资料缺口应归入待核实问题，不能被改写成更强判断。', '中')
        classification = bool(re.search(r'分类|经常性|汇兑|衍生', text))
        stability_pattern = r'(?:核心|主营|基础).{0,12}(?:盈利|利润|经营).{0,12}(?:应更稳定|更稳定|稳定|稳健|改善)|(?:核心盈利能力|核心利润).{0,8}(?:保持|恢复|证明|说明)'
        for stability in re.finditer(stability_pattern, text) if classification else []:
            # Do not let an unrelated "other factors need verification" erase an assertion.
            prefix = re.split(r'[，,；;。\n]', text[max(0, stability.start() - 24):stability.start()])[-1]
            suffix = re.split(r'[，,；;。\n]', text[stability.end():])[0]
            assertion = prefix + stability.group() + suffix
            denied = bool(re.search(r'(?:无法|不能|不足以|尚不能|不代表|未能|尚未).{0,20}(?:证明|说明|判断|推断|推出|确认)|是否.{0,20}(?:稳定|改善)|(?:稳定|改善).{0,10}(?:仍待|有待|尚待|需要|需进一步).{0,6}(?:核验|验证|量化)|(?:稳定|改善).{0,12}(?:仅为|只是|属于)(?:待验证|待核验|研究)?假设|(?:稳定|改善).{0,12}(?:被推翻|被否定|不成立|失效)', assertion))
            uncertainty = bool(re.search(r'可能|或许|待验证|待核验|研究假设', assertion))
            explicit_limit = bool(re.search(r'(?:这|该|此|上述).{0,8}(?:仅是|仅为|只是|属于).{0,8}(?:待验证|待核验).{0,8}(?:推测|假设)', text[stability.end():])
                                  and re.search(r'(?:不能|不足以|无法).{0,18}(?:投资判断|投资结论)', text[stability.end():]))
            denied = denied or (uncertainty and explicit_limit)
            bridge = run.get('profit_adjustment_bridge') or {}
            quantified = bridge.get('available') is True and bridge.get('reviewed') is True and bool(bridge.get('citations'))
            if not denied and not quantified:
                flag('classification_does_not_prove_core_profit_stability', '汇兑/衍生损益的经常性分类解释不等于核心盈利稳定；尚缺有来源、经人工核验的量化利润调节桥，不能从分类说明直接推出核心利润稳定或改善。')
        for rule, reason, severity in _financial_guards(run, text, row):
            flag(rule, reason, severity)
    return issues


def check_comparisons(draft):
    """Public adapter for export/API preparation; never mutates the input."""
    return comparison_checks({'draft': draft})


def _links(row):
    return {'thesis_ids': list(row.get('thesis_ids', [])), 'citations': list(row.get('citations', []))}


def build(run, historical=None):
    """Build a read-only view; old records are explicitly identified as supplements."""
    profile = validate_profile(run.get('investment_profile'))
    saved = run.get('decision') or {}
    if historical is None:
        historical = bool(saved.get('review_status', {}).get('compatibility_view')) or not (run.get('decision') or run.get('investment_profile'))
    checks = comparison_checks(run)
    evidence = {row.get('citation'): row for row in run.get('evidence', []) if row.get('citation')}
    notes = {row.get('claim_id'): row for row in (run.get('human_review') or {}).get('notes', []) if isinstance(row, dict)}
    basis, missing = [], []
    pending = refuted = missing_sources = 0
    for index, row in enumerate((run.get('draft') or {}).get('thesis', [])):
        claim_id = f'thesis:{index}'
        refs = list(row.get('citations', []))
        source_valid = bool(refs) and all(ref in evidence and evidence[ref].get('source_id') and (evidence[ref].get('locator') or evidence[ref].get('pdf_page')) for ref in refs)
        note = notes.get(claim_id) or {}
        state = note.get('state', 'pending')
        # A status with no recorded basis is not a genuine manual sign-off.
        reviewed = state == 'confirmed' and bool(str(note.get('note', '')).strip()) and source_valid
        if state == 'refuted':
            refuted += 1
        elif not reviewed:
            pending += 1
        if not source_valid:
            missing_sources += 1
        source_status = '已记录人工支持依据' if reviewed else ('人工记录反证' if state == 'refuted' else ('缺少有效来源定位' if not source_valid else '引用可回看，支持关系待人工核验'))
        basis.append({'text': row.get('text', ''), 'thesis_ids': [row.get('id', f'T{index + 1}')],
                      'citations': refs, 'claim_id': claim_id, 'source_status': source_status})
    review = run.get('review') or {}
    # First-round combined reviews retain the untouched model review separately.
    issues = [row for row in (review.get('model_review') or review).get('issues', []) if row.get('source') != 'deterministic']
    high = sum(row.get('severity') == '高' for row in issues) + sum(row['severity'] == '高' for row in checks)
    medium = sum(row.get('severity') == '中' for row in issues) + sum(row['severity'] == '中' for row in checks)
    if checks:
        missing.append(f'确定性口径/推论检查有{len(checks)}项未决问题，需更正论据后重新生成或复核。')
    if high or medium:
        missing.append(f'实质复核问题尚未解决：高风险{high}项、中风险{medium}项。')
    if not basis:
        missing.append('尚无可关联的投资论据。')
    if missing_sources:
        missing.append(f'{missing_sources}项论据缺少有效证据编号或原页定位。')
    if pending:
        missing.append(f'{pending}项投资论据的引用支持关系尚待人工核验。')
    if refuted:
        missing.append(f'{refuted}项投资论据已有人工反证，需修改后重审。')
    if run.get('mode') == 'local':
        missing.append('资料模式仅整理事实与核验事项，尚未形成面向后续经营的投资论据。')
    if run.get('mode') == 'development_revision':
        missing.append('本例仅为开发侧逻辑修订，尚未完成新的模型研究复测及金融人工核验；不能以规则通过代替验证。')
    valuation = run.get('valuation') or {}
    scenarios = valuation.get('pe_scenarios') or []
    pe_basis = valuation.get('pe_basis') or {}
    market_pe = valuation.get('market_pe') or {}
    if not valuation:
        missing.append('未附带估值情景，无法判断价格与情景价值的关系。')
    else:
        if not pe_basis.get('text'):
            missing.append('PE倍数依据缺失；演示倍数不能直接支撑投资价值判断。')
        elif pe_basis.get('reviewed') is not True:
            missing.append('PE倍数依据尚未经用户人工复核；用户勾选只代表本人复核声明。')
        if not valuation.get('assumptions', {}).get('shares_yi'):
            missing.append('未选择估值股数分母，缺少每股价值与收益情景。')
        if not market_pe.get('available'):
            missing.append('当前参考PE/行情与股份口径尚未完成：' + str(market_pe.get('reason') or '旧情景未保存该计算，需按同一研究时点重新计算。'))
        if not scenarios:
            missing.append('缺少估值情景结果。')
        if scenarios and any(row.get('price_return_pct') is None for row in scenarios):
            missing.append('价格收益情景不可计算，需补可比较的股数、价格与证券类别口径。')
        if scenarios and any(row.get('total_return_pct') is None for row in scenarios):
            missing.append('股利与交易费率假设未齐，总回报仍待补充；价格情景不能替代总回报。')
    if profile['budget_yuan'] is None:
        missing.append('未提供投入上限。')
    if profile['max_loss_pct'] is None:
        missing.append('未提供最大可接受损失约束。')
    else:
        tolerance = Decimal(profile['max_loss_pct'])
        for row in scenarios:
            return_value = row.get('total_return_pct')
            if return_value is None:
                return_value = row.get('price_return_pct')
            try:
                projected = Decimal(str(return_value))
            except (InvalidOperation, ValueError, TypeError):
                continue
            if projected.is_finite() and projected < -tolerance:
                kind = '总回报' if row.get('total_return_pct') is not None else '价格回报'
                missing.append(f"{row.get('label', '所选')}情景{kind}{projected}%超出用户最大可接受损失{tolerance}%；需调整研究条件并复核，损失阈值不保证成交结果。")
    returns = [{key: row.get(key) for key in ['label', 'pe', 'equity_value_yi', 'per_share_yuan', 'price_return_pct', 'total_return_pct']} |
               {'note': '基于保存的参考价格与用户情景假设；不是持有期内的收益预测，未保证可实现。'} for row in scenarios]
    entry = [{'text': '先解决以下资料与核验缺口：' + item, 'thesis_ids': [], 'citations': []} for item in missing]
    entry.append({'text': '入场前复核最新资料、交易证券类别、币种、实际价格及用户预算和损失约束；历史参考价格不等于可成交价。', 'thesis_ids': [], 'citations': []})
    exit_rows = []
    for row in (run.get('draft') or {}).get('invalidation', []):
        exit_rows.append({'text': '触发以下条件时撤回相关研究候选并重新评估持有/退出决定：' + row.get('text', ''), **_links(row)})
    if profile['max_loss_pct'] is not None:
        exit_rows.append({'text': f"达到用户设定的最大可接受损失{profile['max_loss_pct']}%时，暂停新增投入并复核持有/退出决定；阈值是用户研究假设，实际成交损失可能超出阈值。", 'thesis_ids': [], 'citations': []})
    exit_rows.append({'text': f"用户假设的{profile['horizon_months']}个月持有期届满时，重新评估论据、估值和继续持有条件。", 'thesis_ids': [], 'citations': []})
    # Missing total return is also a genuine gap in a requested complete memo.
    status = '暂缓投资判断' if missing else '有条件纳入研究候选'
    reason = ('尚有证据、估值或约束缺口，先完成核验与条件设定。' if missing else '已记录论据支持依据与情景假设，可按列示条件继续研究；实际投资仍需交易前复核。')
    review_label = '历史记录补充视图 · 待人工核验' if historical else ('仍有未决事项' if missing else '已记录人工复核 · 仍需交易前复核')
    return {'status': status, 'reason': reason, 'objective': profile['goal'], 'horizon_months': profile['horizon_months'],
            'profile': profile, 'basis': basis, 'return_scenarios': returns, 'entry_conditions': entry,
            'exit_conditions': exit_rows, 'missing': list(dict.fromkeys(missing)),
            'review_status': {'label': review_label, 'unresolved_high': high, 'unresolved_medium': medium,
                              'pending_theses': pending, 'refuted_theses': refuted, 'compatibility_view': bool(historical), 'scope': SCOPE}}


def markdown(run, checks=None, concise=False):
    """Use the same deterministic view for saved and regenerated report exports."""
    is_view = 'status' in run and 'profile' in run and 'basis' in run
    view = run if is_view else build(run)
    profile = view['profile']
    lines = ['\n## 投资判断与执行条件\n', f"**{view['status']}**：{view['reason']}\n",
             f"投资目标：{view['objective']}；用户假设持有期：{view['horizon_months']}个月。\n",
             f"核验状态：{view['review_status']['label']}。{SCOPE}\n"]
    if profile['budget_yuan'] is not None:
        lines.append(f"投入上限由用户提供：{profile['budget_yuan']}元。\n")
    if profile['max_loss_pct'] is not None:
        lines.append(f"用户最大可接受损失假设：{profile['max_loss_pct']}%。\n")
    lines.append('\n### 情景回报\n')
    if not view['return_scenarios']:
        lines.append('未附带可计算的回报情景。\n')
    for row in view['return_scenarios']:
        price = '待补' if row['price_return_pct'] is None else str(row['price_return_pct']) + '%'
        total = '待补' if row['total_return_pct'] is None else str(row['total_return_pct']) + '%'
        lines.append(f"- {row['label']}：价格情景回报{price}；总回报{total}。{row['note']}\n")
    for name, key in [('入场前提', 'entry_conditions'), ('撤回、持有与退出复核', 'exit_conditions')]:
        lines.append('\n### ' + name + '\n')
        for row in view[key]:
            links = ''.join(f'[{ref}]' for ref in row['citations'])
            thesis = '；关联' + ','.join(row['thesis_ids']) if row['thesis_ids'] else ''
            lines.append('- ' + row['text'] + links + thesis + '\n')
    if not concise:
        lines.append('\n### 投资论据与支持状态\n')
        for row in view['basis']:
            lines.append('- ' + ','.join(row['thesis_ids']) + '：' + row['text'] + ''.join(f'[{ref}]' for ref in row['citations']) + '；' + row['source_status'] + '\n')
    checks = (checks or []) if is_view else (comparison_checks(run) if checks is None else checks)
    if checks:
        lines.append('\n### 确定性口径与推论检查\n')
        for row in checks:
            lines.append(f"- {row['severity']} · {row['claim']}：{row['reason']}\n")
    return ''.join(lines)
