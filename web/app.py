from flask import Flask, jsonify, render_template, request
import json
import os
import psutil
import time
import urllib.request
import urllib.error
import sys
from datetime import datetime
from urllib.parse import urlparse

# ============================================================
# AEGISOPS WEB PLATFORM V7
# Notifications UI + Aegis AI contextual assistant
# ============================================================

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(WEB_DIR)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from core import agent_client
except Exception:
    agent_client = None
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

STATE_FILE = os.path.join(DATA_DIR, "service_state.json")
EVIDENCE_FILE = os.path.join(DATA_DIR, "latest_evidence.json")
RUNTIME_FILE = os.path.join(DATA_DIR, "runtime_status.json")
HISTORY_FILE = os.path.join(DATA_DIR, "incidents_history.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SERVICES_FILE = os.path.join(DATA_DIR, "services.json")
NOTIFICATIONS_FILE = os.path.join(DATA_DIR, "notifications.json")
AGENTS_FILE = os.path.join(DATA_DIR, "agents.json")

DEFAULT_SETTINGS = {
    "monitoring_enabled": True,
    "auto_recovery": True,
    "monitor_interval": 2,
    "confidence_threshold": 0.70,
}

DEFAULT_SERVICE = {
    "id": "SVC-001",
    "name": "payment-api",
    "health_url": "http://127.0.0.1:8000/health",
    "service_type": "API",
    "monitoring_enabled": True,
    "auto_recovery": True,
    "created_at": "2026-10-07",
}

REMOTE_TIMEOUT_SECONDS = 8.0
LOCAL_TIMEOUT_SECONDS = 2.0
REMOTE_FAILURES_BEFORE_DOWN = 3

HEALTH_CACHE = {}

app = Flask(__name__, template_folder="templates", static_folder="static")


# ============================================================
# JSON HELPERS
# ============================================================

def read_json(path, default):
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        print("[WEB] JSON read error:", path, error)
        return default


def write_json(path, data):
    try:
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4)
        os.replace(temp_path, path)
        return True
    except Exception as error:
        print("[WEB] JSON write error:", path, error)
        return False



# ============================================================
# INFRASTRUCTURE AGENTS
# ============================================================

def normalize_agent(agent):
    agent_id = str(agent.get("id", "")).strip().upper()
    return {
        "id": agent_id,
        "name": str(agent.get("name", agent_id)).strip(),
        "base_url": str(agent.get("base_url", "")).strip().rstrip("/"),
        "enabled": bool(agent.get("enabled", True)),
        "bindings": agent.get("bindings", []) if isinstance(agent.get("bindings", []), list) else [],
        "created_at": str(agent.get("created_at", datetime.now().isoformat(timespec="seconds"))),
    }


def get_agents_registry():
    data = read_json(AGENTS_FILE, [])
    if not isinstance(data, list):
        return []
    return [
        normalize_agent(item)
        for item in data
        if isinstance(item, dict) and item.get("id") and item.get("base_url")
    ]


def save_agents_registry(items):
    return write_json(AGENTS_FILE, items)


# ============================================================
# SETTINGS / SERVICES
# ============================================================

def get_settings():
    saved = read_json(SETTINGS_FILE, {})
    settings = DEFAULT_SETTINGS.copy()
    if isinstance(saved, dict):
        settings.update(saved)
    return settings


def normalize_service(service):
    return {
        "id": str(service.get("id", "")).strip(),
        "name": str(service.get("name", "")).strip(),
        "health_url": str(service.get("health_url", "")).strip(),
        "service_type": str(service.get("service_type", "API")).strip().upper(),
        "monitoring_enabled": bool(service.get("monitoring_enabled", True)),
        "auto_recovery": bool(service.get("auto_recovery", True)),
        "created_at": str(service.get("created_at", datetime.now().isoformat(timespec="seconds"))),
    }


def get_services():
    services = read_json(SERVICES_FILE, [])
    if not isinstance(services, list):
        services = []

    cleaned = []
    for item in services:
        if isinstance(item, dict):
            service = normalize_service(item)
            if service["id"] and service["name"] and service["health_url"]:
                cleaned.append(service)

    if not cleaned:
        cleaned = [DEFAULT_SERVICE.copy()]
        write_json(SERVICES_FILE, cleaned)

    return cleaned


def save_services(services):
    return write_json(SERVICES_FILE, services)


def get_service_by_id(service_id):
    for service in get_services():
        if service["id"] == service_id:
            return service
    return None


def get_primary_service():
    services = get_services()
    for service in services:
        if service["name"].lower() == "payment-api":
            return service
    return services[0] if services else DEFAULT_SERVICE.copy()


def next_service_id(services):
    highest = 0
    for service in services:
        raw = str(service.get("id", ""))
        if raw.startswith("SVC-"):
            try:
                highest = max(highest, int(raw.split("-", 1)[1]))
            except Exception:
                pass
    return f"SVC-{highest + 1:03d}"


def valid_health_url(url):
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_local_service(service):
    url = str(service.get("health_url", "")).lower()
    name = str(service.get("name", "")).lower()
    return (
        name == "payment-api"
        or "127.0.0.1" in url
        or "localhost" in url
    )



# ============================================================
# REMOTE RECOVERY CONNECTORS
# ============================================================

def connector_env_name(service):
    raw = str(service.get("id", "UNKNOWN")).upper()
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw)
    return f"AEGISOPS_RECOVERY_{safe}"


def get_connector_status(service):
    if is_local_service(service):
        return {
            "configured": True,
            "type": "LOCAL_PROCESS",
            "env_name": None,
            "message": "Local process recovery is built in.",
        }

    env_name = connector_env_name(service)
    configured = bool(os.environ.get(env_name, "").strip())

    return {
        "configured": configured,
        "type": "GENERIC_WEBHOOK" if configured else None,
        "env_name": env_name,
        "message": (
            "Remote recovery connector is configured."
            if configured
            else f"Set environment variable {env_name} with the provider recovery webhook."
        ),
    }


def trigger_connector_test(service):
    status = get_connector_status(service)

    if is_local_service(service):
        return {
            "success": False,
            "message": "Local payment-api uses built-in recovery; no remote connector test is required.",
        }

    if not status["configured"]:
        return {
            "success": False,
            "message": status["message"],
        }

    hook = os.environ.get(status["env_name"], "").strip()

    payload = {
        "source": "AegisOps",
        "action": "CONNECTOR_TEST",
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "requested_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        req = urllib.request.Request(
            hook,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AegisOps-Connector-Test/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=20) as response:
            code = int(response.status)
            ok = 200 <= code < 300

            return {
                "success": ok,
                "http_status": code,
                "message": (
                    f"Connector accepted the request (HTTP {code})."
                    if ok
                    else f"Connector returned HTTP {code}."
                ),
            }

    except urllib.error.HTTPError as error:
        return {
            "success": False,
            "http_status": error.code,
            "message": f"Connector test failed: HTTP {error.code} {error.reason}",
        }

    except Exception as error:
        return {
            "success": False,
            "http_status": None,
            "message": f"Connector test failed: {error}",
        }


# ============================================================
# HEALTH CHECKING
# ============================================================

def raw_health_check(service, timeout):
    try:
        req = urllib.request.Request(
            service["health_url"],
            headers={
                "User-Agent": "AegisOps-Web/7.0",
                "Cache-Control": "no-cache",
            },
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            code = int(response.status)
            healthy = 200 <= code < 400
            return {
                **service,
                "status": "HEALTHY" if healthy else "DOWN",
                "online": healthy,
                "http_status": code,
                "error": None if healthy else f"Unexpected HTTP status {code}",
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }

    except urllib.error.HTTPError as error:
        return {
            **service,
            "status": "DOWN",
            "online": False,
            "http_status": error.code,
            "error": f"HTTP {error.code}: {error.reason}",
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }

    except Exception as error:
        return {
            **service,
            "status": "DOWN",
            "online": False,
            "http_status": None,
            "error": str(error),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }


def check_service_health(service, force=False):
    service_id = service["id"]
    local = is_local_service(service)
    timeout = LOCAL_TIMEOUT_SECONDS if local else REMOTE_TIMEOUT_SECONDS

    cache = HEALTH_CACHE.setdefault(
        service_id,
        {
            "failures": 0,
            "last_good": None,
            "last_result": None,
            "last_check_epoch": 0.0,
        },
    )

    if not force and not local:
        age = time.time() - float(cache.get("last_check_epoch", 0.0))
        if age < 3.0 and cache.get("last_result"):
            return cache["last_result"]

    raw = raw_health_check(service, timeout=timeout)
    cache["last_check_epoch"] = time.time()

    if raw["online"]:
        cache["failures"] = 0
        cache["last_good"] = raw.copy()
        cache["last_result"] = raw.copy()
        return raw

    if local:
        cache["failures"] = cache.get("failures", 0) + 1
        cache["last_result"] = raw.copy()
        return raw

    cache["failures"] = cache.get("failures", 0) + 1
    failures = cache["failures"]

    if failures < REMOTE_FAILURES_BEFORE_DOWN:
        degraded = {
            **service,
            "status": "DEGRADED",
            "online": None,
            "http_status": raw.get("http_status"),
            "error": (
                f"Transient check failure {failures}/{REMOTE_FAILURES_BEFORE_DOWN}: "
                f"{raw.get('error') or 'No response'}"
            ),
            "checked_at": raw["checked_at"],
            "consecutive_failures": failures,
        }
        cache["last_result"] = degraded.copy()
        return degraded

    down = {
        **raw,
        "status": "DOWN",
        "online": False,
        "consecutive_failures": failures,
    }
    cache["last_result"] = down.copy()
    return down


# ============================================================
# INCIDENTS / NOTIFICATIONS
# ============================================================

def get_incidents():
    incidents = read_json(HISTORY_FILE, [])
    return incidents if isinstance(incidents, list) else []


def get_notifications(limit=100):
    items = read_json(NOTIFICATIONS_FILE, [])
    if not isinstance(items, list):
        items = []
    return items[:max(1, int(limit))]


def get_unread_notification_count():
    return sum(1 for item in get_notifications(300) if not item.get("read", False))


def mark_all_notifications_read():
    items = read_json(NOTIFICATIONS_FILE, [])
    if not isinstance(items, list):
        items = []

    for item in items:
        item["read"] = True

    return write_json(NOTIFICATIONS_FILE, items)



def create_web_notification(title, message, severity="INFO", incident_id=None, service_name=None):
    items = read_json(NOTIFICATIONS_FILE, [])
    if not isinstance(items, list):
        items = []
    item = {
        "id": "NTF-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"),
        "title": str(title),
        "message": str(message),
        "severity": str(severity).upper(),
        "incident_id": incident_id,
        "service_name": service_name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "read": False,
    }
    items.insert(0, item)
    write_json(NOTIFICATIONS_FILE, items[:300])
    return item

def save_web_incident(incident):
    incidents = read_json(HISTORY_FILE, [])
    if not isinstance(incidents, list):
        incidents = []
    incidents.insert(0, incident)
    write_json(HISTORY_FILE, incidents[:200])

# ============================================================
# DASHBOARD
# ============================================================

def get_system_metrics():
    try:
        return {
            "cpu": round(psutil.cpu_percent(interval=0.05), 1),
            "memory": round(psutil.virtual_memory().percent, 1),
        }
    except Exception:
        return {"cpu": 0, "memory": 0}


def build_dashboard_data():
    primary = get_primary_service()
    service = check_service_health(primary)
    system = get_system_metrics()
    evidence = read_json(EVIDENCE_FILE, {})
    state = read_json(STATE_FILE, {})
    runtime = read_json(RUNTIME_FILE, {})
    incidents = get_incidents()
    settings = get_settings()

    services = get_services()
    healthy_count = 0
    down_count = 0
    degraded_count = 0

    for item in services:
        health = check_service_health(item)
        if health["status"] == "HEALTHY":
            healthy_count += 1
        elif health["status"] == "DOWN":
            down_count += 1
        else:
            degraded_count += 1

    return {
        "aegisops": {
            "status": "OPERATIONAL",
            "monitoring": settings.get("monitoring_enabled", True),
            "auto_recovery": settings.get("auto_recovery", True),
            "pipeline_stage": runtime.get("pipeline_stage", "MONITORING"),
        },
        "service": service,
        "system": system,
        "evidence": evidence,
        "service_state": state,
        "runtime": runtime,
        "latest_incident": incidents[0] if incidents else None,
        "incident_count": len(incidents),
        "service_count": len(services),
        "healthy_service_count": healthy_count,
        "down_service_count": down_count,
        "degraded_service_count": degraded_count,
        "unread_notifications": get_unread_notification_count(),
        "settings": settings,
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


# ============================================================
# ASSISTANT
# ============================================================

def find_service_by_name_from_text(question):
    q = question.lower()
    for service in get_services():
        name = service["name"].lower()
        if name in q:
            return service
        compact = name.replace(" ", "")
        if compact and compact in q.replace(" ", ""):
            return service
    return None


def get_incidents_for_service(service_name):
    name = str(service_name).lower()
    return [
        incident
        for incident in get_incidents()
        if str(
            incident.get("service_name")
            or incident.get("service")
            or incident.get("evidence", {}).get("service_name")
            or ""
        ).lower() == name
    ]


def incident_summary(incident):
    if not incident:
        return "No incident is available."

    analysis = incident.get("analysis", {}) or {}
    safety = incident.get("safety", {}) or {}
    recovery = incident.get("recovery", {}) or {}

    confidence = float(analysis.get("confidence", 0) or 0) * 100

    return (
        f"Incident {incident.get('id', 'UNKNOWN')} for "
        f"{incident.get('service_name', 'unknown service')} is "
        f"{incident.get('status', 'UNKNOWN')}. "
        f"Diagnosis: {analysis.get('incident', 'UNKNOWN')} "
        f"({confidence:.1f}% confidence). "
        f"Recommended action: "
        f"{analysis.get('policy_action') or analysis.get('action', 'UNKNOWN')}. "
        f"Safety: {'APPROVED' if safety.get('approved') else 'BLOCKED'}. "
        f"Recovery attempted: {bool(recovery.get('attempted'))}. "
        f"Verified: {bool(recovery.get('verified'))}."
    )


def generate_assistant_answer(user_message):
    question = user_message.lower().strip()
    services = get_services()
    incidents = get_incidents()
    notifications = get_notifications(30)
    settings = get_settings()
    target_service = find_service_by_name_from_text(question)

    if question in ("hi", "hello", "hey", "hai"):
        return (
            "Hello. I am Aegis AI. I can explain current service health, "
            "incidents, evidence, safety decisions, recovery actions, "
            "notifications and the AegisOps workflow."
        )

    if any(p in question for p in ("what is aegisops", "explain aegisops", "how aegisops works", "how does aegisops work")):
        return (
            "AegisOps monitors registered services, confirms failures, collects evidence, "
            "runs incident analysis, applies a safety policy, executes an allowed recovery "
            "through a local or remote connector, verifies service health, records the incident, "
            "and creates a notification."
        )

    if any(p in question for p in ("how many services", "list services", "all services", "registered services")):
        return (
            f"AegisOps currently has {len(services)} registered service(s): "
            + ", ".join(service["name"] for service in services)
            + "."
        )

    if target_service and any(word in question for word in ("health", "status", "online", "down", "running", "healthy")):
        health = check_service_health(target_service, force=True)
        if health["status"] == "HEALTHY":
            return (
                f"{target_service['name']} is HEALTHY. "
                f"The endpoint returned HTTP {health.get('http_status')}."
            )
        if health["status"] == "DEGRADED":
            return (
                f"{target_service['name']} is DEGRADED. "
                f"AegisOps is waiting for repeated failures before declaring it DOWN. "
                f"Current evidence: {health.get('error')}."
            )
        return (
            f"{target_service['name']} is DOWN. "
            f"Current health error: {health.get('error') or 'unknown'}."
        )

    if target_service and any(word in question for word in ("incident", "crash", "failed", "failure", "recover", "recovery", "why", "evidence")):
        related = get_incidents_for_service(target_service["name"])
        if not related:
            return f"No incident is currently recorded for {target_service['name']}."
        latest = related[0]

        if "evidence" in question:
            evidence = latest.get("evidence", {}) or {}
            return (
                f"Latest evidence for {target_service['name']}: "
                f"failure_type={evidence.get('failure_type', '--')}, "
                f"http_status={evidence.get('http_status', '--')}, "
                f"timeout={evidence.get('timeout', '--')}, "
                f"connection_refused={evidence.get('connection_refused', '--')}, "
                f"process_crashed={evidence.get('process_crashed', '--')}, "
                f"consecutive_failures={evidence.get('consecutive_failures', '--')}."
            )

        return incident_summary(latest)

    if any(p in question for p in ("latest incident", "what happened", "last incident", "incident summary")):
        return incident_summary(incidents[0] if incidents else None)

    if "evidence" in question and incidents:
        evidence = incidents[0].get("evidence", {}) or {}
        return (
            f"Latest incident evidence: "
            f"failure_type={evidence.get('failure_type', '--')}, "
            f"http_status={evidence.get('http_status', '--')}, "
            f"timeout={evidence.get('timeout', '--')}, "
            f"connection_refused={evidence.get('connection_refused', '--')}, "
            f"process_crashed={evidence.get('process_crashed', '--')}, "
            f"recent_deployment={evidence.get('recent_deployment', '--')}."
        )

    if any(word in question for word in ("safety", "safe", "approved", "blocked")) and incidents:
        latest = incidents[0]
        safety = latest.get("safety", {}) or {}
        return (
            f"For {latest.get('id', 'the latest incident')}, the safety decision was "
            f"{'APPROVED' if safety.get('approved') else 'BLOCKED'}. "
            f"Reason: {safety.get('reason') or 'No reason recorded.'}"
        )

    if any(word in question for word in ("recovery", "restart", "redeploy", "action", "fixed", "resolve")) and incidents:
        latest = incidents[0]
        analysis = latest.get("analysis", {}) or {}
        recovery = latest.get("recovery", {}) or {}
        action = analysis.get("policy_action") or analysis.get("action", "UNKNOWN")
        return (
            f"For {latest.get('id', 'the latest incident')}, AegisOps selected {action}. "
            f"Recovery attempted={bool(recovery.get('attempted'))}, "
            f"success={bool(recovery.get('success'))}, "
            f"verified={bool(recovery.get('verified'))}. "
            f"Final status: {latest.get('status', 'UNKNOWN')}."
        )

    if any(word in question for word in ("notification", "alert", "alerts")):
        unread = sum(1 for item in notifications if not item.get("read", False))
        if not notifications:
            return "No notifications are currently recorded."
        latest = notifications[0]
        return (
            f"There are {unread} unread notification(s). "
            f"Latest: {latest.get('title', 'Notification')} — "
            f"{latest.get('message', '')}"
        )

    if any(word in question for word in ("setting", "monitoring", "threshold", "configuration")):
        return (
            f"Monitoring is {'enabled' if settings.get('monitoring_enabled') else 'disabled'}, "
            f"global auto recovery is {'enabled' if settings.get('auto_recovery') else 'disabled'}, "
            f"monitor interval is {settings.get('monitor_interval')} seconds, "
            f"and the minimum AI confidence threshold is "
            f"{float(settings.get('confidence_threshold', 0.70))*100:.0f}%."
        )

    if "connector" in question:
        if target_service:
            status = get_connector_status(target_service)
            if status["configured"]:
                return (
                    f"{target_service['name']} has a configured "
                    f"{status.get('type') or 'recovery'} connector. "
                    "A confirmed remote outage can use it for automatic recovery, "
                    "followed by health verification."
                )
            return (
                f"{target_service['name']} does not have a remote recovery connector configured. "
                f"Set the environment variable {status.get('env_name')} with the provider recovery webhook."
            )

        configured = []
        missing = []

        for service in services:
            status = get_connector_status(service)
            (configured if status["configured"] else missing).append(service["name"])

        return (
            f"Configured recovery connectors: {', '.join(configured) if configured else 'none'}. "
            f"Missing remote connectors: {', '.join(missing) if missing else 'none'}."
        )

    if incidents:
        return (
            "I can answer questions about current service health, registered services, "
            "the latest incident, evidence, safety, recovery, notifications, settings, "
            "or how AegisOps works. "
            + incident_summary(incidents[0])
        )

    return (
        "No incident history is available yet. "
        "Ask me about service health, registered services, settings, or how AegisOps works."
    )


# ============================================================
# API ROUTES
# ============================================================


@app.route("/api/infrastructure", methods=["GET"])
def api_infrastructure():
    agents = []

    for agent in get_agents_registry():
        snapshot = {
            "online": False,
            "services": [],
            "error": "Agent client unavailable.",
            "token_env": None,
        }

        if agent_client:
            snapshot = agent_client.get_agent_snapshot(agent)

        agents.append({
            **agent,
            "snapshot": snapshot,
        })

    return jsonify({
        "agents": agents,
        "count": len(agents),
        "online": sum(1 for item in agents if item["snapshot"].get("online")),
    })


@app.route("/api/infrastructure", methods=["POST"])
def api_add_infrastructure_agent():
    payload = request.get_json(silent=True) or {}

    agent_id = str(payload.get("id", "")).strip().upper()
    name = str(payload.get("name", "")).strip()
    base_url = str(payload.get("base_url", "")).strip().rstrip("/")

    if not agent_id or not name or not base_url:
        return jsonify({"message": "Agent ID, name and base URL are required."}), 400

    if not base_url.startswith(("http://", "https://")):
        return jsonify({"message": "Agent URL must use http:// or https://"}), 400

    agents = get_agents_registry()
    if any(item["id"] == agent_id for item in agents):
        return jsonify({"message": "Agent ID already exists."}), 409

    agent = normalize_agent({
        "id": agent_id,
        "name": name,
        "base_url": base_url,
        "enabled": True,
        "bindings": [],
    })

    agents.append(agent)
    save_agents_registry(agents)

    token_env = (
        agent_client.token_env_name(agent_id)
        if agent_client else
        "AEGISOPS_AGENT_TOKEN_" + agent_id.replace("-", "_")
    )

    return jsonify({
        "message": "Agent registered. Set its token environment variable before connecting.",
        "agent": agent,
        "token_env": token_env,
    }), 201


@app.route("/api/infrastructure/<agent_id>/check", methods=["POST"])
def api_check_infrastructure_agent(agent_id):
    agent = next(
        (item for item in get_agents_registry() if item["id"] == agent_id),
        None,
    )

    if not agent:
        return jsonify({"message": "Agent not found."}), 404

    if not agent_client:
        return jsonify({"message": "Agent client module unavailable."}), 500

    snapshot = agent_client.get_agent_snapshot(agent)
    return jsonify(snapshot), (200 if snapshot.get("online") else 502)


@app.route("/api/infrastructure/<agent_id>/bind", methods=["POST"])
def api_bind_infrastructure_agent(agent_id):
    payload = request.get_json(silent=True) or {}
    service_id = str(payload.get("service_id", "")).strip()
    agent_service = str(payload.get("agent_service", "")).strip()

    if not service_id or not agent_service:
        return jsonify({"message": "service_id and agent_service are required."}), 400

    agents = get_agents_registry()
    target = None

    for agent in agents:
        if agent["id"] == agent_id:
            target = agent
            break

    if not target:
        return jsonify({"message": "Agent not found."}), 404

    bindings = [
        item for item in target.get("bindings", [])
        if str(item.get("service_id")) != service_id
    ]
    bindings.append({
        "service_id": service_id,
        "agent_service": agent_service,
    })
    target["bindings"] = bindings

    save_agents_registry(agents)

    return jsonify({
        "message": "Service bound to AegisOps Agent.",
        "bindings": bindings,
    })


@app.route("/api/infrastructure/<agent_id>", methods=["DELETE"])
def api_delete_infrastructure_agent(agent_id):
    agents = get_agents_registry()
    new_agents = [item for item in agents if item["id"] != agent_id]

    if len(new_agents) == len(agents):
        return jsonify({"message": "Agent not found."}), 404

    save_agents_registry(new_agents)
    return jsonify({"message": "Agent removed."})


@app.route("/api/dashboard", methods=["GET"])
def api_dashboard():
    return jsonify(build_dashboard_data())


@app.route("/api/services", methods=["GET"])
def api_services():
    services = get_services()
    include_health = request.args.get("health", "1") != "0"
    results = []

    for service in services:
        item = (
            check_service_health(service)
            if include_health
            else dict(service)
        )
        item["connector"] = get_connector_status(service)
        results.append(item)

    return jsonify({"success": True, "count": len(results), "services": results})


@app.route("/api/services", methods=["POST"])
def api_add_service():
    body = request.get_json(silent=True) or {}

    name = str(body.get("name", "")).strip()
    health_url = str(body.get("health_url", "")).strip()
    service_type = str(body.get("service_type", "API")).strip().upper()

    if not name:
        return jsonify({"success": False, "message": "Service name is required."}), 400

    if not health_url:
        return jsonify({"success": False, "message": "Health URL is required."}), 400

    if not valid_health_url(health_url):
        return jsonify({"success": False, "message": "Enter a valid http:// or https:// health URL."}), 400

    if service_type == "WEBAPP":
        service_type = "WEB APP"

    if service_type not in ("API", "WEB APP", "WORKER", "OTHER"):
        service_type = "OTHER"

    services = get_services()

    for existing in services:
        if existing["name"].lower() == name.lower():
            return jsonify({"success": False, "message": "A service with this name already exists."}), 409

        if existing["health_url"].rstrip("/").lower() == health_url.rstrip("/").lower():
            return jsonify({"success": False, "message": "This health URL is already connected."}), 409

    service = {
        "id": next_service_id(services),
        "name": name,
        "health_url": health_url,
        "service_type": service_type,
        "monitoring_enabled": bool(body.get("monitoring_enabled", True)),
        "auto_recovery": bool(body.get("auto_recovery", False)),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    services.append(service)

    if not save_services(services):
        return jsonify({"success": False, "message": "Unable to save service."}), 500

    health = check_service_health(service, force=True)

    return jsonify({
        "success": True,
        "message": "Service connected successfully.",
        "service": health,
    }), 201


@app.route("/api/services/<service_id>/check", methods=["POST"])
def api_check_service(service_id):
    service = get_service_by_id(service_id)

    if not service:
        return jsonify({"success": False, "message": "Service not found."}), 404

    return jsonify({
        "success": True,
        "service": check_service_health(service, force=True),
    })


@app.route("/api/services/<service_id>", methods=["PATCH"])
def api_update_service(service_id):
    body = request.get_json(silent=True) or {}
    services = get_services()
    target = None

    for service in services:
        if service["id"] == service_id:
            target = service
            break

    if target is None:
        return jsonify({"success": False, "message": "Service not found."}), 404

    if "monitoring_enabled" in body:
        target["monitoring_enabled"] = bool(body["monitoring_enabled"])

    if "auto_recovery" in body:
        target["auto_recovery"] = bool(body["auto_recovery"])

    if not save_services(services):
        return jsonify({"success": False, "message": "Unable to update service."}), 500

    return jsonify({"success": True, "message": "Service updated.", "service": target})


@app.route("/api/services/<service_id>", methods=["DELETE"])
def api_remove_service(service_id):
    services = get_services()
    target = None

    for service in services:
        if service["id"] == service_id:
            target = service
            break

    if target is None:
        return jsonify({"success": False, "message": "Service not found."}), 404

    if target["name"].lower() == "payment-api":
        return jsonify({
            "success": False,
            "message": "payment-api is the protected local recovery demo.",
        }), 409

    updated = [service for service in services if service["id"] != service_id]
    HEALTH_CACHE.pop(service_id, None)

    if not save_services(updated):
        return jsonify({"success": False, "message": "Unable to remove service."}), 500

    return jsonify({"success": True, "message": f"{target['name']} removed successfully."})



@app.route("/api/connectors", methods=["GET"])
def api_connectors():
    services = get_services()

    return jsonify({
        "connectors": [
            {
                "service_id": service["id"],
                "service_name": service["name"],
                "health_url": service["health_url"],
                **get_connector_status(service),
            }
            for service in services
        ]
    })


@app.route("/api/connectors/<service_id>/test", methods=["POST"])
def api_test_connector(service_id):
    service = get_service_by_id(service_id)

    if not service:
        return jsonify({
            "success": False,
            "message": "Service not found.",
        }), 404

    result = trigger_connector_test(service)

    return jsonify(result), (200 if result.get("success") else 400)



@app.route("/api/connectors/<service_id>/drill", methods=["POST"])
def api_run_recovery_drill(service_id):
    service = get_service_by_id(service_id)
    if not service:
        return jsonify({"success": False, "message": "Service not found."}), 404
    if is_local_service(service):
        return jsonify({"success": False, "message": "Use /crash for payment-api."}), 400

    connector = get_connector_status(service)
    if not connector.get("configured"):
        return jsonify({"success": False, "message": connector.get("message")}), 400

    incident_id = "DRILL-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    started_at = datetime.now().isoformat(timespec="seconds")
    before = check_service_health(service, force=True)

    hook = os.environ.get(connector["env_name"], "").strip()
    payload = {
        "source": "AegisOps",
        "action": "REDEPLOY_SERVICE",
        "mode": "RECOVERY_DRILL",
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "requested_at": started_at,
    }

    try:
        req = urllib.request.Request(
            hook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "AegisOps-Recovery-Drill/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            code = int(response.status)
            trigger_ok = 200 <= code < 300
    except Exception as error:
        code = None
        trigger_ok = False
        trigger_error = str(error)
    else:
        trigger_error = None

    if not trigger_ok:
        incident = {
            "id": incident_id,
            "service_id": service.get("id"),
            "service_name": service.get("name"),
            "detected_at": started_at,
            "status": "RECOVERY_FAILED",
            "drill": True,
            "health": before,
            "evidence": {"failure_type": "recovery_drill", "health_down": False, "http_status": before.get("http_status")},
            "analysis": {"incident": "RECOVERY_DRILL", "confidence": 1.0, "action": "REDEPLOY_SERVICE", "policy_action": "REDEPLOY_SERVICE"},
            "safety": {"approved": True, "action": "REDEPLOY_SERVICE", "reason": "User explicitly started a safe recovery drill."},
            "recovery": {"attempted": True, "success": False, "verified": False, "http_status": code, "reason": trigger_error or f"HTTP {code}"},
        }
        save_web_incident(incident)
        create_web_notification(
            f"{service.get('name')} recovery drill failed",
            incident["recovery"]["reason"],
            "ERROR",
            incident_id,
            service.get("name"),
        )
        return jsonify({"success": False, "message": incident["recovery"]["reason"], "incident": incident}), 502

    time.sleep(12)

    verified = False
    attempts = []
    final_health = None

    for attempt in range(1, 7):
        health = check_service_health(service, force=True)
        final_health = health
        attempts.append({
            "attempt": attempt,
            "status": health.get("status"),
            "http_status": health.get("http_status"),
            "error": health.get("error"),
            "checked_at": health.get("checked_at"),
        })
        if health.get("status") == "HEALTHY":
            verified = True
            break
        time.sleep(10)

    status = "RESOLVED" if verified else "RECOVERY_FAILED"
    incident = {
        "id": incident_id,
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "detected_at": started_at,
        "status": status,
        "drill": True,
        "health": before,
        "evidence": {"failure_type": "recovery_drill", "health_down": False, "http_status": before.get("http_status")},
        "analysis": {"incident": "RECOVERY_DRILL", "confidence": 1.0, "action": "REDEPLOY_SERVICE", "policy_action": "REDEPLOY_SERVICE"},
        "safety": {"approved": True, "action": "REDEPLOY_SERVICE", "reason": "User explicitly started a safe recovery drill."},
        "recovery": {
            "attempted": True,
            "success": verified,
            "verified": verified,
            "connector_type": connector.get("type"),
            "http_status": code,
            "verification_attempts": attempts,
            "final_health": final_health,
        },
    }
    save_web_incident(incident)

    create_web_notification(
        f"{service.get('name')} recovery drill {'completed' if verified else 'verification failed'}",
        "AegisOps triggered the configured recovery connector and verified the service healthy."
        if verified else
        "The connector accepted the request, but health verification did not pass.",
        "SUCCESS" if verified else "ERROR",
        incident_id,
        service.get("name"),
    )

    return jsonify({
        "success": verified,
        "message": "Recovery drill completed and service health was verified."
        if verified else
        "Recovery drill ran, but health verification did not pass.",
        "incident": incident,
    }), (200 if verified else 504)

@app.route("/api/incidents", methods=["GET"])
def api_incidents():
    incidents = get_incidents()
    resolved = sum(1 for incident in incidents if incident.get("status") == "RESOLVED")

    return jsonify({
        "incidents": incidents,
        "count": len(incidents),
        "resolved": resolved,
        "needs_attention": len(incidents) - resolved,
    })


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(get_settings())


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    incoming = request.get_json(silent=True) or {}
    settings = get_settings()

    if "monitoring_enabled" in incoming:
        settings["monitoring_enabled"] = bool(incoming["monitoring_enabled"])

    if "auto_recovery" in incoming:
        settings["auto_recovery"] = bool(incoming["auto_recovery"])

    if "monitor_interval" in incoming:
        try:
            settings["monitor_interval"] = max(1, min(int(incoming["monitor_interval"]), 60))
        except Exception:
            pass

    if "confidence_threshold" in incoming:
        try:
            settings["confidence_threshold"] = max(
                0.50,
                min(float(incoming["confidence_threshold"]), 0.99),
            )
        except Exception:
            pass

    success = write_json(SETTINGS_FILE, settings)

    return jsonify({"success": success, "settings": settings})


@app.route("/api/notifications", methods=["GET"])
def api_notifications():
    items = get_notifications(100)
    return jsonify({
        "notifications": items,
        "count": len(items),
        "unread": sum(1 for item in items if not item.get("read", False)),
    })


@app.route("/api/notifications/read-all", methods=["POST"])
def api_notifications_read_all():
    success = mark_all_notifications_read()
    return jsonify({"success": success, "unread": 0})


@app.route("/api/assistant", methods=["POST"])
def api_assistant():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message", "")).strip()

    if not message:
        return jsonify({"success": False, "answer": "Please enter a question."}), 400

    return jsonify({
        "success": True,
        "answer": generate_assistant_answer(message),
    })


@app.route("/api/status", methods=["GET"])
def api_status():
    primary = get_primary_service()
    return jsonify({
        "application": "AegisOps",
        "status": "ONLINE",
        "primary_service": primary["name"],
        "registered_services": len(get_services()),
        "unread_notifications": get_unread_notification_count(),
        "time": datetime.now().isoformat(timespec="seconds"),
    })


# ============================================================
# PAGE ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/services", methods=["GET"])
def services():
    return render_template("services.html")


@app.route("/incidents", methods=["GET"])
def incidents():
    return render_template("incidents.html")


@app.route("/assistant", methods=["GET"])
def assistant():
    return render_template("assistant.html")


@app.route("/notifications", methods=["GET"])
def notifications():
    return render_template("notifications.html")


@app.route("/connectors", methods=["GET"])
def connectors():
    return render_template("connectors.html")



@app.route("/infrastructure", methods=["GET"])
def infrastructure_page():
    return render_template("infrastructure.html")


@app.route("/settings", methods=["GET"])
def settings():
    return render_template("settings.html")


@app.errorhandler(404)
def page_not_found(error):
    return jsonify({"error": "Page not found", "application": "AegisOps"}), 404


if __name__ == "__main__":
    print()
    print("=" * 70)
    print("AEGISOPS WEB PLATFORM V7")
    print("=" * 70)
    print("Dashboard     : http://127.0.0.1:5000/")
    print("Services      : http://127.0.0.1:5000/services")
    print("Incidents     : http://127.0.0.1:5000/incidents")
    print("Aegis AI      : http://127.0.0.1:5000/assistant")
    print("Notifications : http://127.0.0.1:5000/notifications")
    print("Infrastructure: http://127.0.0.1:5000/infrastructure")
    print("Settings      : http://127.0.0.1:5000/settings")
    print("=" * 70)
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True,
    )
