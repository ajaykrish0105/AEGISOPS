import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
AUDIT_FILE = os.path.join(DATA_DIR, "audit.jsonl")


def append_audit(event_type, actor="aegisops", service_id=None, agent_id=None, details=None):
    os.makedirs(DATA_DIR, exist_ok=True)

    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event_type": str(event_type),
        "actor": str(actor),
        "service_id": service_id,
        "agent_id": agent_id,
        "details": details or {},
    }

    with open(AUDIT_FILE, "a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event
