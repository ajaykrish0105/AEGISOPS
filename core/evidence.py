import json
import os
import platform
import socket
from datetime import datetime

import psutil


# ============================================================
# AEGISOPS - EVIDENCE COLLECTOR V2
# ============================================================

ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATA_DIR = os.path.join(ROOT, "data")

EVIDENCE_FILE = os.path.join(
    DATA_DIR,
    "latest_evidence.json"
)

SERVICE_STATE_FILE = os.path.join(
    DATA_DIR,
    "service_state.json"
)

SERVICE_LOG_FILE = os.path.join(
    DATA_DIR,
    "service.log"
)


# ============================================================
# READ JSON SAFELY
# ============================================================

def read_json_file(path):

    if not os.path.exists(path):
        return {}

    try:
        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except Exception:
        return {}


# ============================================================
# READ RECENT SERVICE LOGS
# ============================================================

def read_recent_logs(path, count=10):

    if not os.path.exists(path):
        return []

    try:
        with open(
            path,
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as file:

            lines = file.readlines()

        return [
            line.strip()
            for line in lines[-count:]
            if line.strip()
        ]

    except Exception:
        return []


# ============================================================
# SYSTEM METRICS
# ============================================================

def get_system_metrics():

    try:
        cpu_percent = psutil.cpu_percent(
            interval=0.4
        )
    except Exception:
        cpu_percent = 0.0

    try:
        memory_percent = (
            psutil.virtual_memory().percent
        )
    except Exception:
        memory_percent = 0.0

    return (
        round(cpu_percent, 2),
        round(memory_percent, 2)
    )


# ============================================================
# EVIDENCE COLLECTOR
# ============================================================

def collect_evidence(
    service_name,
    health_status,
    health_error="none",
    failure_type="unknown"
):

    os.makedirs(
        DATA_DIR,
        exist_ok=True
    )

    # --------------------------------------------------------
    # COLLECT REAL COMPUTER METRICS
    # --------------------------------------------------------

    cpu_percent, memory_percent = (
        get_system_metrics()
    )

    # --------------------------------------------------------
    # READ SERVICE STATE
    # --------------------------------------------------------

    service_state = read_json_file(
        SERVICE_STATE_FILE
    )

    # --------------------------------------------------------
    # READ SERVICE LOG
    # --------------------------------------------------------

    recent_logs = read_recent_logs(
        SERVICE_LOG_FILE
    )

    # --------------------------------------------------------
    # SERVICE FAILURE INFORMATION
    # --------------------------------------------------------

    stored_failure_type = (
        service_state.get(
            "failure_type",
            failure_type
        )
    )

    process_crashed = bool(
        service_state.get(
            "process_crashed",
            False
        )
    )

    recent_deployment = bool(
        service_state.get(
            "recent_deployment",
            False
        )
    )

    error_500 = bool(
        service_state.get(
            "error_500",
            False
        )
    )

    # --------------------------------------------------------
    # RESOURCE THRESHOLDS
    # --------------------------------------------------------

    cpu_high = (
        cpu_percent >= 85.0
    )

    memory_high = (
        memory_percent >= 85.0
    )

    # --------------------------------------------------------
    # COMPLETE EVIDENCE
    # --------------------------------------------------------

    evidence = {

        "timestamp":
            datetime.now().isoformat(
                timespec="seconds"
            ),

        "service":
            service_name,

        "health_status":
            health_status,

        "health_error":
            str(health_error),

        "failure_type":
            str(stored_failure_type),

        "process_crashed":
            process_crashed,

        "cpu_percent":
            cpu_percent,

        "cpu_high":
            cpu_high,

        "memory_percent":
            memory_percent,

        "memory_high":
            memory_high,

        "recent_deployment":
            recent_deployment,

        "error_500":
            error_500,

        "recent_logs":
            recent_logs,

        "service_state":
            service_state,

        "operating_system":
            platform.system(),

        "machine":
            platform.machine(),

        "hostname":
            socket.gethostname(),

        "python_version":
            platform.python_version()
    }

    # --------------------------------------------------------
    # SAVE EVIDENCE
    # --------------------------------------------------------

    with open(
        EVIDENCE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            evidence,
            file,
            indent=4
        )

    # --------------------------------------------------------
    # DISPLAY
    # --------------------------------------------------------

    print()
    print("=" * 64)
    print(
        "          AEGISOPS EVIDENCE COLLECTOR V2"
    )
    print("=" * 64)

    print(
        f"Timestamp       : {evidence['timestamp']}"
    )

    print(
        f"Service         : {evidence['service']}"
    )

    print(
        f"Health Status   : {evidence['health_status']}"
    )

    print(
        f"Health Error    : {evidence['health_error']}"
    )

    print(
        f"Failure Type    : {evidence['failure_type']}"
    )

    print(
        f"Process Crashed : {evidence['process_crashed']}"
    )

    print(
        f"CPU Usage       : {evidence['cpu_percent']}%"
    )

    print(
        f"CPU High        : {evidence['cpu_high']}"
    )

    print(
        f"Memory Usage    : {evidence['memory_percent']}%"
    )

    print(
        f"Memory High     : {evidence['memory_high']}"
    )

    print(
        f"Recent Deploy   : {evidence['recent_deployment']}"
    )

    print(
        f"HTTP 500        : {evidence['error_500']}"
    )

    print(
        f"Operating Sys   : {evidence['operating_system']}"
    )

    print(
        f"Machine         : {evidence['machine']}"
    )

    print(
        f"Hostname        : {evidence['hostname']}"
    )

    print(
        f"Python          : {evidence['python_version']}"
    )

    print()

    if recent_logs:

        print("Recent Application Logs:")

        for log in recent_logs:
            print(f"  > {log}")

    else:

        print(
            "Recent Application Logs: "
            "No logs available"
        )

    print("=" * 64)

    print(
        "[AEGIS] Evidence successfully stored."
    )

    return evidence


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    collect_evidence(
        service_name="payment-api",
        health_status="DOWN",
        health_error="connection refused",
        failure_type="unknown"
    )