"""Safely trigger crash on the isolated localhost demo service only."""
import os
import sys
import urllib.request

secret = os.environ.get('AEGISOPS_DEMO_CRASH_TOKEN', '')
if not secret:
    print('Missing AEGISOPS_DEMO_CRASH_TOKEN', file=sys.stderr)
    sys.exit(1)
request = urllib.request.Request('http://127.0.0.1:8200/test/crash', data=b'{}', method='POST', headers={'X-Demo-Crash-Token': secret, 'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(request, timeout=4) as response:
        print('Crash triggered:', response.status, response.read().decode())
except Exception as exc:
    print('Crash request ended with:', exc)
    print('Check health endpoint; process may have exited during response.')
