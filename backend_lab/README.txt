AEGISOPS — ISOLATED BACKEND FAILURE LAB
======================================
This is a real Flask + SQLite order API. It runs ONLY on 127.0.0.1:8200.
It is NOT a production payment processor. It never touches Render or any external server.

SETUP (PowerShell; keep AegisOps running in its original terminal):
1. Extract this folder into D:\AegisOps\backend_lab\ (files directly in backend_lab).
2. Open a NEW PowerShell:
   cd D:\AegisOps
   .\.venv\Scripts\Activate.ps1
   python -c "import flask; print('Flask ready')"
   $env:AEGISOPS_DEMO_CRASH_TOKEN = [guid]::NewGuid().ToString('N')
   python .\backend_lab\start_backend.py
3. Browse http://127.0.0.1:8200/health
4. Test order creation:
   Invoke-RestMethod -Uri http://127.0.0.1:8200/api/orders -Method Post -ContentType 'application/json' -Body '{"customer":"Ajay","amount":199}'
   Invoke-RestMethod http://127.0.0.1:8200/api/orders
5. Trigger a controlled process crash:
   python .\backend_lab\crash_backend.py
   curl.exe http://127.0.0.1:8200/health
   (Expected: connection refused / no response.)
6. Manually verify recovery script:
   python .\backend_lab\restart_backend.py
   curl.exe http://127.0.0.1:8200/health
   Invoke-RestMethod http://127.0.0.1:8200/api/orders
   (Orders persist across restart.)

IMPORTANT: The first run is a MANUAL recovery test. It does NOT prove that
AegisOps automatically diagnosed or recovered the backend. For the automated
end-to-end test, bind this service to the existing agent and monitor after
reviewing current monitor.py, recovery_policy.py, and agents.json schema.

AGENT POLICY SAMPLE (merge only after reviewing existing policy):
  "lab-backend": {
    "health_url": "http://127.0.0.1:8200/health",
    "log_file": "D:\\AegisOps\\backend_lab\\runtime\\backend.log",
    "metadata": {"environment": "local-test", "owner": "Team Kairo"},
    "actions": {
      "RESTART_SERVICE": ["D:\\AegisOps\\.venv\\Scripts\\python.exe", "D:\\AegisOps\\backend_lab\\restart_backend.py"]
    }
  }

SECURITY: /test/crash requires the random session token and binds to localhost.
Do not expose port 8200 to the internet. Use separate tokens for the agent.
No unrestricted shell commands are accepted by the backend.
