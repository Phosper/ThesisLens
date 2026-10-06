"""Double-click launcher; start a hidden local service and open the ready page."""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
import hashlib
from pathlib import Path

APP=Path(__file__).resolve().parent
def ready(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=2) as fp:
            status=json.load(fp)
            return status.get('name')=='知衡' and status.get('instance_id')==hashlib.sha256(str(APP).encode()).hexdigest()[:16]
    except Exception: return False

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-open',action='store_true');args=parser.parse_args()
    for port in range(8765,8785):
        if ready(port): break
        with socket.socket() as sock:
            try: sock.bind(('127.0.0.1',port))
            except OSError: continue
        data=APP/'data';data.mkdir(exist_ok=True)
        env=dict(os.environ,PYTHONIOENCODING='utf-8')
        with (data/'server.log').open('a',encoding='utf-8') as out,(data/'server-error.log').open('a',encoding='utf-8') as err:
            process=subprocess.Popen([sys.executable,str(APP/'server.py'),'--port',str(port)],cwd=APP,env=env,
                    stdout=out,stderr=err,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (data/'service.json').write_text(json.dumps({'pid':process.pid,'port':port,'url':f'http://127.0.0.1:{port}'}),encoding='utf-8')
        for _ in range(90):
            if ready(port): break
            if process.poll() is not None: raise RuntimeError('Service did not start. See data/server-error.log.')
            time.sleep(1)
        else: raise RuntimeError('Startup is taking longer than expected. Try again shortly.')
        break
    else: raise RuntimeError('No local port is available between 8765 and 8784.')
    url=f'http://127.0.0.1:{port}'
    if not args.no_open: webbrowser.open(url)
    print('Zhiheng ready: '+url)

if __name__=='__main__': main()
