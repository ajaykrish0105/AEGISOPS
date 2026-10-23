"""Tests for consecutive health-check verification after agent recovery."""
import unittest
from unittest.mock import patch

from core import monitor


class AgentRecoveryVerificationTests(unittest.TestCase):
    def test_requires_three_consecutive_successes(self):
        outcomes = [
            {"healthy": True},
            {"healthy": False},
            {"healthy": True},
            {"healthy": True},
            {"healthy": True},
        ]
        with patch.object(monitor, "check_health", side_effect=outcomes), patch.object(
            monitor.time, "sleep"
        ):
            result = monitor.verify_agent_recovery({"id": "SVC-004"}, max_checks=5)

        self.assertTrue(result["verified"])
        self.assertTrue(result["success"])
        self.assertEqual(result["verification_checks"], 5)
        self.assertEqual(result["consecutive_successful_checks"], 3)

    def test_intermittent_successes_do_not_verify_recovery(self):
        outcomes = [
            {"healthy": True},
            {"healthy": False},
            {"healthy": True},
            {"healthy": False},
            {"healthy": True},
            {"healthy": False},
        ]
        with patch.object(monitor, "check_health", side_effect=outcomes), patch.object(
            monitor.time, "sleep"
        ):
            result = monitor.verify_agent_recovery({"id": "SVC-004"}, max_checks=6)

        self.assertFalse(result["verified"])
        self.assertFalse(result["success"])
        self.assertEqual(result["verification_checks"], 6)
        self.assertEqual(result["consecutive_successful_checks"], 0)


if __name__ == "__main__":
    unittest.main()
