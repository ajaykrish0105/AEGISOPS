"""Safely add agent-based SVC-004 handling to AegisOps Monitor V7.

Does not enable automatic recovery; creates a timestamped backup.
"""
from pathlib import Path
from datetime import datetime
import ast
import shutil
import sys

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / 'core' / 'monitor.py'
MARKER = '# AEGISOPS SVC-004 AGENT INTEGRATION V1'

INTEGRATION = '''\n\n# AEGISOPS SVC-004 AGENT INTEGRATION V1\ndef handle_agent_backend_failure(service, health, settings):\n    """Agent-only recovery for the explicitly allowlisted local demo backend."""\n    service_key = service["id"]\n    if service_key in ACTIVE_DOWN_SERVICES:\n        return\n    ACTIVE_DOWN_SERVICES.add(service_key)\n    incident_id = new_incident_id()\n    evidence = {\n        "service_id": service_key,\n        "service_name": service.get("name"),\n        "health_error": health.get("error"),\n        "http_status": health.get("http_status"),\n        "failure_type": "LOCAL_BACKEND_HEALTH_FAILURE",\n    }\n    analysis = {\n        "incident": "LOCAL_BACKEND_UNAVAILABLE",\n        "confidence": None,\n        "action": "RESTART_SERVICE",\n        "diagnostic_source": "DETERMINISTIC_HEALTH_POLICY",\n    }\n    safety = {"approved": False, "action": "RESTART_SERVICE", "reason": "Not yet evaluated."}\n    recovery = {"attempted": False, "success": False, "verified": False, "automatic": False}\n    status = "HUMAN_REVIEW_REQUIRED"\n    try:\n        update_runtime_status(pipeline_stage="EVIDENCE", active_service=service.get("name"))\n        from core import agent_client\n        binding = agent_client.find_binding(service_key)\n        if not binding or binding.get("agent_service") != "aegisops-demo-backend":\n            safety["reason"] = "Expected AGENT-001 demo backend binding is missing."\n        elif str(binding["agent"].get("id")) != "AGENT-001":\n            safety["reason"] = "Unexpected agent ID; recovery denied."\n        elif not settings.get("auto_recovery", True) or not service.get("auto_recovery", False):\n            safety["reason"] = "Automatic recovery disabled in global or service settings."\n        else:\n            update_runtime_status(pipeline_stage="SAFETY", active_service=service.get("name"))\n            capabilities = agent_client.get_service_capabilities(service_key)\n            # Client versions may return either the capabilities map or a response wrapping it.\n            caps = capabilities.get("capabilities", capabilities) if isinstance(capabilities, dict) else {}\n            if not isinstance(caps, dict) or caps.get("RESTART_SERVICE") is not True:\n                safety["reason"] = "Agent did not confirm RESTART_SERVICE authorization."\n            else:\n                safety = {"approved": True, "action": "RESTART_SERVICE", "reason": "Explicit AGENT-001 binding and action capability verified."}\n                update_runtime_status(pipeline_stage="RECOVERY", active_service=service.get("name"))\n                result = agent_client.execute_action(service_key, "RESTART_SERVICE", incident_id=incident_id)\n                recovery = dict(result) if isinstance(result, dict) else {"result": str(result)}\n                recovery["attempted"] = True\n                recovery["automatic"] = True\n                # Never claim success merely because the agent accepted the command.\n                update_runtime_status(pipeline_stage="VERIFY", active_service=service.get("name"))\n                for _ in range(12):\n                    verification = check_health(service)\n                    if verification.get("healthy"):\n                        recovery["verified"] = True\n                        recovery["success"] = True\n                        status = "RESOLVED"\n                        FAILURE_COUNTS[service_key] = 0\n                        break\n                    time.sleep(2)\n                if status != "RESOLVED":\n                    recovery["verified"] = False\n                    recovery["success"] = False\n                    status = "RECOVERY_FAILED"\n    except Exception as error:\n        safety["reason"] = "Agent communication or execution error: " + str(error)\n        status = "RECOVERY_FAILED" if recovery.get("attempted") else "HUMAN_REVIEW_REQUIRED"\n    finally:\n        incident = {\n            "id": incident_id, "service_id": service_key,\n            "service_name": service.get("name"),\n            "detected_at": datetime.now().isoformat(timespec="seconds"),\n            "status": status, "health": health, "evidence": evidence,\n            "analysis": analysis, "safety": safety, "recovery": recovery,\n        }\n        save_incident(incident)\n        notify(\n            title=f"{service.get('name')} {status}",\n            message=f"Agent recovery status: {status}. {safety.get('reason', '')}",\n            severity="SUCCESS" if status == "RESOLVED" else "WARNING",\n            incident_id=incident_id, service_name=service.get("name"),\n        )\n        update_runtime_status(pipeline_stage="MONITORING", active_service=None,\n                              last_incident_id=incident_id, last_incident_status=status)\n        print(f"[AGENT INCIDENT] {service.get('name')} -> {status}")\n        # Avoid retry storms: leave the down-service latch set until a healthy check.\n\n'''


def main():
    if not TARGET.is_file():
        raise FileNotFoundError(TARGET)
    original = TARGET.read_text(encoding='utf-8')
    if MARKER in original:
        print('[SKIP] Integration already installed')
        return
    old = '''        if is_local_service(service):\n            handle_local_failure('''
    new = '''        if str(service.get("id")) == "SVC-004":\n            handle_agent_backend_failure(service, health, settings)\n        elif is_local_service(service):\n            handle_local_failure('''
    if original.count(old) != 1 or original.count('def monitor_once():') != 1:
        raise RuntimeError('Unexpected monitor.py structure; no changes made')
    modified = original.replace(old, new, 1)
    modified = modified.replace('def monitor_once():', INTEGRATION + '\ndef monitor_once():', 1)
    ast.parse(modified)
    backup = TARGET.with_name('monitor.py.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(TARGET, backup)
    TARGET.write_text(modified, encoding='utf-8')
    print('[BACKUP]', backup.name)
    print('[OK] SVC-004 routed to agent-based handler')
    print('[SAFE] Auto-recovery remains OFF until agent connectivity and action contract are tested')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('[ERROR]', error, file=sys.stderr)
        sys.exit(1)
