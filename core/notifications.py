import json
import os
import urllib.request
from datetime import datetime

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(CORE_DIR)
DATA_DIR = os.path.join(ROOT, "data")
NOTIFICATIONS_FILE = os.path.join(DATA_DIR, "notifications.json")


def _read_json(path, default):
    try:
        if not os.path.exists(path):
            return default

        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    except Exception:
        return default


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

    os.replace(temp_path, path)


def create_notification(
    title,
    message,
    severity="INFO",
    incident_id=None,
    service_name=None,
):
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

    history = _read_json(NOTIFICATIONS_FILE, [])

    if not isinstance(history, list):
        history = []

    history.insert(0, item)
    history = history[:300]

    _write_json(NOTIFICATIONS_FILE, history)

    _send_optional_webhook(item)

    return item


def _send_optional_webhook(item):
    """
    Optional outbound notification.
    Set AEGISOPS_NOTIFICATION_WEBHOOK to a Slack/Teams/custom webhook
    that accepts a simple JSON payload.
    """
    hook = os.environ.get("AEGISOPS_NOTIFICATION_WEBHOOK", "").strip()

    if not hook:
        return False

    payload = {
        "text": (
            f"[{item['severity']}] {item['title']}\n"
            f"{item['message']}"
        ),
        "aegisops": item,
    }

    try:
        request = urllib.request.Request(
            hook,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AegisOps-Notifications/1.0",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=12) as response:
            return 200 <= int(response.status) < 300

    except Exception as error:
        print("[NOTIFY] Webhook delivery failed:", error)
        return False


def get_notifications(limit=50):
    history = _read_json(NOTIFICATIONS_FILE, [])

    if not isinstance(history, list):
        return []

    return history[:max(1, int(limit))]


def unread_count():
    return sum(
        1
        for item in get_notifications(300)
        if not item.get("read", False)
    )


def mark_all_read():
    history = _read_json(NOTIFICATIONS_FILE, [])

    if not isinstance(history, list):
        history = []

    for item in history:
        item["read"] = True

    _write_json(NOTIFICATIONS_FILE, history)
    return True
