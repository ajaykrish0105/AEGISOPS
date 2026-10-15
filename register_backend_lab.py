"""Register the local AegisOps backend lab without modifying existing service entries."""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SERVICES = ROOT / 'data' / 'services.json'
AGENTS = ROOT / 'data' / 'agents.json'
POLICY = ROOT / 'agent' / 'policy.json'
BACKEND = ROOT / 'backend_lab' / 'restart_backend.py'


def load(path, expected):
    with path.open(encoding='utf-8') as f:
        obj = json.load(f)
    if not isinstance(obj, expected):
        raise ValueError(f'Unexpected JSON structure: {path}')
    return obj


def save(path, obj):
    backup = path.with_name(path.name + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(path, backup)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, indent=4, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)
    print(f'[BACKUP] {backup.name}')


def main():
    for path in (SERVICES, AGENTS, POLICY, BACKEND):
        if not path.is_file():
            raise FileNotFoundError(f'Missing: {path}')
    services = load(SERVICES, list)
    agents = load(AGENTS, list)
    policy = load(POLICY, dict)
    ids = {str(s.get('id')) for s in services}
    if 'SVC-004' not in ids:
        services.append({'id': 'SVC-004', 'name': 'AegisOps Demo Backend', 'health_url': 'http://127.0.0.1:8200/health', 'service_type': 'API', 'monitoring_enabled': True, 'auto_recovery': False, 'created_at': datetime.now().isoformat(timespec='seconds')})
        save(SERVICES, services)
        print('[OK] SVC-004 registered (automatic recovery intentionally OFF until monitor integration verified)')
    else:
        print('[SKIP] SVC-004 already exists; preserved')
    configured = policy.setdefault('services', {})
    if 'aegisops-demo-backend' not in configured:
        configured['aegisops-demo-backend'] = {'health_url': 'http://127.0.0.1:8200/health', 'log_file': '', 'metadata': {'environment': 'local-lab', 'owner': 'Team Kairo'}, 'actions': {'RESTART_SERVICE': [sys.executable, str(BACKEND)]}}
        save(POLICY, policy)
        print('[OK] Local agent allowlisted only demo backend restart')
    else:
        print('[SKIP] Agent policy entry exists; preserved')
    agent = next((a for a in agents if a.get('id') == 'AGENT-001'), None)
    if agent is None:
        agent = {'id': 'AGENT-001', 'name': 'Local Lab Agent', 'base_url': 'http://127.0.0.1:9100', 'enabled': True, 'bindings': []}
        agents.append(agent)
        changed = True
    else:
        changed = False
    bindings = agent.setdefault('bindings', [])
    if not any(str(b.get('service_id')) == 'SVC-004' for b in bindings):
        bindings.append({'service_id': 'SVC-004', 'agent_service': 'aegisops-demo-backend'})
        changed = True
    if changed:
        save(AGENTS, agents)
        print('[OK] AGENT-001 binding registered')
    else:
        print('[SKIP] Agent binding already exists')
    print('\nConfiguration ready. Auto-recovery remains disabled pending monitor/policy compatibility check.')
    print('Never expose port 9100 to the public Internet without production-grade security.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[ERROR] {exc}', file=sys.stderr)
        sys.exit(1)
