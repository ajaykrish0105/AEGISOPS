import json
import os
import urllib.request
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
AGENTS_FILE = os.path.join(DATA_DIR, "agents.json")


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def _safe_id(value):
    value = str(value or "").upper()
    return "".join(ch if ch.isalnum() else "_" for ch in value)


def token_env_name(agent_id):
    return "AEGISOPS_AGENT_TOKEN_" + _safe_id(agent_id)


def get_agents():
    data = _read_json(AGENTS_FILE, [])
    return data if isinstance(data, list) else []


def get_agent(agent_id):
    for agent in get_agents():
        if str(agent.get("id")) == str(agent_id):
            return agent
    return None


def find_binding(service_id):
    for agent in get_agents():
        if not agent.get("enabled", True):
            continue
        for binding in agent.get("bindings", []):
            if str(binding.get("service_id")) == str(service_id):
                return {
                    "agent": agent,
                    "agent_service": binding.get("agent_service"),
                }
    return None


def _request(agent, path, method="GET", payload=None, timeout=8):
    base_url = str(agent.get("base_url", "")).rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError("Agent URL must use http:// or https://")

    env_name = token_env_name(agent.get("id"))
    token = os.environ.get(env_name, "").strip()
    if not token:
        raise RuntimeError(f"Missing agent token environment variable: {env_name}")

    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "AegisOps-Control-Plane/1.0",
    }

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        base_url + path,
        data=data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        body = json.loads(raw) if raw else {}
        return {
            "http_status": int(response.status),
            "body": body,
        }


def get_agent_snapshot(agent):
    try:
        health = _request(agent, "/v1/health")
        services = _request(agent, "/v1/services")
        return {
            "online": True,
            "health": health["body"],
            "services": services["body"].get("services", []),
            "token_env": token_env_name(agent.get("id")),
            "error": None,
        }
    except Exception as error:
        return {
            "online": False,
            "health": None,
            "services": [],
            "token_env": token_env_name(agent.get("id")),
            "error": str(error),
        }


def get_service_capabilities(service_id):
    binding = find_binding(service_id)
    if not binding:
        return None

    agent = binding["agent"]
    agent_service = binding["agent_service"]

    try:
        result = _request(agent, f"/v1/services/{agent_service}")
        body = result["body"]
        return {
            "agent_id": agent.get("id"),
            "agent_service": agent_service,
            "capabilities": body.get("capabilities", {}),
            "online": True,
        }
    except Exception as error:
        return {
            "agent_id": agent.get("id"),
            "agent_service": agent_service,
            "capabilities": {},
            "online": False,
            "error": str(error),
        }


def collect_evidence(service_id):
    binding = find_binding(service_id)
    if not binding:
        return {"success": False, "reason": "No AegisOps Agent binding exists."}

    agent = binding["agent"]
    agent_service = binding["agent_service"]

    try:
        result = _request(agent, f"/v1/services/{agent_service}/evidence", timeout=12)
        return {
            "success": True,
            "agent_id": agent.get("id"),
            "agent_service": agent_service,
            "evidence": result["body"],
        }
    except Exception as error:
        return {"success": False, "reason": str(error)}


def execute_action(service_id, action, incident_id=None):
    binding = find_binding(service_id)
    if not binding:
        return {
            "attempted": False,
            "success": False,
            "reason": "No AegisOps Agent binding exists.",
        }

    agent = binding["agent"]
    agent_service = binding["agent_service"]

    payload = {
        "incident_id": incident_id,
        "requested_by": "AegisOps",
    }

    try:
        result = _request(
            agent,
            f"/v1/services/{agent_service}/actions/{action}",
            method="POST",
            payload=payload,
            timeout=75,
        )
        body = result["body"]
        return {
            "attempted": True,
            "success": bool(body.get("success")),
            "verified": False,
            "connector_type": "AEGISOPS_AGENT",
            "agent_id": agent.get("id"),
            "agent_service": agent_service,
            "action": action,
            "reason": body.get("message"),
            "details": body,
        }
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8", errors="replace"))
        except Exception:
            body = {}
        return {
            "attempted": True,
            "success": False,
            "verified": False,
            "connector_type": "AEGISOPS_AGENT",
            "action": action,
            "reason": body.get("message") or f"Agent returned HTTP {error.code}.",
        }
    except Exception as error:
        return {
            "attempted": True,
            "success": False,
            "verified": False,
            "connector_type": "AEGISOPS_AGENT",
            "action": action,
            "reason": str(error),
        }
