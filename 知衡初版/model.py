"""OpenAI-compatible model calls. Credentials stay in server memory only."""
import json
import os
import threading
import time
import hashlib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from core import APP, json_dump
import audit

_lock=threading.Lock()
_key_override=None
_config={'provider':'DeepSeek','base_url':os.environ.get('ZHIHENG_BASE_URL','https://api.deepseek.com'),
         'model':os.environ.get('ZHIHENG_MODEL','deepseek-flash'),'key_env':os.environ.get('ZHIHENG_KEY_ENV','DEEPSEEK_API_KEY')}

def get_config():
    with _lock:
        cfg=dict(_config)
        key=_key_override if _key_override is not None else os.environ.get(cfg['key_env'],'')
    cfg['configured']=bool(key.strip())
    return cfg

def credentials():
    with _lock:
        cfg=dict(_config)
        key=_key_override if _key_override is not None else os.environ.get(cfg['key_env'],'')
    if not key.strip(): raise ModelFailure('尚未配置模型密钥。请先使用资料模式，或在模型设置中配置。','credentials_missing')
    return cfg,key

def configure(body):
    global _key_override
    base=str(body.get('base_url','')).strip().rstrip('/')
    url=urllib.parse.urlparse(base)
    if url.scheme not in ['https','http'] or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('模型服务地址必须是没有密钥和查询参数的HTTP(S)地址')
    if url.scheme=='http' and url.hostname not in ['localhost','127.0.0.1','::1']:
        raise ValueError('公网模型服务请使用HTTPS；本机模型可以使用HTTP')
    model=str(body.get('model','')).strip()
    if not model or len(model)>120: raise ValueError('请填写模型名称')
    env=str(body.get('key_env','DEEPSEEK_API_KEY'))
    if env not in ['DEEPSEEK_API_KEY','OPENAI_API_KEY','DASHSCOPE_API_KEY','ZHIHENG_API_KEY']:
        raise ValueError('不支持的环境变量名称')
    with _lock:
        _config.update(provider=str(body.get('provider','自定义'))[:40],base_url=base,model=model,key_env=env)
        if body.get('clear_key'): _key_override=''
        elif body.get('api_key'): _key_override=str(body['api_key']).strip()
        elif body.get('use_environment'): _key_override=None
    return get_config()

class ModelFailure(ValueError):
    def __init__(self,message,error_kind,http_status=None):
        super().__init__(message);self.error_kind=error_kind;self.http_status=http_status


def complete(system,user,max_tokens=2600):
    cfg=get_config();started=time.monotonic()
    attempt_id=audit.begin_attempt(cfg['provider'],cfg['model'],system,user)
    try:
        result,log=_complete(system,user,max_tokens,attempt_id)
    except Exception as error:
        kind=getattr(error,'error_kind', 'invalid_response_json' if isinstance(error,json.JSONDecodeError) else type(error).__name__)
        try:audit.finish_attempt(attempt_id,'failed',round((time.monotonic()-started)*1000),error_kind=kind,http_status=getattr(error,'http_status',None))
        except Exception:pass
        raise
    audit.finish_attempt(attempt_id,'success',round((time.monotonic()-started)*1000),provider=log['provider'],model=log['model'],usage=log.get('usage',{}),response_model=log.get('response_model','unknown'),output_sha256=hashlib.sha256(json_dump(result).encode()).hexdigest())
    return result,dict(log,attempt_id=attempt_id)


def _complete(system,user,max_tokens=2600,attempt_id=None):
    cfg,key=credentials()
    body={'model':cfg['model'],'messages':[{'role':'system','content':system},{'role':'user','content':user}],
          'stream':False,'max_tokens':max_tokens,'response_format':{'type':'json_object'}}
    hostname=urllib.parse.urlparse(cfg['base_url']).hostname
    if hostname=='api.openai.com':
        body['max_completion_tokens']=body.pop('max_tokens')
    if hostname=='api.deepseek.com':
        body['thinking']={'type':'disabled'}
    if hostname=='dashscope.aliyuncs.com' and cfg['model'].startswith('qwen'):
        body['enable_thinking']=False
    data=json_dump(body).encode('utf-8')
    req=urllib.request.Request(cfg['base_url'].rstrip('/')+'/chat/completions',data=data,
             headers={'Content-Type':'application/json','Authorization':'Bearer '+key,'User-Agent':'Zhiheng-Prototype/0.1'})
    if attempt_id:audit.request_sent(attempt_id,cfg['provider'],cfg['model'],data)
    try:
        with urllib.request.urlopen(req,timeout=120) as response:
            raw=json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        # Do not echo vendor bodies, request headers or secrets back to the browser/logs.
        raise ModelFailure(f'模型服务返回HTTP {exc.code}。请核对服务地址、模型名称、密钥和余额。','http_error',exc.code) from None
    except (urllib.error.URLError,TimeoutError):
        raise ModelFailure('模型服务连接失败或超时。可以先切换到资料模式。','connection_or_timeout') from None
    try:
        choice=raw['choices'][0]
        if choice.get('finish_reason')=='length': raise ModelFailure('模型输出达到长度上限，未保存不完整结论。请缩小问题范围。','length_limit')
        content=choice['message']['content']
        if content.startswith('```'): content=content.strip('`').removeprefix('json').strip()
        result=json.loads(content)
        if not isinstance(result,dict): raise ModelFailure('模型没有返回有效的结构化结果。请重试或使用资料模式。','invalid_structured_result')
    except (KeyError,IndexError,TypeError,json.JSONDecodeError):
        raise ModelFailure('模型没有返回有效的结构化结果。请重试或使用资料模式。','invalid_structured_result') from None
    return result,{'provider':cfg['provider'],'model':cfg['model'],'response_model':raw.get('model') or 'unknown','usage':raw.get('usage',{}),
                   'request_system':system,'request_user':user,'response':result}
