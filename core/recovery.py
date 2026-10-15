import os
import sys
import time
import subprocess
import urllib.request


# ============================================================
# AEGISOPS RECOVERY ENGINE V1
# ============================================================

ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

SERVICE_SCRIPT = os.path.join(
    ROOT,
    "demo",
    "service.py"
)

HEALTH_URL = "http://127.0.0.1:8000/health"

RECOVERY_LOG = os.path.join(
    ROOT,
    "data",
    "recovery.log"
)


# ============================================================
# HEALTH CHECK
# ============================================================

def check_health():

    try:

        request = urllib.request.Request(
            HEALTH_URL,
            headers={
                "User-Agent": "AegisOps-Recovery/1.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=1
        ) as response:

            return response.status == 200

    except Exception:

        return False


# ============================================================
# START SERVICE PROCESS
# ============================================================

def start_service():

    os.makedirs(
        os.path.dirname(RECOVERY_LOG),
        exist_ok=True
    )

    log_file = open(
        RECOVERY_LOG,
        "a",
        encoding="utf-8"
    )

    creation_flags = 0

    if os.name == "nt":

        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
        )

    process = subprocess.Popen(
        [
            sys.executable,
            SERVICE_SCRIPT
        ],
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags
    )

    return process


# ============================================================
# VERIFY RECOVERY
# ============================================================

def verify_recovery(
    attempts=10,
    delay=1
):

    print()
    print(
        "[VERIFY] Waiting for service "
        "health..."
    )

    for attempt in range(
        1,
        attempts + 1
    ):

        if check_health():

            print(
                f"[VERIFY] Attempt "
                f"{attempt}/{attempts}: "
                f"HTTP 200"
            )

            return True

        print(
            f"[VERIFY] Attempt "
            f"{attempt}/{attempts}: "
            f"service not ready"
        )

        time.sleep(delay)

    return False


# ============================================================
# RECOVERY EXECUTION
# ============================================================

def execute_recovery(decision):

    print()
    print("=" * 64)
    print(
        "              AEGISOPS RECOVERY ENGINE"
    )
    print("=" * 64)

    approved = decision.get(
        "approved",
        False
    )

    action = decision.get(
        "action",
        "HUMAN_REVIEW"
    )

    print(
        f"Safety Approval : {approved}"
    )

    print(
        f"Recovery Action : {action}"
    )

    # --------------------------------------------------------
    # SAFETY MUST APPROVE FIRST
    # --------------------------------------------------------

    if not approved:

        print()
        print(
            "[BLOCKED] Recovery cannot run "
            "without Safety Engine approval."
        )

        return {
            "success": False,
            "verified": False,
            "action": action,
            "reason": "SAFETY_NOT_APPROVED"
        }

    # --------------------------------------------------------
    # ONLY RESTART IS IMPLEMENTED CURRENTLY
    # --------------------------------------------------------

    if action not in {
        "RESTART_SERVICE",
        "CONTROLLED_RESTART"
    }:

        print()
        print(
            "[BLOCKED] Recovery action is "
            "not implemented."
        )

        return {
            "success": False,
            "verified": False,
            "action": action,
            "reason": "ACTION_NOT_IMPLEMENTED"
        }

    # --------------------------------------------------------
    # DON'T START DUPLICATE SERVICE
    # --------------------------------------------------------

    if check_health():

        print()
        print(
            "[INFO] Service is already healthy."
        )

        return {
            "success": True,
            "verified": True,
            "action": action,
            "reason": "ALREADY_HEALTHY"
        }

    # --------------------------------------------------------
    # START SERVICE
    # --------------------------------------------------------

    print()
    print(
        "[RECOVERY] Starting payment-api..."
    )

    try:

        process = start_service()

        print(
            f"[RECOVERY] New process PID: "
            f"{process.pid}"
        )

    except Exception as error:

        print(
            f"[ERROR] Failed to start service: "
            f"{error}"
        )

        return {
            "success": False,
            "verified": False,
            "action": action,
            "reason": "START_FAILED"
        }

    # --------------------------------------------------------
    # VERIFY
    # --------------------------------------------------------

    verified = verify_recovery()

    if verified:

        print()
        print(
            "[RECOVERED] payment-api is ONLINE."
        )

        print(
            "[VERIFIED] /health returned HTTP 200."
        )

        print("=" * 64)

        return {
            "success": True,
            "verified": True,
            "action": action,
            "pid": process.pid,
            "reason": "RECOVERY_VERIFIED"
        }

    print()
    print(
        "[FAILED] Service recovery could "
        "not be verified."
    )

    print("=" * 64)

    return {
        "success": False,
        "verified": False,
        "action": action,
        "pid": process.pid,
        "reason": "HEALTH_CHECK_FAILED"
    }


# ============================================================
# DIRECT TEST
# ============================================================

if __name__ == "__main__":

    test_decision = {
        "approved": True,
        "action": "RESTART_SERVICE",
        "reason": "SAFETY_CHECK_PASSED"
    }

    result = execute_recovery(
        test_decision
    )

    print()
    print(result)