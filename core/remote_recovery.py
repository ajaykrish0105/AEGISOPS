
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime

try:
    from core import agent_client
except ImportError:
    agent_client = None


# ============================================================
# AEGISOPS 2.0 - REMOTE RECOVERY ENGINE
# ============================================================

SUPPORTED_ACTIONS = (
    "RESTART_SERVICE",
    "REDEPLOY_SERVICE",
    "ROLLBACK_DEPLOYMENT",
    "SCALE_SERVICE",
)


def _safe_id(service_id):
    value = str(service_id or "UNKNOWN").upper()
    return "".join(
        ch if ch.isalnum() else "_"
        for ch in value
    )


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


# ============================================================
# CONNECTOR STATUS
# ============================================================

def get_connector_status(service):
    service_id = service.get("id")

    action_envs = {
        action: _env_name(service_id, action)
        for action in SUPPORTED_ACTIONS
    }

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
            agent_info = agent_client.get_service_capabilities(
                service_id
            )
        except Exception:
            agent_info = None

    if agent_info and agent_info.get("online"):
        for action, enabled in agent_info.get(
            "capabilities", {}
        ).items():

            if action in SUPPORTED_ACTIONS and enabled:
                capabilities[action] = True
                sources.setdefault(
                    action,
                    "AEGISOPS_AGENT"
                )

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


# ============================================================
# WEBHOOK LOOKUP
# ============================================================

def _hook_for_action(service, action):
    status = get_connector_status(service)
    env_name = status["action_envs"].get(action)

    if env_name:
        hook = os.environ.get(env_name, "").strip()

        if hook:
            return hook, env_name

    if action == "REDEPLOY_SERVICE":
        legacy_name = status["legacy_env_name"]
        legacy_hook = os.environ.get(
            legacy_name, ""
        ).strip()

        if legacy_hook:
            return legacy_hook, legacy_name

    return "", env_name


# ============================================================
# EXECUTE REMOTE RECOVERY
# ============================================================

def trigger_remote_action(service, action, timeout=20):

    if action not in SUPPORTED_ACTIONS:
        return {
            "attempted": False,
            "success": False,
            "verified": False,
            "action": action,
            "reason": (
                f"Unsupported recovery action: {action}"
            ),
        }

    status = get_connector_status(service)
    source = status.get("sources", {}).get(action)

    # Execute using AegisOps Agent
    if source == "AEGISOPS_AGENT" and agent_client:
        try:
            result = agent_client.execute_action(
                service.get("id"),
                action,
            )

            if not isinstance(result, dict):
                raise ValueError(
                    "Agent returned an invalid response."
                )

            result.setdefault("action", action)
            result.setdefault("verified", False)

            return result

        except Exception as error:
            return {
                "attempted": True,
                "success": False,
                "verified": False,
                "action": action,
                "connector_type": "AEGISOPS_AGENT",
                "reason": f"Agent execution failed: {error}",
                "triggered_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
            }

    hook, env_name = _hook_for_action(
        service,
        action
    )

    if not hook:
        return {
            "attempted": False,
            "success": False,
            "verified": False,
            "connector_required": True,
            "action": action,
            "env_name": env_name,
            "reason": (
                f"No authorized connector is configured "
                f"for {action}."
            ),
            "triggered_at": None,
        }

    payload = {
        "source": "AegisOps",
        "action": action,
        "service_id": service.get("id"),
        "service_name": service.get("name"),
        "requested_at": datetime.now().isoformat(
            timespec="seconds"
        ),
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

        with urllib.request.urlopen(
            request,
            timeout=timeout
        ) as response:

            code = int(response.status)
            accepted = 200 <= code < 300

            return {
                "attempted": True,
                "success": accepted,
                "verified": False,
                "connector_required": False,
                "connector_type": "GENERIC_ACTION_WEBHOOK",
                "action": action,
                "http_status": code,
                "reason": (
                    "Recovery action accepted."
                    if accepted
                    else f"Connector returned HTTP {code}."
                ),
                "triggered_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
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
            "reason": (
                f"Connector failed: "
                f"HTTP {error.code} {error.reason}"
            ),
            "triggered_at": datetime.now().isoformat(
                timespec="seconds"
            ),
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
            "triggered_at": datetime.now().isoformat(
                timespec="seconds"
            ),
        }


# ============================================================
# BACKWARD COMPATIBILITY
# ============================================================

def trigger_remote_recovery(service, timeout=20):
    return trigger_remote_action(
        service,
        "REDEPLOY_SERVICE",
        timeout=timeout
    )


# ============================================================
# AEGISOPS 2.0 - RECOVERY VERIFICATION ENGINE
# ============================================================

def verify_remote_service(
    service,
    health_check_function,
    wait_seconds=180,
    interval_seconds=10,
    required_successes=3,
):
    """
    Verify that a recovered service remains healthy.

    A single successful HTTP response is not enough.

    Requirements:
        - Three consecutive successful health checks
        - Reset the counter after any failure
        - Stop when the verification timeout expires
        - Return a structured verification result
    """

    started = time.monotonic()

    attempts = 0
    consecutive_successes = 0
    last_health = None

    required_successes = max(
        1,
        int(required_successes)
    )

    wait_seconds = max(
        0.0,
        float(wait_seconds)
    )

    interval_seconds = max(
        0.01,
        float(interval_seconds)
    )

    service_name = service.get(
        "name",
        service.get("id", "UNKNOWN")
    )

    print(
        f"[AEGISOPS VERIFY] Starting verification "
        f"for {service_name}"
    )

    while time.monotonic() - started < wait_seconds:

        attempts += 1

        try:
            last_health = health_check_function(
                service
            )

            if not isinstance(last_health, dict):
                last_health = {
                    "healthy": False,
                    "error": (
                        "Invalid health check response"
                    ),
                }

        except Exception as error:
            last_health = {
                "healthy": False,
                "error": str(error),
            }

        if last_health.get("healthy") is True:
            consecutive_successes += 1
            status = "HEALTHY"

        else:
            consecutive_successes = 0
            status = "UNHEALTHY"

        print(
            f"[AEGISOPS VERIFY] "
            f"Service={service_name} | "
            f"Attempt={attempts} | "
            f"Status={status} | "
            f"Stable={consecutive_successes}/"
            f"{required_successes}"
        )

        if consecutive_successes >= required_successes:

            verified_at = datetime.now().isoformat(
                timespec="seconds"
            )

            print(
                f"[AEGISOPS VERIFY] "
                f"RECOVERY VERIFIED: {service_name}"
            )

            return {
                "verified": True,
                "verification_attempts": attempts,
                "consecutive_successes": consecutive_successes,
                "required_successes": required_successes,
                "verified_at": verified_at,
                "final_health": last_health,
                "reason": (
                    "Service passed consecutive "
                    "health checks."
                ),
            }

        remaining = wait_seconds - (
            time.monotonic() - started
        )

        if remaining > 0:
            time.sleep(
                min(interval_seconds, remaining)
            )

    print(
        f"[AEGISOPS VERIFY] "
        f"RECOVERY NOT VERIFIED: {service_name}"
    )

    return {
        "verified": False,
        "verification_attempts": attempts,
        "consecutive_successes": consecutive_successes,
        "required_successes": required_successes,
        "verified_at": None,
        "final_health": last_health,
        "reason": (
            "Recovery verification timed out."
        ),
    }
