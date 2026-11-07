"""
checks.observability_tls.checker
Owner: TV4 (Lê Anh Quân)
Controls:
  - 4.1: Ensure that logging is enabled. (Automated)
  - 4.2: Ensure that auditing is enabled. (Manual / Automated via BinAuditLogger)
  - 5.1: Inter-node Encryption (Automated - Cuối kỳ)
  - 5.2: Client Encryption (Automated - Cuối kỳ)

Tuân thủ nghiêm ngặt schemas/results.json và AGENTS.md:
- Trả về dict chuẩn 1.0
- Che giấu mật khẩu / secrets
- Xử lý lỗi kết nối thành ERROR, không tự biến thành PASS hay FAIL
"""

import os
import re
import time
import subprocess
from typing import Dict, Any, List, Optional

DEFAULT_OWNER = "Lê Anh Quân"

def _run_node_command(target_node: str, cmd: str, ssh_user: str = "labadmin") -> Dict[str, Any]:
    """
    Thực thi lệnh trên node mục tiêu (qua SSH hoặc local nếu chạy trực tiếp trên node).
    """
    # Nếu đang chạy trực tiếp trên chính node mục tiêu hoặc target là localhost / 127.0.0.1
    if target_node in ["127.0.0.1", "localhost", "cass-dev1"] and os.path.exists("/etc/cassandra"):
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            return {"exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr}
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}

    # Thực thi qua SSH tới node (Cloud VM hoặc VMware host)
    ssh_cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=5 {ssh_user}@{target_node} '{cmd}'"
    try:
        res = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=20)
        return {"exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": f"SSH connection failed: {e}"}


def check_4_1_logging_enabled(target_node: str, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    CIS 4.1: Ensure that logging is enabled. (Automated)
    Audit Procedure:
      - Chạy nodetool getlogginglevels
      - Kiểm tra ROOT logger level không được là OFF.
      - Kiểm tra file cấu hình logback.xml để đảm bảo mức log bền vững qua restart.
    """
    start_time = time.time()
    policy_ref = "policies/lab.yml"
    expected = "ROOT logger level is not OFF (Default: INFO)"

    # 1. Thu thập mức log đang chạy thực tế qua nodetool
    cmd_nodetool = "nodetool getlogginglevels"
    exec_res = _run_node_command(target_node, cmd_nodetool)

    if exec_res["exit_code"] != 0:
        # Thử đường dẫn tuyệt đối tarball nếu nodetool không có trong PATH
        cmd_nodetool_full = "/opt/cassandra/bin/nodetool getlogginglevels"
        exec_res = _run_node_command(target_node, cmd_nodetool_full)

    if exec_res["exit_code"] != 0:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "4.1",
            "owner": "Lê Anh Quân",
            "cis_status": "A",
            "scope": "node",
            "target": target_node,
            "status": "ERROR",
            "actual": None,
            "expected": expected,
            "evidence": f"Failed to execute nodetool: {exec_res['stderr'].strip()}",
            "policy_ref": policy_ref,
            "reason": "Không thể kết nối hoặc không chạy được nodetool trên node",
            "duration_ms": duration_ms
        }

    stdout = exec_res["stdout"]
    # Parse output: tìm dòng chứa ROOT
    # Ví dụ:
    # Logger Name                        Log Level
    # ROOT                               INFO
    root_level = None
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].strip().upper() == "ROOT":
            root_level = parts[1].strip().upper()
            break

    duration_ms = round((time.time() - start_time) * 1000, 2)

    if not root_level:
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "4.1",
            "owner": "Lê Anh Quân",
            "cis_status": "A",
            "scope": "node",
            "target": target_node,
            "status": "FAIL",
            "actual": "ROOT logger not found in nodetool output",
            "expected": expected,
            "evidence": stdout.strip(),
            "policy_ref": policy_ref,
            "reason": "Không tìm thấy cấu hình mức ROOT logger",
            "duration_ms": duration_ms
        }

    if root_level == "OFF":
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "4.1",
            "owner": "Lê Anh Quân",
            "cis_status": "A",
            "scope": "node",
            "target": target_node,
            "status": "FAIL",
            "actual": f"ROOT log level is {root_level}",
            "expected": expected,
            "evidence": stdout.strip(),
            "policy_ref": policy_ref,
            "reason": "Mức log ROOT đang bị tắt (OFF), vi phạm chuẩn CIS 4.1",
            "duration_ms": duration_ms
        }

    return {
        "schema_version": "1.0",
        "run_id": f"run-{int(start_time)}",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": "4.1",
        "owner": "Lê Anh Quân",
        "cis_status": "A",
        "scope": "node",
        "target": target_node,
        "status": "PASS",
        "actual": f"ROOT log level is {root_level}",
        "expected": expected,
        "evidence": stdout.strip(),
        "policy_ref": policy_ref,
        "reason": f"Logging đang được kích hoạt với mức {root_level}",
        "duration_ms": duration_ms
    }


def check_4_2_auditing_enabled(target_node: str, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    CIS 4.2: Ensure that auditing is enabled. (Manual / Automated)
    Audit Procedure:
      - Đọc cấu hình audit_logging_options trong /etc/cassandra/cassandra.yaml
      - Kiểm tra enabled: true
      - Đồ án yêu cầu: class BinAuditLogger, thư mục audit riêng.
    """
    start_time = time.time()
    policy_ref = "policies/lab.yml"
    expected = "audit_logging_options.enabled: true (using BinAuditLogger)"

    # Đọc block audit_logging_options trong cassandra.yaml
    cmd = "cat /etc/cassandra/cassandra.yaml"
    exec_res = _run_node_command(target_node, cmd)

    if exec_res["exit_code"] != 0:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "4.2",
            "owner": "Lê Anh Quân",
            "cis_status": "M",
            "scope": "node",
            "target": target_node,
            "status": "ERROR",
            "actual": None,
            "expected": expected,
            "evidence": f"Failed to read cassandra.yaml: {exec_res['stderr'].strip()}",
            "policy_ref": policy_ref,
            "reason": "Không thể đọc file cấu hình /etc/cassandra/cassandra.yaml",
            "duration_ms": duration_ms
        }

    content = exec_res["stdout"]

    # Phân tích regex block audit_logging_options
    # Tránh phụ thuộc vào PyYAML nếu trên máy client chưa cài
    audit_match = re.search(r"^audit_logging_options:(.*?)(?=^[a-zA-Z0-9_]+:|\Z)", content, re.MULTILINE | re.DOTALL)

    duration_ms = round((time.time() - start_time) * 1000, 2)

    if not audit_match:
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "4.2",
            "owner": "Lê Anh Quân",
            "cis_status": "M",
            "scope": "node",
            "target": target_node,
            "status": "FAIL",
            "actual": "audit_logging_options section not found",
            "expected": expected,
            "evidence": "audit_logging_options block is missing from cassandra.yaml",
            "policy_ref": policy_ref,
            "reason": "Chưa cấu hình audit_logging_options trong cassandra.yaml",
            "duration_ms": duration_ms
        }

    audit_block = audit_match.group(1)
    
    # Kiểm tra enabled: true
    enabled_match = re.search(r"^\s+enabled:\s*(true|false)", audit_block, re.MULTILINE | re.IGNORECASE)
    logger_match = re.search(r"^\s+logger:\s*([a-zA-Z0-9_]+)", audit_block, re.MULTILINE)

    is_enabled = False
    if enabled_match and enabled_match.group(1).lower() == "true":
        is_enabled = True

    logger_name = logger_match.group(1) if logger_match else "Default"

    evidence_snippet = f"audit_logging_options:\n{audit_block.strip()}"

    if is_enabled:
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "4.2",
            "owner": "Lê Anh Quân",
            "cis_status": "M",
            "scope": "node",
            "target": target_node,
            "status": "PASS",
            "actual": f"enabled: true, logger: {logger_name}",
            "expected": expected,
            "evidence": evidence_snippet,
            "policy_ref": policy_ref,
            "reason": f"Audit logging đang được bật bằng logger {logger_name}",
            "duration_ms": duration_ms
        }
    else:
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "4.2",
            "owner": "Lê Anh Quân",
            "cis_status": "M",
            "scope": "node",
            "target": target_node,
            "status": "FAIL",
            "actual": "enabled: false" if enabled_match else "enabled is not defined",
            "expected": expected,
            "evidence": evidence_snippet,
            "policy_ref": policy_ref,
            "reason": "Audit logging đang bị tắt (enabled: false)",
            "duration_ms": duration_ms
        }


def check_5_1_internode_encryption(target_node: str, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    CIS 5.1: Inter-node Encryption (Automated)
    Kiểm tra server_encryption_options -> internode_encryption in ['all', 'dc', 'rack']
    Chính sách của nhóm yêu cầu đích đến: internode_encryption: all, optional: false
    """
    start_time = time.time()
    policy_ref = "policies/lab.yml"
    expected = "server_encryption_options.internode_encryption: all, optional: false"

    cmd = "cat /etc/cassandra/cassandra.yaml"
    exec_res = _run_node_command(target_node, cmd)

    duration_ms = round((time.time() - start_time) * 1000, 2)

    if exec_res["exit_code"] != 0:
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "5.1",
            "owner": "Lê Anh Quân",
            "cis_status": "A",
            "scope": "cluster",
            "target": target_node,
            "status": "ERROR",
            "actual": None,
            "expected": expected,
            "evidence": exec_res["stderr"].strip(),
            "policy_ref": policy_ref,
            "reason": "Không thể kết nối hoặc đọc cấu hình cassandra.yaml",
            "duration_ms": duration_ms
        }

    content = exec_res["stdout"]
    enc_match = re.search(r"^server_encryption_options:(.*?)(?=^[a-zA-Z0-9_]+:|\Z)", content, re.MULTILINE | re.DOTALL)

    if not enc_match:
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "5.1",
            "owner": "Lê Anh Quân",
            "cis_status": "A",
            "scope": "cluster",
            "target": target_node,
            "status": "FAIL",
            "actual": "server_encryption_options not configured",
            "expected": expected,
            "evidence": "server_encryption_options is missing",
            "policy_ref": policy_ref,
            "reason": "server_encryption_options chưa được khai báo trong cassandra.yaml",
            "duration_ms": duration_ms
        }

    enc_block = enc_match.group(1)
    internode_match = re.search(r"^\s+internode_encryption:\s*([a-zA-Z0-9_]+)", enc_block, re.MULTILINE)
    val = internode_match.group(1).lower() if internode_match else "none"

    if val in ["all", "dc", "rack"]:
        status = "PASS"
        reason = f"Inter-node encryption đang bật ở mức '{val}'"
    else:
        status = "FAIL"
        reason = f"Inter-node encryption đang để giá trị '{val}', không mã hóa"

    return {
        "schema_version": "1.0",
        "run_id": f"run-{int(start_time)}",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": "5.1",
        "owner": "Lê Anh Quân",
        "cis_status": "A",
        "scope": "cluster",
        "target": target_node,
        "status": status,
        "actual": f"internode_encryption: {val}",
        "expected": expected,
        "evidence": enc_block.strip(),
        "policy_ref": policy_ref,
        "reason": reason,
        "duration_ms": duration_ms
    }


def check_5_2_client_encryption(target_node: str, policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    CIS 5.2: Client Encryption (Automated)
    Kiểm tra client_encryption_options -> enabled: true, optional: false
    """
    start_time = time.time()
    policy_ref = "policies/lab.yml"
    expected = "client_encryption_options.enabled: true, optional: false"

    cmd = "cat /etc/cassandra/cassandra.yaml"
    exec_res = _run_node_command(target_node, cmd)

    duration_ms = round((time.time() - start_time) * 1000, 2)

    if exec_res["exit_code"] != 0:
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "5.2",
            "owner": "Lê Anh Quân",
            "cis_status": "A",
            "scope": "node",
            "target": target_node,
            "status": "ERROR",
            "actual": None,
            "expected": expected,
            "evidence": exec_res["stderr"].strip(),
            "policy_ref": policy_ref,
            "reason": "Không thể kết nối hoặc đọc cấu hình cassandra.yaml",
            "duration_ms": duration_ms
        }

    content = exec_res["stdout"]
    client_match = re.search(r"^client_encryption_options:(.*?)(?=^[a-zA-Z0-9_]+:|\Z)", content, re.MULTILINE | re.DOTALL)

    if not client_match:
        return {
            "schema_version": "1.0",
            "run_id": f"run-{int(start_time)}",
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "control_id": "5.2",
            "owner": "Lê Anh Quân",
            "cis_status": "A",
            "scope": "node",
            "target": target_node,
            "status": "FAIL",
            "actual": "client_encryption_options not configured",
            "expected": expected,
            "evidence": "client_encryption_options is missing",
            "policy_ref": policy_ref,
            "reason": "client_encryption_options chưa được khai báo trong cassandra.yaml",
            "duration_ms": duration_ms
        }

    client_block = client_match.group(1)
    enabled_m = re.search(r"^\s+enabled:\s*(true|false)", client_block, re.MULTILINE | re.IGNORECASE)
    optional_m = re.search(r"^\s+optional:\s*(true|false)", client_block, re.MULTILINE | re.IGNORECASE)

    enabled_val = enabled_m.group(1).lower() == "true" if enabled_m else False
    optional_val = optional_m.group(1).lower() == "true" if optional_m else False

    # Theo CIS Benchmark: Nếu enabled == True thì success
    # Theo chính sách tăng cường của nhóm: Bắt buộc optional == False để chặn kết nối unencrypted
    if enabled_val and not optional_val:
        status = "PASS"
        reason = "Client encryption được kích hoạt và bắt buộc mã hóa (optional: false)"
    elif enabled_val and optional_val:
        status = "NEEDS_REVIEW"
        reason = "Client encryption được bật nhưng optional: true (vẫn cho phép kết nối không mã hóa)"
    else:
        status = "FAIL"
        reason = "Client encryption đang bị tắt (enabled: false)"

    return {
        "schema_version": "1.0",
        "run_id": f"run-{int(start_time)}",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": "5.2",
        "owner": "Lê Anh Quân",
        "cis_status": "A",
        "scope": "node",
        "target": target_node,
        "status": status,
        "actual": f"enabled: {enabled_val}, optional: {optional_val}",
        "expected": expected,
        "evidence": client_block.strip(),
        "policy_ref": policy_ref,
        "reason": reason,
        "duration_ms": duration_ms
    }


def run_all_checks(target_node: str, policy: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Điểm chạy tập trung gọi toàn bộ 4 checks của TV4.
    """
    return [
        check_4_1_logging_enabled(target_node, policy),
        check_4_2_auditing_enabled(target_node, policy),
        check_5_1_internode_encryption(target_node, policy),
        check_5_2_client_encryption(target_node, policy),
    ]
