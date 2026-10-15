import os
import sys
import time
import signal
import subprocess
import urllib.request
import webbrowser
from datetime import datetime

# ============================================================
# AEGISOPS MASTER LAUNCHER V4
# Starts and supervises:
#   1. Demo payment-api
#   2. Multi-service monitor
#   3. Flask web console
# If monitor/web crashes, launcher restarts it automatically.
# ============================================================

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")

DEMO_SERVICE = os.path.join(ROOT, "demo", "service.py")
MONITOR_SCRIPT = os.path.join(ROOT, "core", "monitor.py")
WEB_SCRIPT = os.path.join(ROOT, "web", "app.py")

SERVICE_URL = "http://127.0.0.1:8000/health"
DASHBOARD_URL = "http://127.0.0.1:5000/"

SERVICE_LOG = os.path.join(DATA_DIR, "service_console.log")
MONITOR_LOG = os.path.join(DATA_DIR, "monitor_console.log")
WEB_LOG = os.path.join(DATA_DIR, "web_console.log")

os.makedirs(DATA_DIR, exist_ok=True)

children = {
    "service": None,
    "monitor": None,
    "web": None,
}

log_handles = {}


def now():
    return datetime.now().strftime("%H:%M:%S")


def url_online(url, timeout=1.0):
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "AegisOps-Launcher/4.0"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 500
    except Exception:
        return False


def open_log(name, path):
    handle = open(path, "a", encoding="utf-8", buffering=1)
    handle.write(
        f"\n\n{'=' * 70}\n"
        f"AEGISOPS {name.upper()} START {datetime.now().isoformat(timespec='seconds')}\n"
        f"{'=' * 70}\n"
    )
    log_handles[name] = handle
    return handle


def start_python(name, script, log_path):
    if not os.path.exists(script):
        print(f"[{now()}] [ERROR] Missing {name} script: {script}")
        return None

    old_handle = log_handles.get(name)
    if old_handle:
        try:
            old_handle.close()
        except Exception:
            pass

    handle = open_log(name, log_path)

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        [sys.executable, "-u", script],
        cwd=ROOT,
        stdout=handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )

    children[name] = process

    print(
        f"[{now()}] [STARTED] {name:<8} "
        f"PID={process.pid}"
    )

    return process


def wait_for_url(url, seconds=12):
    deadline = time.time() + seconds

    while time.time() < deadline:
        if url_online(url):
            return True
        time.sleep(0.4)

    return False


def ensure_demo_service():
    if url_online(SERVICE_URL):
        print(
            f"[{now()}] [OK]      payment-api already healthy"
        )
        return

    print(
        f"[{now()}] [START]   payment-api"
    )

    process = start_python(
        "service",
        DEMO_SERVICE,
        SERVICE_LOG
    )

    if process is None:
        return

    if wait_for_url(SERVICE_URL, 10):
        print(
            f"[{now()}] [HEALTHY] payment-api HTTP endpoint ready"
        )
    else:
        print(
            f"[{now()}] [WARN]    payment-api did not become healthy yet"
        )


def ensure_monitor():
    process = children.get("monitor")

    if process is None or process.poll() is not None:
        if process is not None:
            print(
                f"[{now()}] [RESTART] monitor exited "
                f"with code {process.returncode}"
            )

        start_python(
            "monitor",
            MONITOR_SCRIPT,
            MONITOR_LOG
        )


def ensure_web():
    # If another valid AegisOps web process is already serving port 5000,
    # do not create a duplicate Flask server.
    if url_online(DASHBOARD_URL):
        process = children.get("web")

        if process is None:
            print(
                f"[{now()}] [OK]      web console already online"
            )

        return

    process = children.get("web")

    if process is None or process.poll() is not None:
        if process is not None:
            print(
                f"[{now()}] [RESTART] web exited "
                f"with code {process.returncode}"
            )

        start_python(
            "web",
            WEB_SCRIPT,
            WEB_LOG
        )

        if wait_for_url(DASHBOARD_URL, 10):
            print(
                f"[{now()}] [ONLINE]  dashboard ready"
            )
        else:
            print(
                f"[{now()}] [WARN]    dashboard not responding yet"
            )


def terminate_process(name):
    process = children.get(name)

    if process is None:
        return

    if process.poll() is not None:
        return

    try:
        print(
            f"[{now()}] [STOP]    {name} PID={process.pid}"
        )

        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
            time.sleep(0.5)

            if process.poll() is None:
                process.terminate()
        else:
            process.terminate()

        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def close_logs():
    for handle in log_handles.values():
        try:
            handle.close()
        except Exception:
            pass


def show_status():
    monitor = children.get("monitor")
    web = children.get("web")

    monitor_state = (
        "RUNNING"
        if monitor is not None and monitor.poll() is None
        else "STOPPED"
    )

    web_state = (
        "ONLINE"
        if url_online(DASHBOARD_URL)
        else "OFFLINE"
    )

    service_state = (
        "HEALTHY"
        if url_online(SERVICE_URL)
        else "DOWN"
    )

    print()
    print("=" * 70)
    print("AEGISOPS READY")
    print("=" * 70)
    print(f"payment-api : {service_state}")
    print(f"monitor     : {monitor_state}")
    print(f"web console : {web_state}")
    print(f"dashboard   : {DASHBOARD_URL}")
    print("=" * 70)
    print("Launcher watchdog is active. Press Ctrl+C to stop AegisOps.")
    print()


def main():
    print()
    print("=" * 70)
    print("AEGISOPS MASTER LAUNCHER V4")
    print("=" * 70)

    ensure_demo_service()
    ensure_monitor()
    ensure_web()

    show_status()

    try:
        webbrowser.open(DASHBOARD_URL)
    except Exception:
        pass

    last_status = 0

    try:
        while True:
            # Core reliability fix:
            # monitor and web are supervised continuously.
            ensure_monitor()
            ensure_web()

            # The demo service is intentionally NOT force-restarted here.
            # When it crashes, monitor.py must be allowed to detect the
            # incident and run the AegisOps recovery pipeline.

            if time.time() - last_status >= 15:
                monitor = children.get("monitor")

                if monitor is not None and monitor.poll() is None:
                    print(
                        f"[{now()}] [WATCHDOG] monitor RUNNING | "
                        f"dashboard {'ONLINE' if url_online(DASHBOARD_URL) else 'OFFLINE'}"
                    )

                last_status = time.time()

            time.sleep(2)

    except KeyboardInterrupt:
        print()
        print(
            f"[{now()}] AegisOps shutdown requested."
        )

    finally:
        # Stop only processes launched by this master launcher.
        terminate_process("monitor")
        terminate_process("web")
        terminate_process("service")
        close_logs()

        print(
            f"[{now()}] AegisOps stopped."
        )


if __name__ == "__main__":
    main()
