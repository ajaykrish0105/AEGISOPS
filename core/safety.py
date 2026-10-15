# ============================================================
# AEGISOPS SAFETY ENGINE V1
# ============================================================

MIN_CONFIDENCE = 0.70

ALLOWED_ACTIONS = {
    "RESTART_SERVICE",
    "CONTROLLED_RESTART"
}

BLOCKED_ACTIONS = {
    "ROLLBACK_DEPLOYMENT",
    "INVESTIGATE_OR_SCALE",
    "HUMAN_REVIEW"
}


def evaluate_action(analysis):

    incident = analysis.get(
        "incident",
        "UNKNOWN"
    )

    confidence = float(
        analysis.get(
            "confidence",
            0.0
        )
    )

    action = analysis.get(
        "action",
        "HUMAN_REVIEW"
    )

    print()
    print("=" * 64)
    print("              AEGISOPS SAFETY ENGINE")
    print("=" * 64)

    print(
        f"Incident         : {incident}"
    )

    print(
        f"AI Confidence    : "
        f"{confidence * 100:.2f}%"
    )

    print(
        f"Proposed Action  : {action}"
    )

    # --------------------------------------------------------
    # CONFIDENCE CHECK
    # --------------------------------------------------------

    if confidence < MIN_CONFIDENCE:

        print()
        print(
            "[BLOCKED] AI confidence below "
            "safety threshold."
        )

        print(
            "[ACTION] Human review required."
        )

        return {
            "approved": False,
            "action": "HUMAN_REVIEW",
            "reason": "LOW_CONFIDENCE"
        }

    # --------------------------------------------------------
    # ACTION ALLOWLIST CHECK
    # --------------------------------------------------------

    if action not in ALLOWED_ACTIONS:

        print()
        print(
            "[BLOCKED] Proposed action is not "
            "approved for autonomous execution."
        )

        print(
            "[ACTION] Human review required."
        )

        return {
            "approved": False,
            "action": "HUMAN_REVIEW",
            "reason": "ACTION_NOT_ALLOWED"
        }

    # --------------------------------------------------------
    # APPROVED
    # --------------------------------------------------------

    print()
    print(
        "[APPROVED] Safety validation passed."
    )

    print(
        f"[APPROVED] {action} may be executed."
    )

    print("=" * 64)

    return {
        "approved": True,
        "action": action,
        "reason": "SAFETY_CHECK_PASSED"
    }