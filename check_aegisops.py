"""Non-destructive AegisOps project readiness check. Run from D:\\AegisOps."""
from pathlib import Path
import json, os, urllib.request, urllib.error

ROOT = Path(__file__).resolve().parent


def load(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def status(label, ok, detail=''):
    print(f"[{'OK' if ok else 'CHECK'}] {label}" + (f' — {detail}' if detail else ''))


def probe(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'AegisOps-Readiness/1.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            return True, str(response.status)
    except Exception as exc:
        return False, type(exc).__name__

print('\nAEGISOPS READINESS CHECK (READ-ONLY)\n' + '='*46)
for rel in ('aegisops.py','core/monitor.py','core/recovery.py','web/app.py','data/services.json'):
    status(rel, (ROOT/rel).is_file())
for rel in ('agent/agent.py','core/agent_client.py','core/recovery_policy.py','core/audit.py','data/agents.json'):
    status(rel, (ROOT/rel).is_file(), 'enterprise component')

services = load(ROOT/'data/services.json', [])
if isinstance(services, dict):
    services = services.get('services', [])
if not isinstance(services, list):
    services=[]
print(f'\nRegistered services: {len(services)}')
for svc in services:
    if not isinstance(svc, dict): continue
    sid=str(svc.get('id','unknown'))
    name=str(svc.get('name','unnamed'))
    env='AEGISOPS_RECOVERY_'+''.join(c if c.isalnum() else '_' for c in sid.upper())
    configured=bool(os.environ.get(env)) or bool(os.environ.get('AEGISOPS_RECOVERY_'+sid.replace('-','_')))
    if sid == 'SVC-001':
        print(f'  {sid}: {name} — built-in local recovery')
    else:
        print(f'  {sid}: {name} — recovery webhook '+('present' if configured else 'not visible to this process'))

agents=load(ROOT/'data/agents.json', [])
if isinstance(agents,dict): agents=agents.get('agents',[])
if not isinstance(agents,list): agents=[]
print(f'\nRegistered agents: {len(agents)}')
for agent in agents:
    if not isinstance(agent,dict): continue
    aid=str(agent.get('id','unknown'))
    env='AEGISOPS_AGENT_TOKEN_'+''.join(c if c.isalnum() else '_' for c in aid.upper())
    print(f'  {aid}: token '+('present' if os.environ.get(env) else 'not visible to this process'))

for label,url in [('Dashboard','http://127.0.0.1:5000/'),('Local service','http://127.0.0.1:8000/health')]:
    ok,detail=probe(url)
    status(label,ok,'HTTP '+detail if ok else detail)

print('\nThis check never restarts services, triggers deploys or prints tokens.\n')
