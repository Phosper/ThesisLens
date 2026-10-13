"""Persistent safe metadata for attempts and controlled local-source access.

No headers, credentials, URLs, exception messages, prompts or document bodies enter
this database. Original model I/O remains in the separately saved research record.
"""
import contextvars
from contextlib import contextmanager
import functools
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
import urllib.parse

_context = contextvars.ContextVar('zhiheng_audit_context', default={})
FIELDS = {'attempt_id', 'operation', 'purpose', 'status', 'error_kind', 'http_status', 'duration_ms',
          'provider', 'model', 'input_sha256', 'output_sha256', 'source_id', 'relative_source',
          'sha256', 'transfer_sha256', 'source_sha256', 'bytes', 'cache_hit', 'cache_name', 'page', 'http_method', 'range_start', 'range_end', 'response_model',
          'usage', 'parent_run_id', 'request_sent', 'request_body_sha256', 'count', 'started_at', 'finished_at'}
_TOKEN = re.compile(r'\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{20,})\b')


def current():
    return dict(_context.get())


def _safe_id(value):
    text=str(value)
    return text if re.fullmatch(r'[A-Za-z0-9_-]{1,100}',text) and not _TOKEN.search(text) else '[redacted]'


def db_path():
    import core
    return core.DATA/'audit.sqlite3'


def connect():
    import core
    db = sqlite3.connect(db_path(), timeout=15, factory=core.ClosingConnection)
    db.row_factory = sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,created_at TEXT,run_id TEXT,job_id TEXT,kind TEXT,metadata TEXT);
        CREATE INDEX IF NOT EXISTS audit_run ON events(run_id,id);
        CREATE TABLE IF NOT EXISTS attempts(attempt_id TEXT PRIMARY KEY,created_at TEXT,run_id TEXT,job_id TEXT,status TEXT,metadata TEXT);''')
    return db


def _clean(metadata):
    result = {}
    for key, value in metadata.items():
        if key not in FIELDS or value is None:
            continue
        if key == 'usage':
            result[key] = {name: number for name, number in (value or {}).items()
                           if name in ['prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens']
                           and isinstance(number, (int, float)) and not isinstance(number, bool) and number >= 0}
        elif isinstance(value, (int, float, bool)):
            result[key] = value
        else:
            text = str(value)[:400]
            # IDs/labels are never allowed to carry secrets, absolute paths or URLs.
            if _TOKEN.search(text) or re.search(r'[A-Za-z]:[\\/]|https?://|Bearer\s', text, re.I):
                text = '[redacted]'
            if key == 'relative_source' and ('..' in Path(text).parts or Path(text).is_absolute()):
                text = '[external source]'
            result[key] = text
    return result


def event(kind, **metadata):
    import core
    context = current()
    clean = _clean(metadata)
    with connect() as db:
        cursor = db.execute('INSERT INTO events(created_at,run_id,job_id,kind,metadata) VALUES (?,?,?,?,?)',
                            (core.now(), context.get('run_id'), context.get('job_id'), kind, json.dumps(clean, ensure_ascii=False)))
        return cursor.lastrowid


@contextmanager
def context(run_id=None, job_id=None, operation=None):
    state = current()
    if run_id is not None:
        state['run_id'] = _safe_id(run_id)
    if job_id is not None:
        state['job_id'] = _safe_id(job_id)
    token = _context.set(state)
    try:
        yield state
    finally:
        _context.reset(token)


def operation(name):
    """Wrap full operations so failed jobs remain inspectable without a saved memo."""
    def decorate(function):
        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            run_id = current().get('run_id') or uuid.uuid4().hex[:12]
            started = time.monotonic()
            with context(run_id=run_id):
                event('operation', operation=name, status='started')
                try:
                    result = function(*args, **kwargs)
                except Exception as error:
                    try:
                        event('operation', operation=name, status='failed', error_kind=type(error).__name__,
                              duration_ms=round((time.monotonic()-started)*1000))
                    except Exception:
                        pass  # Preserve the original failure, never replace it with a log error.
                    raise
                event('operation', operation=name, status='success', duration_ms=round((time.monotonic()-started)*1000))
                if isinstance(result, dict) and result.get('id'):
                    result['audit'] = snapshot(run_id)
                return result
        return wrapped
    return decorate


def begin_attempt(provider, model, system, user):
    import core
    attempt_id = uuid.uuid4().hex
    metadata = _clean({'attempt_id': attempt_id, 'provider': provider, 'model': model,
                       'status': 'started', 'purpose': 'model_request', 'input_sha256': hashlib.sha256((system+'\0'+user).encode()).hexdigest()})
    state = current()
    with connect() as db:
        db.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?)',
                   (attempt_id, core.now(), state.get('run_id'), state.get('job_id'), 'started', json.dumps(metadata, ensure_ascii=False)))
    event('model_attempt', **metadata)
    return attempt_id


def finish_attempt(attempt_id, status, duration_ms, **metadata):
    clean = _clean(dict(metadata, attempt_id=attempt_id, status=status, duration_ms=duration_ms))
    with connect() as db:
        row = db.execute('SELECT metadata FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
        if not row:
            raise ValueError('模型审计请求编号不存在')
        payload = dict(json.loads(row['metadata']), **clean)
        db.execute('UPDATE attempts SET status=?,metadata=? WHERE attempt_id=?', (status, json.dumps(payload, ensure_ascii=False), attempt_id))
    event('model_attempt', **payload)


def request_sent(attempt_id, provider, model, body):
    """Record the actual request configuration, never credentials or headers."""
    payload=_clean({'attempt_id':attempt_id,'provider':provider,'model':model,'request_sent':True,
                    'request_body_sha256':hashlib.sha256(body).hexdigest(),'status':'started'})
    with connect() as db:
        row=db.execute('SELECT metadata FROM attempts WHERE attempt_id=?',(attempt_id,)).fetchone()
        db.execute('UPDATE attempts SET metadata=? WHERE attempt_id=?',(json.dumps(dict(json.loads(row['metadata']),**payload),ensure_ascii=False),attempt_id))
    event('model_attempt',**payload)


def _relative(file):
    import core
    file = Path(file).resolve()
    for root, label in [(core.DATASET, 'dataset'), (core.APP, 'app')]:
        if file.is_relative_to(root.resolve()):
            return label+'/'+file.relative_to(root.resolve()).as_posix()
    return '[external source]'


def read_bytes(file, source_id=None, purpose='source_read'):
    started = time.monotonic()
    relative = _relative(file)
    try:
        raw = Path(file).read_bytes()
    except Exception as error:
        try:
            event('source_read', source_id=source_id, relative_source=relative, purpose=purpose,
                  status='failed', error_kind=type(error).__name__, duration_ms=round((time.monotonic()-started)*1000))
        except Exception:
            pass
        raise
    event('source_read', source_id=source_id, relative_source=relative, purpose=purpose,
          status='success', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
          cache_hit=False, duration_ms=round((time.monotonic()-started)*1000))
    return raw


def read_text(file, encoding='utf-8', source_id=None, purpose='source_read'):
    raw=read_bytes(file, source_id, purpose)
    try:return raw.decode(encoding)
    except UnicodeError as error:
        event('source_decode',source_id=source_id,purpose=purpose,status='failed',error_kind=type(error).__name__)
        raise


def cache_hit(name, source_id=None, sha256=None, count=None):
    event('cache', cache_name=name, source_id=source_id, sha256=sha256, count=count, status='hit', cache_hit=True)


def snapshot(run_id=None, job_id=None, limit=1000):
    run_id=_safe_id(run_id) if run_id is not None else None
    job_id=_safe_id(job_id) if job_id is not None else None
    query = 'run_id=?' if run_id else 'job_id=?' if job_id else '1=1'
    values = [run_id or job_id] if run_id or job_id else []
    limit = max(1, min(int(limit), 5000))
    with connect() as db:
        rows = db.execute('SELECT * FROM events WHERE '+query+' ORDER BY id DESC LIMIT ?', values+[limit]).fetchall()
        attempts = db.execute('SELECT * FROM attempts WHERE '+query+' ORDER BY created_at LIMIT ?', values+[limit]).fetchall()
        count = db.execute('SELECT COUNT(*) FROM events WHERE '+query, values).fetchone()[0]
    events = [dict(id=row['id'], created_at=row['created_at'], run_id=row['run_id'], job_id=row['job_id'], kind=row['kind'], **json.loads(row['metadata'])) for row in reversed(rows)]
    requests = [dict(created_at=row['created_at'], run_id=row['run_id'], job_id=row['job_id'], **json.loads(row['metadata'])) for row in attempts]
    return {'available': bool(events or requests), 'scope': '安全元数据审计：含本次已登记请求成功/失败、受控原件与缓存访问；不含密钥、请求头、原文或错误响应体。历史缺失日志无法追补；成功请求数不是服务商账单。',
            'run_id': run_id, 'job_id': job_id, 'events': events, 'model_attempts': requests,
            'event_count': count, 'returned_events': len(events), 'truncated': count > len(events),
            'historical_note': None if events or requests else '该保存记录没有关联的新审计日志；不追补历史请求。'}


def markdown(view):
    attempts=view.get('model_attempts',[])
    counts={state:sum(row.get('status')==state for row in attempts) for state in ['success','failed','started']}
    lines=['\n## 请求与资料访问审计\n',view['scope']+'\n',
           f"模型请求记录：成功{counts['success']}次，失败{counts['failed']}次，未结束{counts['started']}次；已登记事件{view['event_count']}条。\n"]
    if view.get('historical_note'):lines.append(view['historical_note']+'\n')
    if view.get('truncated'):lines.append(f"当前导出仅展示最新{view['returned_events']}条事件；完整记录保存在本机审计库，可按运行编号查询。\n")
    for row in attempts:
        lines.append(f"- {row['attempt_id']}：{row['status']}，请求模型{row.get('model','unknown')}，服务返回模型{row.get('response_model','unknown')}，耗时{row.get('duration_ms','待完成')}毫秒；失败类型{row.get('error_kind','无')}。\n")
    return ''.join(lines)


def original_url(source_id, run_id=None, page=None):
    """Browser URL binds an actual saved-report visit; PDF fragment follows query."""
    import core
    base=getattr(core,'LOCAL_BASE_URL','')
    parsed=urllib.parse.urlparse(base)
    if parsed.hostname not in ['127.0.0.1','localhost'] or parsed.scheme!='http':base=''
    suffix='?'+urllib.parse.urlencode({'run_id':_safe_id(run_id)}) if run_id else ''
    fragment='#page='+str(int(page)) if page is not None else ''
    return base+'/api/files/'+urllib.parse.quote(str(source_id),safe='')+suffix+fragment
