import json
import os
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


# ============================================================
# AEGISOPS DEMO CLOUD SERVICE V2
# ============================================================

ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

DATA_DIR = os.path.join(ROOT, "data")

STATE_FILE = os.path.join(
    DATA_DIR,
    "service_state.json"
)

LOG_FILE = os.path.join(
    DATA_DIR,
    "service.log"
)

HOST = "127.0.0.1"
PORT = 8000
SERVICE_NAME = "payment-api"


# ============================================================
# LOG WRITER
# ============================================================

def write_log(level, message):

    os.makedirs(DATA_DIR, exist_ok=True)

    timestamp = datetime.now().isoformat(
        timespec="seconds"
    )

    line = (
        f"{timestamp} [{level}] "
        f"{SERVICE_NAME}: {message}"
    )

    with open(
        LOG_FILE,
        "a",
        encoding="utf-8"
    ) as file:
        file.write(line + "\n")

    print(f"[{level}] {message}")


# ============================================================
# SERVICE STATE
# ============================================================

def save_state(
    status,
    failure_type="none",
    process_crashed=False,
    recent_deployment=False,
    error_500=False
):

    os.makedirs(DATA_DIR, exist_ok=True)

    state = {
        "timestamp": datetime.now().isoformat(
            timespec="seconds"
        ),
        "service": SERVICE_NAME,
        "status": status,
        "failure_type": failure_type,
        "process_crashed": process_crashed,
        "recent_deployment": recent_deployment,
        "error_500": error_500
    }

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            state,
            file,
            indent=4
        )


# ============================================================
# HTTP SERVICE
# ============================================================

class ServiceHandler(BaseHTTPRequestHandler):

    def send_json(self, status_code, data):

        body = json.dumps(data).encode(
            "utf-8"
        )

        self.send_response(status_code)

        self.send_header(
            "Content-Type",
            "application/json"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)


    def do_GET(self):

        # ----------------------------------------------------
        # HEALTH CHECK
        # ----------------------------------------------------

        if self.path == "/health":

            self.send_json(
                200,
                {
                    "service": SERVICE_NAME,
                    "status": "healthy"
                }
            )

            return


        # ----------------------------------------------------
        # CONTROLLED CRASH
        # ----------------------------------------------------

        if self.path == "/crash":

            write_log(
                "CRITICAL",
                "Fatal application failure detected"
            )

            save_state(
                status="DOWN",
                failure_type="application_crash",
                process_crashed=True
            )

            self.send_json(
                500,
                {
                    "service": SERVICE_NAME,
                    "status": "crashing",
                    "failure_type":
                        "application_crash"
                }
            )

            write_log(
                "CRITICAL",
                "Service process shutting down"
            )

            threading.Thread(
                target=self.server.shutdown,
                daemon=True
            ).start()

            return


        # ----------------------------------------------------
        # HOME
        # ----------------------------------------------------

        if self.path == "/":

            self.send_json(
                200,
                {
                    "service": SERVICE_NAME,
                    "status": "online",
                    "message":
                        "AegisOps protected service"
                }
            )

            return


        self.send_json(
            404,
            {
                "error": "not_found"
            }
        )


    # Disable normal HTTP request spam

    def log_message(
        self,
        format,
        *args
    ):
        return


# ============================================================
# START SERVICE
# ============================================================

def start_service():

    os.makedirs(
        DATA_DIR,
        exist_ok=True
    )

    # Every successful start resets service state.

    save_state(
        status="HEALTHY",
        failure_type="none",
        process_crashed=False,
        recent_deployment=False,
        error_500=False
    )

    write_log(
        "INFO",
        "payment-api started successfully"
    )

    server = HTTPServer(
        (HOST, PORT),
        ServiceHandler
    )

    print()
    print("=" * 64)
    print(
        "          AEGISOPS DEMO CLOUD SERVICE V2"
    )
    print("=" * 64)

    print(f"Service : {SERVICE_NAME}")
    print(f"Address : http://{HOST}:{PORT}")
    print(f"Health  : http://{HOST}:{PORT}/health")
    print(f"Crash   : http://{HOST}:{PORT}/crash")

    print()
    print(
        "[ONLINE] payment-api is healthy"
    )

    print("=" * 64)

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        write_log(
            "INFO",
            "Service manually stopped"
        )

    finally:

        server.server_close()

    print()
    print(
        "[DOWN] payment-api is offline"
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    start_service()