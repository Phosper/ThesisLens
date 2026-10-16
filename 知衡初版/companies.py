"""Shared issuer profiles and explicitly user-registered document research entities."""
import json
from pathlib import Path
import re
import threading
import uuid

BASE = Path(__file__).with_name('companies.json')
DEFAULTS = json.loads(BASE.read_text(encoding='utf-8'))['profiles']
_lock = threading.RLock()


def local_path():
    import core
    return core.DATA / 'company_registry.json'


def profiles(include_local=True):
    rows = [dict(row, registration='内置公开样本', registration_note='细分标签用于研究方法提示，不是估值可比性认证。') for row in DEFAULTS]
    if include_local:
        path = local_path()
        if path.exists():
            extra = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(extra, list):
                raise ValueError('本机企业登记格式无效')
            occupied = {row['code'] for row in rows}
            for row in extra:
                if not isinstance(row, dict) or not re.fullmatch(r'(?:\d{6}|LOCAL_[a-f0-9]{12})', str(row.get('code', ''))) or row['code'] in occupied:
                    raise ValueError('本机企业登记编号无效或重复')
                if not isinstance(row.get('name'), str) or type(row.get('listed')) is not bool:
                    raise ValueError('本机企业名称或上市状态无效')
                occupied.add(row['code'])
                rows.append(dict(row))
    return rows


def get(code):
    return next((row for row in profiles() if row['code'] == code), None)


def names(include_local=True):
    return {row['code']: row['name'] for row in profiles(include_local)}


def refresh():
    import core
    core.COMPANIES.clear()
    core.COMPANIES.update(names())


def register(body):
    if not isinstance(body, dict):
        raise ValueError('企业登记需要对象')
    name = body.get('name', '')
    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 50:
        raise ValueError('企业名称需要2至50字')
    listed = body.get('listed', False)
    if type(listed) is not bool:
        raise ValueError('上市状态需要布尔值')
    code = str(body.get('code') or '').strip()
    if listed and not re.fullmatch(r'\d{6}', code):
        raise ValueError('上市企业需填写六位证券代码')
    if not listed and code:
        raise ValueError('非上市企业不填写证券代码，系统生成资料研究编号')
    note = body.get('note', '')
    if not isinstance(note, str) or len(note) > 400:
        raise ValueError('企业说明最多400字')
    code = code if listed else 'LOCAL_' + uuid.uuid4().hex[:12]
    with _lock:
        if any(row['code'] == code or row['name'] == name.strip() for row in profiles()):
            raise ValueError('企业编号或名称已登记')
        path = local_path()
        extra = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        row = {'code': code, 'name': name.strip(), 'listed': listed,
               'segment': '用户登记上市企业' if listed else '非上市资料研究',
               'method': 'custom' if listed else 'documents', 'comparison_codes': [],
               'org_id': None, 'exchange': None, 'registration': '用户登记，未经独立核验',
               'registration_note': note.strip() or '请补充真实原件及披露日期；企业登记本身不是财务事实。'}
        extra.append(row)
        staged = path.with_suffix('.tmp')
        staged.write_text(json.dumps(extra, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        staged.replace(path)
        refresh()
    return row


def comparison_codes(code):
    row = get(code)
    return [code] + [peer for peer in (row or {}).get('comparison_codes', []) if peer in names() and peer != code]
