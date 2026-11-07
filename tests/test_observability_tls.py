"""
tests/test_observability_tls.py
Unit tests cho các hàm kiểm tra của TV4 (4.1, 4.2, 5.1, 5.2)
Chạy độc lập bằng lệnh: python -m unittest tests/test_observability_tls.py
"""

import unittest
from unittest.mock import patch
from checks.observability_tls.checker import (
    check_4_1_logging_enabled,
    check_4_2_auditing_enabled,
    check_5_1_internode_encryption,
    check_5_2_client_encryption
)

class TestObservabilityTLSChecks(unittest.TestCase):

    REQUIRED_SCHEMA_KEYS = [
        "schema_version", "run_id", "timestamp_utc", "control_id",
        "owner", "cis_status", "scope", "target", "status",
        "actual", "expected", "evidence", "policy_ref", "reason", "duration_ms"
    ]

    def _assert_schema_compliance(self, res):
        for k in self.REQUIRED_SCHEMA_KEYS:
            self.assertIn(k, res, f"Kết quả thiếu key bắt buộc: {k}")
        self.assertEqual(res["owner"], "Lê Anh Quân")
        self.assertEqual(res["schema_version"], "1.0")

    # --------------------------------------------------------------------------
    # Test 4.1: Logging
    # --------------------------------------------------------------------------
    @patch("checks.observability_tls.checker._run_node_command")
    def test_4_1_pass_when_info(self, mock_cmd):
        mock_cmd.return_value = {
            "exit_code": 0,
            "stdout": "Logger Name                        Log Level\nROOT                               INFO\norg.apache.cassandra               WARN",
            "stderr": ""
        }
        res = check_4_1_logging_enabled("cass-dev1")
        self._assert_schema_compliance(res)
        self.assertEqual(res["status"], "PASS")
        self.assertIn("INFO", res["actual"])

    @patch("checks.observability_tls.checker._run_node_command")
    def test_4_1_fail_when_off(self, mock_cmd):
        mock_cmd.return_value = {
            "exit_code": 0,
            "stdout": "Logger Name                        Log Level\nROOT                               OFF",
            "stderr": ""
        }
        res = check_4_1_logging_enabled("cass-dev1")
        self._assert_schema_compliance(res)
        self.assertEqual(res["status"], "FAIL")

    @patch("checks.observability_tls.checker._run_node_command")
    def test_4_1_error_on_ssh_failure(self, mock_cmd):
        mock_cmd.return_value = {
            "exit_code": -1,
            "stdout": "",
            "stderr": "SSH Connection refused"
        }
        res = check_4_1_logging_enabled("cass-dev1")
        self._assert_schema_compliance(res)
        self.assertEqual(res["status"], "ERROR")

    # --------------------------------------------------------------------------
    # Test 4.2: Audit Logging
    # --------------------------------------------------------------------------
    @patch("checks.observability_tls.checker._run_node_command")
    def test_4_2_pass_when_enabled(self, mock_cmd):
        mock_cmd.return_value = {
            "exit_code": 0,
            "stdout": "audit_logging_options:\n    enabled: true\n    logger: BinAuditLogger\n    audit_logs_dir: /var/log/cassandra/audit\n",
            "stderr": ""
        }
        res = check_4_2_auditing_enabled("cass-dev1")
        self._assert_schema_compliance(res)
        self.assertEqual(res["status"], "PASS")

    @patch("checks.observability_tls.checker._run_node_command")
    def test_4_2_fail_when_disabled(self, mock_cmd):
        mock_cmd.return_value = {
            "exit_code": 0,
            "stdout": "audit_logging_options:\n    enabled: false\n",
            "stderr": ""
        }
        res = check_4_2_auditing_enabled("cass-dev1")
        self._assert_schema_compliance(res)
        self.assertEqual(res["status"], "FAIL")

    # --------------------------------------------------------------------------
    # Test 5.1: Inter-node Encryption
    # --------------------------------------------------------------------------
    @patch("checks.observability_tls.checker._run_node_command")
    def test_5_1_pass_when_all(self, mock_cmd):
        mock_cmd.return_value = {
            "exit_code": 0,
            "stdout": "server_encryption_options:\n    internode_encryption: all\n",
            "stderr": ""
        }
        res = check_5_1_internode_encryption("cass-dev1")
        self._assert_schema_compliance(res)
        self.assertEqual(res["status"], "PASS")

    # --------------------------------------------------------------------------
    # Test 5.2: Client Encryption
    # --------------------------------------------------------------------------
    @patch("checks.observability_tls.checker._run_node_command")
    def test_5_2_pass_when_strict_tls(self, mock_cmd):
        mock_cmd.return_value = {
            "exit_code": 0,
            "stdout": "client_encryption_options:\n    enabled: true\n    optional: false\n",
            "stderr": ""
        }
        res = check_5_2_client_encryption("cass-dev1")
        self._assert_schema_compliance(res)
        self.assertEqual(res["status"], "PASS")

if __name__ == "__main__":
    unittest.main()

