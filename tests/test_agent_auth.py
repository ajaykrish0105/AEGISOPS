"""Authentication tests for the AegisOps remote agent."""
import unittest
from unittest.mock import patch

from agent import agent as agent_module


class AgentAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.client = agent_module.app.test_client()

    def test_missing_token_is_rejected(self):
        with patch.object(agent_module, "AGENT_TOKEN", ""):
            response = self.client.get("/v1/health")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["success"])

    def test_invalid_token_is_rejected(self):
        with patch.object(agent_module, "AGENT_TOKEN", "expected-test-token"):
            response = self.client.get(
                "/v1/health",
                headers={"Authorization": "Bearer incorrect-test-token"},
            )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["success"])

    def test_valid_token_is_accepted(self):
        with patch.object(agent_module, "AGENT_TOKEN", "expected-test-token"):
            response = self.client.get(
                "/v1/health",
                headers={"Authorization": "Bearer expected-test-token"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
