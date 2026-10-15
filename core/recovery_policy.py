def _capabilities(connector_status):
    caps = connector_status.get("capabilities", {}) if isinstance(connector_status, dict) else {}
    return {str(k): bool(v) for k, v in caps.items()}


def build_remote_recovery_plan(service, evidence, connector_status):
    """Return an ordered, pre-authorized automatic recovery runbook.

    AegisOps can only execute actions for which the target organization has
    configured an authorized connector. Unknown or security-sensitive failures
    are escalated instead of guessed.
    """
    caps = _capabilities(connector_status)
    status = evidence.get("http_status")
    timeout = bool(evidence.get("timeout"))
    refused = bool(evidence.get("connection_refused"))
    recent_deployment = bool(evidence.get("recent_deployment"))

    actions = []
    diagnosis = "REMOTE_HEALTH_FAILURE"
    reason = "Confirmed remote health-check failure."

    if status in (401, 403):
        return {
            "diagnosis": "AUTHORIZATION_FAILURE",
            "actions": [],
            "reason": "Authentication/authorization failures are not auto-mutated.",
            "requires_human": True,
        }

    if status == 404:
        return {
            "diagnosis": "ENDPOINT_OR_ROUTE_FAILURE",
            "actions": [],
            "reason": "A missing route may indicate configuration or deployment drift.",
            "requires_human": True,
        }

    if status == 429 and caps.get("SCALE_SERVICE"):
        actions.append("SCALE_SERVICE")
        diagnosis = "CAPACITY_PRESSURE"
        reason = "Remote service returned HTTP 429 and an authorized scale connector is available."

    if recent_deployment and caps.get("ROLLBACK_DEPLOYMENT"):
        actions.append("ROLLBACK_DEPLOYMENT")
        diagnosis = "PROBABLE_BAD_DEPLOYMENT"
        reason = "Health failure followed a recent deployment and rollback is pre-authorized."

    if timeout or refused or status in (500, 502, 503, 504) or status is None:
        if caps.get("RESTART_SERVICE"):
            actions.append("RESTART_SERVICE")
        if caps.get("REDEPLOY_SERVICE"):
            actions.append("REDEPLOY_SERVICE")

    if not actions and caps.get("REDEPLOY_SERVICE"):
        actions.append("REDEPLOY_SERVICE")

    # De-duplicate while preserving order.
    actions = list(dict.fromkeys(actions))

    return {
        "diagnosis": diagnosis,
        "actions": actions,
        "reason": reason,
        "requires_human": not bool(actions),
    }
