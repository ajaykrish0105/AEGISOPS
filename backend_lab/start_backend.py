"""Start demo backend independently; do not run it under an auto-restarting launcher."""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent
ROOT.joinpath('runtime').mkdir(exist_ok=True)
try:
    urllib.request.urlopen('http://127.0.0.1:8200/health', timeout=2)
    print('Demo backend already running')
    sys.exit(0)
except Exception:
    pass
flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)
with (ROOT / 'runtime' / 'backend_console.log').open('a', encoding='utf-8') as output:
    subprocess.Popen([sys.executable, str(ROOT / 'backend.py')], cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
for i in range(20):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8200/health', timeout=1) as response:
            if response.status == 200:
                print('Demo backend online: http://127.0.0.1:8200/health')
                sys.exit(0)
    except Exception:
        time.sleep(0.5)
print('Backend failed to start. See runtime/backend_console.log', file=sys.stderr)
sys.exit(1)
