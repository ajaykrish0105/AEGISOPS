import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime

try:
    from core import agent_client
except Exception:
    agent_client = None

SUPPORTED_ACTIONS = (
    "RESTART_SERVICE",
    "REDEPLOY_SERVICE",
    "ROLLBACK_DEPLOYMENT",
    "SCALE_SERVICE",
)


def _safe_id(service_id):
    value = str(service_id or "UNKNOWN").upper()
    return "".join(ch if ch.isalnum() else "_" for ch in value)


def _env_name(service_id, action):
    sid = _safe_id(service_id)
    prefixes = {
        "RESTART_SERVICE": "AEGISOPS_RESTART_",
        "REDEPLOY_SERVICE": "AEGISOPS_REDEPLOY_",
        "ROLLBACK_DEPLOYMENT": "AEGISOPS_ROLLBACK_",
        "SCALE_SERVICE": "AEGISOPS_SCALE_",
    }
    return prefixes[action] + sid


def _legacy_env_name(service_id):
    return "AEGISOPS_RECOVERY_" + _safe_id(service_id)


def get_connector_status(service):
    service_id = service.get("id")
    action_envs = {action: _env_name(service_id, action) for action in SUPPORTED_ACTIONS}
    capabilities = {}
    sources = {}

    for action, env_name in action_envs.items():
        hook = os.environ.get(env_name, "").strip()
        capabilities[action] = bool(hook)
        if hook:
            sources[action] = "WEBHOOK"

    legacy_name = _legacy_env_name(service_id)
    legacy_hook = os.environ.get(legacy_name, "").strip()
    if legacy_hook:
        capabilities["REDEPLOY_SERVICE"] = True
        sources["REDEPLOY_SERVICE"] = "WEBHOOK"

    agent_info = None
    if agent_client:
        try:
            agent_info = agent_client.get_service_capabilities(service_id)
        except Exception:
            agent_info = None

    if agent_info and agent_info.get("online"):
        for action, enabled in agent_info.get("capabilities", {}).items():
            if action in SUPPORTED_ACTIONS and enabled:
                capabilities[action] = True
                sources.setdefault(action, "AEGISOPS_AGENT")

    return {
        "configured": any(capabilities.values()),
        "connector_type": "HYBRID",
        "env_name": legacy_name,
        "legacy_env_name": legacy_name,
        "action_envs": action_envs,
        "capabilities": capabilities,
        "sources": sources,
        "agent": agent_info,
    }


def _hook_for_action(service, action):
    status = get_connector_status(service)
    env_name = status["action_envs"].get(action)

    if env_name:
        hook = os.environ.get(env_name, "").strip()
        if hook:
            return hook, env_name

    if action == "REDEPLOY_SERVICE":
        legacy_name = status["legacy_env_name"]
        legacy_hook = os.environ.get(legacy_name, "").strip()
        if legacy_hook:
            return legacy_hook, legacy_name

    return "", env_name


def trigger_remote_action(service, action, timeout=20):
    if action not in SUPPORTED_ACTIONS:
        return {
            "attempted": False,
            "success": False,
            "verified": False,
            "action": action,
            "reason": f"Unsupported recovery action: {action}",
        }

    status = get_connector_status(service)
    source = status.get("sources", {}).get(action)

    if source == "AEGISOPS_AGENT" and agent_client:
        result = agent_client.execute_action(
            service.get("id"),
            action,
        )
        result.setdefault("action", action)
        return result

    hook, env_name = _hook_for_action(service, action)

    if not hook:
        return {
            "attempted": False,
            "success": False,
            "verified": False,
            "connector_required": True,
            "action": action,
            "env_name": env_name,
            "reason": f"No authorized connector is configured for {action}.",
            "triggered_at": None,
        }

    payload = {
        "source": "AegisOps",
        "action": action,
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "requested_at": datetime.now().isoformat(timespec="seconds"),
    }

    try:
        request = urllib.request.Request(
            hook,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AegisOps-Recovery/2.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = int(response.status)
            ok = 200 <= code < 300
            return {
                "attempted": True,
                "success": ok,
                "verified": False,
                "connector_required": False,
                "connector_type": "GENERIC_ACTION_WEBHOOK",
                "action": action,
                "http_status": code,
                "reason": "Recovery action accepted." if ok else f"Connector returned HTTP {code}.",
                "triggered_at": datetime.now().isoformat(timespec="seconds"),
            }

    except urllib.error.HTTPError as error:
        return {
            "attempted": True,
            "success": False,
            "verified": False,
            "connector_required": False,
            "connector_type": "GENERIC_ACTION_WEBHOOK",
            "action": action,
            "http_status": error.code,
            "reason": f"Connector failed: HTTP {error.code} {error.reason}",
            "triggered_at": datetime.now().isoformat(timespec="seconds"),
        }

    except Exception as error:
        return {
            "attempted": True,
            "success": False,
            "verified": False,
            "connector_required": False,
            "connector_type": "GENERIC_ACTION_WEBHOOK",
            "action": action,
            "http_status": None,
            "reason": f"Connector error: {error}",
            "triggered_at": datetime.now().isoformat(timespec="seconds"),
        }


def trigger_remote_recovery(service, timeout=20):
    # Backward-compatible wrapper used by older code.
    return trigger_remote_action(service, "REDEPLOY_SERVICE", timeout=timeout)


def verify_remote_service(service, health_check_function, wait_seconds=180, interval_seconds=10):
    started = time.time()
    attempts = 0
    last_health = None

    while time.time() - started < wait_seconds:
        attempts += 1
        try:
            last_health = health_check_function(service)
        except Exception as error:
            last_health = {"healthy": False, "error": str(error)}

        if last_health.get("healthy"):
            return {
                "verified": True,
                "verification_attempts": attempts,
                "verified_at": datetime.now().isoformat(timespec="seconds"),
                "final_health": last_health,
            }

        time.sleep(interval_seconds)

    return {
        "verified": False,
        "verification_attempts": attempts,
        "verified_at": None,
        "final_health": last_health,
    }
