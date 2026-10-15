"""Pre-authorized recovery command for agent policy: restarts only this demo backend."""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / 'backend.py'
HEALTH = 'http://127.0.0.1:8200/health'


def healthy():
    try:
        with urllib.request.urlopen(HEALTH, timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


if __name__ == '__main__':
    if healthy():
        print('Backend already healthy; no restart needed.')
        sys.exit(0)
    with (ROOT / 'runtime' / 'recovery.log').open('a', encoding='utf-8') as log:
        log.write('Starting approved backend recovery\n')
    flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)
    log_file = (ROOT / 'runtime' / 'backend_console.log').open('a', encoding='utf-8')
    try:
        subprocess.Popen([sys.executable, str(SCRIPT)], cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
    finally:
        log_file.close()
    for _ in range(20):
        if healthy():
            print('Recovery verified: backend HTTP 200')
            sys.exit(0)
        time.sleep(0.5)
    print('Recovery failed verification: backend still offline', file=sys.stderr)
    sys.exit(1)
