from flask import Flask, jsonify, request
import json
import os
import platform
import subprocess
import time
import urllib.request
from datetime import datetime

import psutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POLICY_FILE = os.environ.get(
    "AEGISOPS_AGENT_POLICY",
    os.path.join(BASE_DIR, "policy.json"),
)
AUDIT_FILE = os.environ.get(
    "AEGISOPS_AGENT_AUDIT",
    os.path.join(BASE_DIR, "agent_audit.jsonl"),
)

AGENT_ID = os.environ.get("AEGISOPS_AGENT_ID", "AGENT-001")
AGENT_NAME = os.environ.get("AEGISOPS_AGENT_NAME", platform.node() or AGENT_ID)
AGENT_TOKEN = os.environ.get("AEGISOPS_AGENT_TOKEN", "").strip()
AGENT_HOST = os.environ.get("AEGISOPS_AGENT_HOST", "127.0.0.1")
AGENT_PORT = int(os.environ.get("AEGISOPS_AGENT_PORT", "9100"))

app = Flask(__name__)


def read_policy():
    try:
        with open(POLICY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_audit(event_type, service=None, action=None, result=None, details=None):
    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "agent_id": AGENT_ID,
        "event_type": event_type,
        "service": service,
        "action": action,
        "result": result,
        "details": details or {},
    }
    with open(AUDIT_FILE, "a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")


def authorized():
    if not AGENT_TOKEN:
        return False
    header = request.headers.get("Authorization", "")
    return header == f"Bearer {AGENT_TOKEN}"


@app.before_request
def require_auth():
    if not authorized():
        return jsonify({
            "success": False,
            "message": "Unauthorized AegisOps Agent request.",
        }), 401


def service_config(service_name):
    policy = read_policy()
    services = policy.get("services", {})
    service = services.get(service_name)
    return service if isinstance(service, dict) else None


def health_check(url, timeout=4):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AegisOps-Agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            code = int(response.status)
            return {
                "healthy": 200 <= code < 400,
                "http_status": code,
                "error": None,
            }
    except Exception as error:
        return {
            "healthy": False,
            "http_status": None,
            "error": str(error),
        }


def safe_tail(path, lines=80):
    if not path or not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            return file.readlines()[-lines:]
    except Exception:
        return []


@app.route("/v1/health", methods=["GET"])
def agent_health():
    return jsonify({
        "success": True,
        "agent_id": AGENT_ID,
        "name": AGENT_NAME,
        "hostname": platform.node(),
        "platform": platform.platform(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })


@app.route("/v1/services", methods=["GET"])
def list_services():
    policy = read_policy()
    services = []

    for name, cfg in policy.get("services", {}).items():
        actions = cfg.get("actions", {})
        services.append({
            "name": name,
            "health_url": cfg.get("health_url"),
            "capabilities": {
                action: bool(command)
                for action, command in actions.items()
            },
        })

    return jsonify({"services": services})


@app.route("/v1/services/<service_name>", methods=["GET"])
def get_service(service_name):
    cfg = service_config(service_name)
    if not cfg:
        return jsonify({"message": "Unknown agent service."}), 404

    actions = cfg.get("actions", {})
    return jsonify({
        "name": service_name,
        "health_url": cfg.get("health_url"),
        "capabilities": {
            action: bool(command)
            for action, command in actions.items()
        },
    })


@app.route("/v1/services/<service_name>/evidence", methods=["GET"])
def evidence(service_name):
    cfg = service_config(service_name)
    if not cfg:
        return jsonify({"message": "Unknown agent service."}), 404

    health = health_check(cfg.get("health_url")) if cfg.get("health_url") else {}
    log_lines = safe_tail(cfg.get("log_file"))

    payload = {
        "service": service_name,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "host": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage(os.path.abspath(os.sep)).percent,
        },
        "health": health,
        "recent_logs": [line.rstrip("\n") for line in log_lines],
        "metadata": cfg.get("metadata", {}),
    }

    write_audit("EVIDENCE_COLLECTED", service=service_name)
    return jsonify(payload)


@app.route("/v1/services/<service_name>/actions/<action>", methods=["POST"])
def execute_action(service_name, action):
    cfg = service_config(service_name)
    if not cfg:
        return jsonify({"success": False, "message": "Unknown agent service."}), 404

    actions = cfg.get("actions", {})
    command = actions.get(action)

    if not isinstance(command, list) or not command:
        return jsonify({
            "success": False,
            "message": f"Action {action} is not pre-authorized for this service.",
        }), 403

    # Security design:
    # - exact argv list comes only from local policy.json
    # - request cannot supply shell commands
    # - shell=False
    # - fixed timeout
    started = time.time()

    write_audit(
        "ACTION_STARTED",
        service=service_name,
        action=action,
        details={"incident_id": (request.get_json(silent=True) or {}).get("incident_id")},
    )

    try:
        completed = subprocess.run(
            [str(part) for part in command],
            shell=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

        success = completed.returncode == 0
        result = {
            "success": success,
            "message": (
                f"{action} completed successfully."
                if success else
                f"{action} failed with exit code {completed.returncode}."
            ),
            "return_code": completed.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": (completed.stdout or "")[-4000:],
            "stderr": (completed.stderr or "")[-4000:],
        }

        write_audit(
            "ACTION_FINISHED",
            service=service_name,
            action=action,
            result="SUCCESS" if success else "FAILED",
            details={
                "return_code": completed.returncode,
                "duration_seconds": result["duration_seconds"],
            },
        )

        return jsonify(result), (200 if success else 500)

    except subprocess.TimeoutExpired:
        write_audit(
            "ACTION_FINISHED",
            service=service_name,
            action=action,
            result="TIMEOUT",
        )
        return jsonify({
            "success": False,
            "message": f"{action} exceeded the 60 second agent timeout.",
        }), 504

    except Exception as error:
        write_audit(
            "ACTION_FINISHED",
            service=service_name,
            action=action,
            result="ERROR",
            details={"error": str(error)},
        )
        return jsonify({
            "success": False,
            "message": str(error),
        }), 500


if __name__ == "__main__":
    if not AGENT_TOKEN:
        raise SystemExit(
            "AEGISOPS_AGENT_TOKEN is required before starting the agent."
        )

    print("=" * 68)
    print("AEGISOPS AGENT")
    print("=" * 68)
    print("Agent ID :", AGENT_ID)
    print("Name     :", AGENT_NAME)
    print("Listen   :", f"http://{AGENT_HOST}:{AGENT_PORT}")
    print("Policy   :", POLICY_FILE)
    print("=" * 68)

    app.run(
        host=AGENT_HOST,
        port=AGENT_PORT,
        debug=False,
        threaded=True,
    )
