"""Safety tests for SVC-004 registration defaults."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import register_backend_lab


class BackendLabRegistrationTests(unittest.TestCase):
    def test_existing_svc004_has_auto_recovery_forced_off(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            services_path = root / "services.json"
            agents_path = root / "agents.json"
            policy_path = root / "policy.json"
            backend_path = root / "restart_backend.py"
            backend_path.write_text("# test fixture\n", encoding="utf-8")

            services_path.write_text(json.dumps([
                {
                    "id": "SVC-004",
                    "name": "AegisOps Demo Backend",
                    "health_url": "http://127.0.0.1:8200/health",
                    "monitoring_enabled": True,
                    "auto_recovery": True,
                    "custom_setting": "preserve-me",
                }
            ]), encoding="utf-8")
            agents_path.write_text(json.dumps([
                {
                    "id": "AGENT-001",
                    "name": "Local Lab Agent",
                    "base_url": "http://127.0.0.1:9100",
                    "enabled": True,
                    "bindings": [
                        {
                            "service_id": "SVC-004",
                            "agent_service": "aegisops-demo-backend",
                        }
                    ],
                }
            ]), encoding="utf-8")
            policy_path.write_text(json.dumps({
                "services": {
                    "aegisops-demo-backend": {
                        "health_url": "http://127.0.0.1:8200/health",
                        "actions": {"RESTART_SERVICE": ["python", "restart_backend.py"]},
                    }
                }
            }), encoding="utf-8")

            with patch.multiple(
                register_backend_lab,
                SERVICES=services_path,
                AGENTS=agents_path,
                POLICY=policy_path,
                BACKEND=backend_path,
            ):
                register_backend_lab.main()

            updated = json.loads(services_path.read_text(encoding="utf-8"))
            self.assertIs(updated[0]["auto_recovery"], False)
            self.assertEqual(updated[0]["custom_setting"], "preserve-me")


if __name__ == "__main__":
    unittest.main()
