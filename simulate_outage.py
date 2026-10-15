import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
SERVICES_FILE = os.path.join(DATA_DIR, "services.json")
SIMULATION_FILE = os.path.join(DATA_DIR, "recovery_simulation.json")

TARGET_SERVICE_ID = "SVC-003"
FAILURE_CHECKS = 3


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = path + ".tmp"

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

    os.replace(temp_path, path)


services = read_json(SERVICES_FILE, [])
service = next(
    (
        item for item in services
        if isinstance(item, dict)
        and str(item.get("id")) == TARGET_SERVICE_ID
    ),
    None,
)

if not service:
    print("ERROR: SVC-003 was not found in data/services.json")
    raise SystemExit(1)

if not service.get("monitoring_enabled", True):
    print("ERROR: Monitoring is OFF for Crafted Web.")
    raise SystemExit(1)

if not service.get("auto_recovery", False):
    print("ERROR: Auto Recovery is OFF for Crafted Web.")
    raise SystemExit(1)

simulation = {
    "active": True,
    "service_id": TARGET_SERVICE_ID,
    "service_name": service.get("name"),
    "total_failures": FAILURE_CHECKS,
    "remaining_failures": FAILURE_CHECKS,
    "started_at": datetime.now().isoformat(timespec="seconds"),
    "mode": "SAFE_MONITOR_OUTAGE_SIMULATION",
    "note": (
        "The real website stays online. Only AegisOps monitor receives "
        "three synthetic failed checks. Recovery verification uses the "
        "real health URL."
    ),
}

write_json(SIMULATION_FILE, simulation)

print("=" * 68)
print("AEGISOPS SAFE AUTOMATIC RECOVERY TEST")
print("=" * 68)
print("Service :", service.get("name"))
print("ID      :", TARGET_SERVICE_ID)
print("Failures:", FAILURE_CHECKS)
print()
print("Simulation armed.")
print("Do NOT click Test Connector or Run Recovery Drill.")
print()
print("The running AegisOps monitor should now automatically:")
print("  1. Detect failure 1/3")
print("  2. Detect failure 2/3")
print("  3. Confirm outage 3/3")
print("  4. Trigger the configured Render recovery connector")
print("  5. Verify the real website returns HTTP 200")
print("  6. Create a RESOLVED incident and notification")
print("=" * 68)
