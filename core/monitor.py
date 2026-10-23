import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# ============================================================
# AEGISOPS MONITOR V7
#
# Local service:
#   Detect -> Evidence -> AI -> Safety -> Restart -> Verify
#
# Remote service:
#   3 consecutive failures -> Evidence -> AI -> Safety Policy
#   -> Recovery Connector -> Redeploy/Restart -> Verify -> Notify
# ============================================================

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(CORE_DIR)
DATA_DIR = os.path.join(ROOT, "data")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SERVICES_FILE = os.path.join(DATA_DIR, "services.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
HISTORY_FILE = os.path.join(DATA_DIR, "incidents_history.json")
RUNTIME_FILE = os.path.join(DATA_DIR, "runtime_status.json")
SIMULATION_FILE = os.path.join(DATA_DIR, "recovery_simulation.json")

DEFAULT_SETTINGS = {
    "monitoring_enabled": True,
    "auto_recovery": True,
    "monitor_interval": 2,
    "confidence_threshold": 0.70,
}

REMOTE_TIMEOUT_SECONDS = 8.0
LOCAL_TIMEOUT_SECONDS = 2.0
REMOTE_FAILURES_BEFORE_INCIDENT = 3

FAILURE_COUNTS = {}
ACTIVE_DOWN_SERVICES = set()


# ============================================================
# IMPORT PROJECT MODULES
# ============================================================

def import_optional(module_name):
    try:
        return __import__(module_name, fromlist=["*"])
    except Exception as error:
        print(f"[MONITOR] Could not import {module_name}: {error}")
        return None


analyzer_module = import_optional("core.analyzer")
evidence_module = import_optional("core.evidence")
safety_module = import_optional("core.safety")
recovery_module = import_optional("core.recovery")
remote_recovery_module = import_optional("core.remote_recovery")
notifications_module = import_optional("core.notifications")
recovery_policy_module = import_optional("core.recovery_policy")


# ============================================================
# JSON
# ============================================================

def read_json(path, default):
    try:
        if not os.path.exists(path):
            return default

        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    except Exception as error:
        print("[MONITOR] JSON read error:", path, error)
        return default


def write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = path + ".tmp"

        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)

        os.replace(temp_path, path)
        return True

    except Exception as error:
        print("[MONITOR] JSON write error:", path, error)
        return False


# ============================================================
# CONFIG
# ============================================================

def get_settings():
    saved = read_json(SETTINGS_FILE, {})
    settings = DEFAULT_SETTINGS.copy()

    if isinstance(saved, dict):
        settings.update(saved)

    return settings


def get_services():
    services = read_json(SERVICES_FILE, [])

    if not isinstance(services, list):
        return []

    return [
        service
        for service in services
        if isinstance(service, dict)
        and service.get("id")
        and service.get("name")
        and service.get("health_url")
    ]


def is_local_service(service):
    url = str(service.get("health_url", "")).lower()
    name = str(service.get("name", "")).lower()

    return (
        name == "payment-api"
        or "127.0.0.1" in url
        or "localhost" in url
    )


# ============================================================
# RUNTIME
# ============================================================

def update_runtime_status(**kwargs):
    current = read_json(RUNTIME_FILE, {})

    if not isinstance(current, dict):
        current = {}

    current.update(kwargs)
    current["updated_at"] = datetime.now().isoformat(timespec="seconds")

    write_json(RUNTIME_FILE, current)


# ============================================================
# HEALTH
# ============================================================

def check_health(service):
    local = is_local_service(service)
    timeout = LOCAL_TIMEOUT_SECONDS if local else REMOTE_TIMEOUT_SECONDS

    try:
        request = urllib.request.Request(
            service["health_url"],
            headers={
                "User-Agent": "AegisOps-Monitor/7.0",
                "Cache-Control": "no-cache",
            },
        )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = int(response.status)
            healthy = 200 <= code < 400

            return {
                "healthy": healthy,
                "http_status": code,
                "error": None if healthy else f"HTTP {code}",
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }

    except urllib.error.HTTPError as error:
        return {
            "healthy": False,
            "http_status": error.code,
            "error": f"HTTP {error.code}: {error.reason}",
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }

    except Exception as error:
        return {
            "healthy": False,
            "http_status": None,
            "error": str(error),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }



# ============================================================
# SAFE OUTAGE SIMULATION
# ============================================================

def get_simulation():
    data = read_json(SIMULATION_FILE, {})

    if not isinstance(data, dict):
        return {}

    return data


def clear_simulation():
    write_json(SIMULATION_FILE, {})


def check_monitor_health(service):
    """
    Health check used only by the continuous monitor.

    If a recovery simulation is active for this service, AegisOps
    returns a synthetic DOWN result for the configured number of
    checks. The real website is NOT taken offline.

    Recovery verification still uses check_health(), so it checks
    the actual remote website after the connector is triggered.
    """
    simulation = get_simulation()

    active = bool(simulation.get("active"))
    service_id = str(simulation.get("service_id", "")).strip()
    remaining = int(simulation.get("remaining_failures", 0) or 0)

    if (
        active
        and service_id == str(service.get("id", "")).strip()
        and remaining > 0
    ):
        current_number = (
            int(simulation.get("total_failures", remaining) or remaining)
            - remaining
            + 1
        )

        simulation["remaining_failures"] = remaining - 1
        simulation["last_simulated_at"] = datetime.now().isoformat(
            timespec="seconds"
        )

        if simulation["remaining_failures"] <= 0:
            simulation["active"] = False
            simulation["completed_at"] = datetime.now().isoformat(
                timespec="seconds"
            )

        write_json(SIMULATION_FILE, simulation)

        print(
            f"[SIMULATION] {service.get('name')} synthetic outage "
            f"{current_number}/"
            f"{simulation.get('total_failures', REMOTE_FAILURES_BEFORE_INCIDENT)}"
        )

        return {
            "healthy": False,
            "http_status": None,
            "error": "AEGISOPS_SAFE_SIMULATED_OUTAGE",
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "simulated": True,
        }

    return check_health(service)


# ============================================================
# MODULE HELPERS
# ============================================================

def resolve_callable(module, candidates):
    if module is None:
        return None

    for name in candidates:
        func = getattr(module, name, None)

        if callable(func):
            return func

    return None


def collect_local_evidence(service):
    func = resolve_callable(
        evidence_module,
        [
            "collect_evidence",
            "gather_evidence",
            "build_evidence",
            "get_evidence",
        ],
    )

    service_name = service.get("name", "unknown")
    health = check_health(service)

    health_status = "UP" if health.get("healthy") else "DOWN"
    health_error = str(health.get("error") or "none")

    if func:
        try:
            result = func(
                service_name=service_name,
                health_status=health_status,
                health_error=health_error,
                failure_type="application_crash",
            )

            if isinstance(result, dict):
                result.setdefault("service_name", service_name)
                return result

        except Exception as error:
            print("[MONITOR] Evidence error:", error)

    return {
        "service_name": service_name,
        "health_status": health_status,
        "health_error": health_error,
        "failure_type": "application_crash",
        "process_crashed": not health.get("healthy", False),
        "timeout": bool(health.get("timeout", False)),
    }


def build_remote_evidence(service, health, failures):
    error_text = str(health.get("error") or "").lower()

    return {
        "service_name": service.get("name"),
        "service_id": service.get("id"),
        "health_url": service.get("health_url"),
        "failure_type": "remote_health_failure",
        "process_crashed": False,
        "health_down": True,
        "timeout": (
            "timed out" in error_text
            or "timeout" in error_text
        ),
        "connection_refused": "refused" in error_text,
        "memory_high": False,
        "cpu_high": False,
        "recent_deployment": False,
        "error_500": health.get("http_status") == 500,
        "http_status": health.get("http_status"),
        "health_error": health.get("error"),
        "consecutive_failures": failures,
        "checked_at": health.get("checked_at"),
    }


def analyze_incident(evidence):
    func = resolve_callable(
        analyzer_module,
        [
            "analyze_evidence",
            "analyze_incident",
            "analyze",
            "predict_incident",
            "classify_incident",
        ],
    )

    if func:
        try:
            result = func(evidence)

            if isinstance(result, dict):
                return result

        except Exception as error:
            print("[MONITOR] Analyzer error:", error)

    return {
        "incident": "UNKNOWN",
        "confidence": 0.0,
        "action": "HUMAN_REVIEW",
    }


def evaluate_safety(analysis):
    func = resolve_callable(
        safety_module,
        [
            "evaluate_action",
            "evaluate_safety",
            "check_safety",
            "validate_action",
        ],
    )

    if func:
        try:
            result = func(analysis)

            if isinstance(result, dict):
                return result

        except TypeError:
            try:
                result = func(
                    analysis.get("action"),
                    analysis.get("confidence"),
                )

                if isinstance(result, dict):
                    return result

            except Exception as error:
                print("[MONITOR] Safety error:", error)

        except Exception as error:
            print("[MONITOR] Safety error:", error)

    return {
        "approved": False,
        "action": analysis.get("action"),
        "reason": "Safety module unavailable or failed.",
    }


def execute_local_recovery(analysis, safety):
    func = resolve_callable(
        recovery_module,
        [
            "execute_recovery",
            "recover_service",
            "run_recovery",
        ],
    )

    if func is None:
        return {
            "attempted": False,
            "success": False,
            "verified": False,
            "reason": "Recovery module unavailable.",
        }

    possible_args = [
        (safety, analysis),
        (analysis.get("action"), safety),
        (safety,),
        tuple(),
    ]

    for args in possible_args:
        try:
            result = func(*args)

            if isinstance(result, dict):
                return result

        except TypeError:
            continue

        except Exception as error:
            print("[MONITOR] Recovery error:", error)
            break

    return {
        "attempted": True,
        "success": False,
        "verified": False,
        "reason": "Recovery execution failed.",
    }


# ============================================================
# NOTIFICATIONS
# ============================================================

def notify(title, message, severity, incident_id, service_name):
    if notifications_module is None:
        print(f"[NOTIFY] {severity}: {title} - {message}")
        return

    func = getattr(
        notifications_module,
        "create_notification",
        None,
    )

    if callable(func):
        try:
            func(
                title=title,
                message=message,
                severity=severity,
                incident_id=incident_id,
                service_name=service_name,
            )
        except Exception as error:
            print("[NOTIFY] Error:", error)


# ============================================================
# INCIDENT HISTORY
# ============================================================

def save_incident(incident):
    history = read_json(HISTORY_FILE, [])

    if not isinstance(history, list):
        history = []

    history.insert(0, incident)
    history = history[:200]

    write_json(HISTORY_FILE, history)


def new_incident_id():
    return "INC-" + datetime.now().strftime("%Y%m%d-%H%M%S")


# ============================================================
# LOCAL INCIDENT
# ============================================================

def handle_local_failure(service, health, settings):
    service_key = service["id"]

    if service_key in ACTIVE_DOWN_SERVICES:
        return

    ACTIVE_DOWN_SERVICES.add(service_key)

    update_runtime_status(
        pipeline_stage="EVIDENCE",
        active_service=service.get("name"),
    )

    evidence = collect_local_evidence(service)

    update_runtime_status(
        pipeline_stage="AI_ANALYSIS",
        active_service=service.get("name"),
    )

    analysis = analyze_incident(evidence)

    update_runtime_status(
        pipeline_stage="SAFETY",
        active_service=service.get("name"),
    )

    safety = evaluate_safety(analysis)
    threshold = float(
        settings.get("confidence_threshold", 0.70)
    )

    if float(analysis.get("confidence", 0) or 0) < threshold:
        safety = {
            **safety,
            "approved": False,
            "reason": (
                f"AI confidence "
                f"{float(analysis.get('confidence', 0))*100:.1f}% "
                f"is below configured threshold "
                f"{threshold*100:.0f}%."
            ),
        }

    if not settings.get("auto_recovery", True):
        safety = {
            **safety,
            "approved": False,
            "reason": "Global autonomous recovery is disabled.",
        }

    if not service.get("auto_recovery", True):
        safety = {
            **safety,
            "approved": False,
            "reason": "Auto recovery is disabled for this service.",
        }

    recovery = {
        "attempted": False,
        "success": False,
        "verified": False,
    }

    if safety.get("approved"):
        update_runtime_status(
            pipeline_stage="RECOVERY",
            active_service=service.get("name"),
        )

        recovery = execute_local_recovery(
            analysis,
            safety,
        )

    update_runtime_status(
        pipeline_stage="VERIFY",
        active_service=service.get("name"),
    )

    verification = check_health(service)

    if verification.get("healthy"):
        recovery["verified"] = True

        if recovery.get("attempted", True):
            recovery["success"] = True

        status = "RESOLVED"
        FAILURE_COUNTS[service_key] = 0
        ACTIVE_DOWN_SERVICES.discard(service_key)

    else:
        status = "RECOVERY_FAILED"

    incident = {
        "id": new_incident_id(),
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "detected_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "health": health,
        "evidence": evidence,
        "analysis": analysis,
        "safety": safety,
        "recovery": recovery,
    }

    save_incident(incident)

    notify(
        title=f"{service.get('name')} {status}",
        message=(
            f"AegisOps diagnosed "
            f"{analysis.get('incident', 'UNKNOWN')} and "
            f"attempted {analysis.get('action', 'UNKNOWN')}. "
            f"Verification: "
            f"{'PASSED' if recovery.get('verified') else 'FAILED'}."
        ),
        severity="SUCCESS" if status == "RESOLVED" else "ERROR",
        incident_id=incident["id"],
        service_name=service.get("name"),
    )

    update_runtime_status(
        pipeline_stage="MONITORING",
        active_service=None,
        last_incident_id=incident["id"],
        last_incident_status=status,
    )

    print(
        f"[INCIDENT] {service.get('name')} -> {status} | "
        f"{analysis.get('incident')} | "
        f"{analysis.get('action')}"
    )


# ============================================================
# REMOTE INCIDENT
# ============================================================

def handle_remote_failure(service, health, settings):
    service_key = service["id"]
    failures = FAILURE_COUNTS.get(service_key, 0)

    if failures < REMOTE_FAILURES_BEFORE_INCIDENT:
        print(
            f"[REMOTE] {service.get('name')} transient failure "
            f"{failures}/{REMOTE_FAILURES_BEFORE_INCIDENT}: "
            f"{health.get('error')}"
        )
        return

    if service_key in ACTIVE_DOWN_SERVICES:
        return

    ACTIVE_DOWN_SERVICES.add(service_key)

    update_runtime_status(pipeline_stage="EVIDENCE", active_service=service.get("name"))
    evidence = build_remote_evidence(service, health, failures)

    connector_status = {
        "configured": False,
        "connector_type": None,
        "capabilities": {},
    }
    if remote_recovery_module:
        func = getattr(remote_recovery_module, "get_connector_status", None)
        if callable(func):
            connector_status = func(service)

    update_runtime_status(pipeline_stage="AI_ANALYSIS", active_service=service.get("name"))

    plan = {
        "diagnosis": "REMOTE_HEALTH_FAILURE",
        "actions": ["REDEPLOY_SERVICE"] if connector_status.get("configured") else [],
        "reason": "Confirmed remote health-check failure.",
        "requires_human": not connector_status.get("configured"),
    }

    if recovery_policy_module:
        selector = getattr(recovery_policy_module, "build_remote_recovery_plan", None)
        if callable(selector):
            try:
                plan = selector(service, evidence, connector_status)
            except Exception as error:
                print("[POLICY] Error:", error)

    actions = list(plan.get("actions") or [])
    analysis = {
        "incident": plan.get("diagnosis", "REMOTE_HEALTH_FAILURE"),
        "confidence": 1.0,
        "action": actions[0] if actions else "HUMAN_REVIEW",
        "policy_action": actions[0] if actions else "HUMAN_REVIEW",
        "recovery_plan": actions,
        "diagnostic_source": "AUTONOMOUS_RECOVERY_POLICY",
        "reason": plan.get("reason"),
    }

    update_runtime_status(pipeline_stage="SAFETY", active_service=service.get("name"))

    global_auto = bool(settings.get("auto_recovery", True))
    service_auto = bool(service.get("auto_recovery", False))

    approved = global_auto and service_auto and bool(actions)

    safety = {
        "approved": approved,
        "action": analysis["action"],
        "reason": (
            "Automatic recovery is enabled and every action in the runbook requires an authorized connector."
            if approved else
            "No safe pre-authorized automatic recovery action is available."
        ),
    }

    attempts = []
    status = "HUMAN_REVIEW_REQUIRED"
    verified = False

    if approved and remote_recovery_module:
        trigger = getattr(remote_recovery_module, "trigger_remote_action", None)
        verify = getattr(remote_recovery_module, "verify_remote_service", None)

        for action in actions:
            update_runtime_status(
                pipeline_stage="RECOVERY",
                active_service=service.get("name"),
                active_action=action,
            )

            if not callable(trigger):
                attempts.append({"action": action, "attempted": False, "success": False, "reason": "Recovery connector module unavailable."})
                continue

            result = trigger(service, action)
            attempt = dict(result)
            attempt["action"] = action

            if result.get("success") and callable(verify):
                update_runtime_status(
                    pipeline_stage="VERIFY",
                    active_service=service.get("name"),
                    active_action=action,
                )
                verification = verify(
                    service,
                    check_health,
                    wait_seconds=120,
                    interval_seconds=10,
                )
                attempt.update(verification)

            attempts.append(attempt)

            if attempt.get("verified"):
                verified = True
                status = "RESOLVED"
                FAILURE_COUNTS[service_key] = 0
                ACTIVE_DOWN_SERVICES.discard(service_key)
                analysis["action"] = action
                analysis["policy_action"] = action
                break

        if not verified:
            status = "RECOVERY_FAILED"

    recovery = {
        "attempted": bool(attempts),
        "success": verified,
        "verified": verified,
        "automatic": True,
        "attempts": attempts,
        "executed_action": analysis.get("action") if verified else None,
    }

    incident = {
        "id": new_incident_id(),
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "detected_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "health": health,
        "evidence": evidence,
        "analysis": analysis,
        "safety": safety,
        "recovery": recovery,
        "connector": connector_status,
    }
    save_incident(incident)

    if status == "RESOLVED":
        notify(
            title=f"{service.get('name')} automatically recovered",
            message=(
                f"AegisOps detected a confirmed outage, automatically executed "
                f"{analysis.get('action')}, and verified the service healthy again."
            ),
            severity="SUCCESS",
            incident_id=incident["id"],
            service_name=service.get("name"),
        )
    elif status == "RECOVERY_FAILED":
        notify(
            title=f"{service.get('name')} automatic recovery failed",
            message="AegisOps exhausted the pre-authorized recovery runbook and could not verify service health.",
            severity="ERROR",
            incident_id=incident["id"],
            service_name=service.get("name"),
        )
    else:
        notify(
            title=f"{service.get('name')} requires human review",
            message="AegisOps detected the outage, but no safe pre-authorized connector action matched this failure.",
            severity="WARNING",
            incident_id=incident["id"],
            service_name=service.get("name"),
        )

    update_runtime_status(
        pipeline_stage="MONITORING",
        active_service=None,
        active_action=None,
        last_incident_id=incident["id"],
        last_incident_status=status,
    )

    print(f"[REMOTE INCIDENT] {service.get('name')} -> {status} | {analysis.get('action')}")


# ============================================================
# LOOP
# ============================================================



def verify_agent_recovery(service, required_successes=3, max_checks=12, interval_seconds=2):
    """Verify recovery only after consecutive successful service health checks."""
    consecutive_successes = 0
    for check_number in range(max_checks):
        verification = check_health(service)
        if verification.get("healthy"):
            consecutive_successes += 1
            if consecutive_successes >= required_successes:
                return {
                    "verified": True,
                    "success": True,
                    "verification_checks": check_number + 1,
                    "consecutive_successful_checks": consecutive_successes,
                }
        else:
            consecutive_successes = 0
        if check_number < max_checks - 1:
            time.sleep(interval_seconds)
    return {
        "verified": False,
        "success": False,
        "verification_checks": max_checks,
        "consecutive_successful_checks": consecutive_successes,
    }


# AEGISOPS SVC-004 AGENT INTEGRATION V1
def handle_agent_backend_failure(service, health, settings):
    """Agent-only recovery for the explicitly allowlisted local demo backend."""
    service_key = service["id"]
    if service_key in ACTIVE_DOWN_SERVICES:
        return
    ACTIVE_DOWN_SERVICES.add(service_key)
    incident_id = new_incident_id()
    evidence = {
        "service_id": service_key,
        "service_name": service.get("name"),
        "health_error": health.get("error"),
        "http_status": health.get("http_status"),
        "failure_type": "LOCAL_BACKEND_HEALTH_FAILURE",
    }
    analysis = {
        "incident": "LOCAL_BACKEND_UNAVAILABLE",
        "confidence": None,
        "action": "RESTART_SERVICE",
        "diagnostic_source": "DETERMINISTIC_HEALTH_POLICY",
    }
    safety = {"approved": False, "action": "RESTART_SERVICE", "reason": "Not yet evaluated."}
    recovery = {"attempted": False, "success": False, "verified": False, "automatic": False}
    status = "HUMAN_REVIEW_REQUIRED"
    try:
        update_runtime_status(pipeline_stage="EVIDENCE", active_service=service.get("name"))
        from core import agent_client
        binding = agent_client.find_binding(service_key)
        if not binding or binding.get("agent_service") != "aegisops-demo-backend":
            safety["reason"] = "Expected AGENT-001 demo backend binding is missing."
        elif str(binding["agent"].get("id")) != "AGENT-001":
            safety["reason"] = "Unexpected agent ID; recovery denied."
        elif not settings.get("auto_recovery", True) or not service.get("auto_recovery", False):
            safety["reason"] = "Automatic recovery disabled in global or service settings."
        else:
            update_runtime_status(pipeline_stage="SAFETY", active_service=service.get("name"))
            capabilities = agent_client.get_service_capabilities(service_key)
            # Client versions may return either the capabilities map or a response wrapping it.
            caps = capabilities.get("capabilities", capabilities) if isinstance(capabilities, dict) else {}
            if not isinstance(caps, dict) or caps.get("RESTART_SERVICE") is not True:
                safety["reason"] = "Agent did not confirm RESTART_SERVICE authorization."
            else:
                safety = {"approved": True, "action": "RESTART_SERVICE", "reason": "Explicit AGENT-001 binding and action capability verified."}
                update_runtime_status(pipeline_stage="RECOVERY", active_service=service.get("name"))
                result = agent_client.execute_action(service_key, "RESTART_SERVICE", incident_id=incident_id)
                recovery = dict(result) if isinstance(result, dict) else {"result": str(result)}
                recovery["attempted"] = True
                recovery["automatic"] = True
                action_succeeded = bool(recovery.get("success"))
                recovery["action_succeeded"] = action_succeeded
                # A healthy service alone cannot turn a failed action into a successful recovery.
                if not action_succeeded:
                    recovery["verified"] = False
                    recovery["success"] = False
                    recovery["verification_skipped_reason"] = "Agent action did not report success."
                    status = "RECOVERY_FAILED"
                else:
                    update_runtime_status(pipeline_stage="VERIFY", active_service=service.get("name"))
                    verification_result = verify_agent_recovery(service)
                    recovery.update(verification_result)
                    recovery["action_succeeded"] = True
                    if verification_result["verified"]:
                        status = "RESOLVED"
                        FAILURE_COUNTS[service_key] = 0
                    else:
                        status = "RECOVERY_FAILED"
    except Exception as error:
        safety["reason"] = "Agent communication or execution error: " + str(error)
        status = "RECOVERY_FAILED" if recovery.get("attempted") else "HUMAN_REVIEW_REQUIRED"
    finally:
        incident = {
            "id": incident_id, "service_id": service_key,
            "service_name": service.get("name"),
            "detected_at": datetime.now().isoformat(timespec="seconds"),
            "status": status, "health": health, "evidence": evidence,
            "analysis": analysis, "safety": safety, "recovery": recovery,
        }
        save_incident(incident)
        notify(
            title=f"{service.get('name')} {status}",
            message=f"Agent recovery status: {status}. {safety.get('reason', '')}",
            severity="SUCCESS" if status == "RESOLVED" else "WARNING",
            incident_id=incident_id, service_name=service.get("name"),
        )
        update_runtime_status(pipeline_stage="MONITORING", active_service=None,
                              last_incident_id=incident_id, last_incident_status=status)
        print(f"[AGENT INCIDENT] {service.get('name')} -> {status}")
        # Avoid retry storms: leave the down-service latch set until a healthy check.


def monitor_once():
    settings = get_settings()

    if not settings.get("monitoring_enabled", True):
        update_runtime_status(
            pipeline_stage="PAUSED",
            monitor_status="PAUSED",
        )
        return

    services = get_services()

    update_runtime_status(
        pipeline_stage="MONITORING",
        monitor_status="RUNNING",
        registered_services=len(services),
    )

    for service in services:
        if not service.get("monitoring_enabled", True):
            continue

        service_key = service["id"]
        health = check_monitor_health(service)

        if health["healthy"]:
            if FAILURE_COUNTS.get(service_key, 0) > 0:
                print(
                    f"[HEALTHY] {service.get('name')} recovered "
                    f"after {FAILURE_COUNTS.get(service_key, 0)} "
                    f"failed check(s)"
                )

            FAILURE_COUNTS[service_key] = 0
            ACTIVE_DOWN_SERVICES.discard(service_key)
            continue

        FAILURE_COUNTS[service_key] = (
            FAILURE_COUNTS.get(service_key, 0) + 1
        )

        if str(service.get("id")) == "SVC-004":
            handle_agent_backend_failure(service, health, settings)
        elif is_local_service(service):
            handle_local_failure(
                service,
                health,
                settings,
            )
        else:
            handle_remote_failure(
                service,
                health,
                settings,
            )


def run_monitor():
    print("=" * 70)
    print("AEGISOPS MONITOR V7")
    print("=" * 70)
    print(
        "Remote failures required:",
        REMOTE_FAILURES_BEFORE_INCIDENT,
    )
    print(
        "Remote connector env     :",
        "AEGISOPS_RECOVERY_<SERVICE_ID>",
    )
    print(
        "Safe outage simulation   :",
        "data/recovery_simulation.json",
    )
    print("=" * 70)

    while True:
        try:
            monitor_once()

        except KeyboardInterrupt:
            print("\n[MONITOR] Stopped by user.")
            break

        except Exception as error:
            print("[MONITOR] Loop error:", error)

            update_runtime_status(
                pipeline_stage="ERROR",
                monitor_status="ERROR",
                error=str(error),
            )

        settings = get_settings()

        try:
            interval = max(
                1,
                int(
                    settings.get(
                        "monitor_interval",
                        2,
                    )
                ),
            )
        except Exception:
            interval = 2

        time.sleep(interval)


if __name__ == "__main__":
    run_monitor()
