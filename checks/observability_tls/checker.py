"""
checks.observability_tls.checker
Owner: TV4 (Lê Anh Quân)
Controls: 4.1, 4.2, 5.1, 5.2
"""

from typing import Dict, Any, List
import time

def check_4_1_logging_enabled(target_node: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    CIS 4.1: Ensure that logging is enabled. (Automated)
    Kiểm tra mức logging hiện tại qua `nodetool getlogginglevels`.
    Mức ROOT không được là OFF. Mức hợp lệ theo policy: INFO, WARN, DEBUG, ERROR.
    """
    start_time = time.time()
    # TODO: Thực thi `nodetool getlogginglevels` trên target_node qua SSH
    # Mock / Prototype logic:
    return {
        "schema_version": "1.0",
        "run_id": "run-local",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": "4.1",
        "owner": "TV4",
        "cis_status": "A",
        "scope": "node",
        "target": target_node,
        "status": "NOT_IMPLEMENTED",
        "actual": None,
        "expected": "ROOT logger level != OFF",
        "evidence": "Chưa kết nối SSH thực thi lệnh nodetool getlogginglevels",
        "policy_ref": "policies/lab.yml",
        "reason": "Chưa cấu hình runner kết nối tới node",
        "duration_ms": round((time.time() - start_time) * 1000, 2)
    }

def check_4_2_auditing_enabled(target_node: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    CIS 4.2: Ensure that auditing is enabled. (Manual / Automated)
    Kiểm tra file cassandra.yaml -> audit_logging_options -> enabled == True.
    Đồ án yêu cầu: Dùng BinAuditLogger, thư mục audit 512 MiB, kiểm chứng bằng auditlogviewer.
    """
    start_time = time.time()
    # TODO: Đọc cassandra.yaml trên target_node
    return {
        "schema_version": "1.0",
        "run_id": "run-local",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": "4.2",
        "owner": "TV4",
        "cis_status": "M",
        "scope": "node",
        "target": target_node,
        "status": "NOT_IMPLEMENTED",
        "actual": None,
        "expected": "audit_logging_options.enabled: true (BinAuditLogger)",
        "evidence": "Chưa đọc cấu hình /etc/cassandra/cassandra.yaml",
        "policy_ref": "policies/lab.yml",
        "reason": "Chưa cấu hình runner đọc file yaml",
        "duration_ms": round((time.time() - start_time) * 1000, 2)
    }

def check_5_1_internode_encryption(target_node: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    CIS 5.1: Inter-node Encryption (Automated)
    cassandra.yaml -> server_encryption_options -> internode_encryption: all
    """
    return {
        "schema_version": "1.0",
        "run_id": "run-local",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": "5.1",
        "owner": "TV4",
        "cis_status": "A",
        "scope": "cluster",
        "target": target_node,
        "status": "NOT_IMPLEMENTED",
        "actual": None,
        "expected": "internode_encryption: all",
        "evidence": "",
        "policy_ref": "policies/lab.yml",
        "reason": "Mục tiêu cuối kỳ",
        "duration_ms": 0.0
    }

def check_5_2_client_encryption(target_node: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    CIS 5.2: Client Encryption (Automated)
    cassandra.yaml -> client_encryption_options -> enabled: true, optional: false
    """
    return {
        "schema_version": "1.0",
        "run_id": "run-local",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": "5.2",
        "owner": "TV4",
        "cis_status": "A",
        "scope": "node",
        "target": target_node,
        "status": "NOT_IMPLEMENTED",
        "actual": None,
        "expected": "client_encryption_options.enabled: true, optional: false",
        "evidence": "",
        "policy_ref": "policies/lab.yml",
        "reason": "Mục tiêu cuối kỳ",
        "duration_ms": 0.0
    }

def run_all_checks(target_node: str, policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        check_4_1_logging_enabled(target_node, policy),
        check_4_2_auditing_enabled(target_node, policy),
        check_5_1_internode_encryption(target_node, policy),
        check_5_2_client_encryption(target_node, policy),
    ]
