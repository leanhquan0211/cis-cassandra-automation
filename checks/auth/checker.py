"""
checks.auth.checker
Owner: TV2 (Đoàn Thanh Đệ)
Controls: 2.1 2.2, 3.1, 3.2

Mục 2.1 kiểm tra gì?
    SSH vào node -> đọc /etc/cassandra/cassandra.yaml -> tìm dòng "authenticator:"
    -> so với policy (policies/lab.yml, auth.authenticator = PasswordAuthenticator).

SSH vào node bằng gì?
    Dùng lệnh `ssh <target_node>` bình thường. Hãy chạy checker TRÊN ctrl-dev và truyền
    IP private của node (ví dụ 192.168.56.139). SSH sẽ dùng user hiện tại (ubuntu) và
    key mặc định ~/.ssh/id_rsa nên code này không cần biết user/key.
    Lần đầu phải `ssh ubuntu@<ip>` thủ công một lần để chấp nhận host key.

Chạy thử (trên ctrl-dev):
    python3 -m checks.auth.checker 192.168.56.139
"""

import subprocess
import time
from typing import Any, Dict, List, Tuple

CONF_PATH = "/etc/cassandra/cassandra.yaml"


def _read_authenticator(target_node: str) -> Tuple[Any, Any]:
    """
    SSH vào node, đọc cassandra.yaml, trả về (giá trị authenticator, dòng gốc).
    Không có dòng authenticator đang hoạt động -> trả về (None, None).
    Không SSH/đọc được -> raise RuntimeError.
    """
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
           target_node, "cat", CONF_PATH]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"Không chạy được ssh tới {target_node}: {exc}")
    if proc.returncode != 0:
        raise RuntimeError(f"Không đọc được {CONF_PATH} trên {target_node}: {proc.stderr.strip()}")

    for line in proc.stdout.splitlines():
        # Chỉ lấy dòng đang hoạt động (không bị comment #, không thụt lề)
        if line.startswith("authenticator:"):
            value = line.split(":", 1)[1].split("#")[0].strip()
            return value, line.strip()
    return None, None


def check_2_1_authentication_enabled(target_node: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    CIS 2.1: authenticator phải là PasswordAuthenticator.
        ERROR        : không đọc được cấu hình trên node
        FAIL         : chưa đặt authenticator hoặc đang là AllowAllAuthenticator
        PASS         : đúng giá trị policy yêu cầu
        NEEDS_REVIEW : giá trị khác (không phải AllowAll nhưng cũng không khớp policy)
    """
    start = time.time()
    expected = policy.get("auth", {}).get("authenticator", "PasswordAuthenticator")

    status, actual, evidence, reason = "ERROR", None, "", ""
    try:
        value, line = _read_authenticator(target_node)
    except RuntimeError as exc:
        evidence = str(exc)
        reason = "Không thu thập được cấu hình nên không thể kết luận PASS/FAIL"
    else:
        short_name = (value or "").split(".")[-1]  # chấp nhận cả tên đầy đủ org.apache...X
        if not value or short_name == "AllowAllAuthenticator":
            status = "FAIL"
            actual = value or "chưa đặt (mặc định AllowAllAuthenticator)"
            evidence = line or f"{CONF_PATH}: không có dòng 'authenticator:' đang hoạt động"
            reason = "AllowAllAuthenticator không yêu cầu đăng nhập"
        elif short_name == expected:
            status, actual, evidence = "PASS", value, line
            reason = f"authenticator đúng theo policy ({expected})"
        else:
            status, actual, evidence = "NEEDS_REVIEW", value, line
            reason = f"authenticator khác policy ({expected}), cần người xem xét"

    return {
        "schema_version": "1.0",
        "run_id": "run-local",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": "2.1",
        "owner": "TV2",
        "cis_status": "A",
        "scope": "node",
        "target": target_node,
        "status": status,
        "actual": actual,
        "expected": f"authenticator: {expected}",
        "evidence": evidence,
        "policy_ref": "policies/lab.yml",
        "reason": reason,
        "duration_ms": round((time.time() - start) * 1000, 2),
    }


def run_all_checks(target_node: str, policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Hiện mới có 2.1. Làm xong 2.2, 3.2, 3.1 thì thêm vào danh sách này.
    return [
        check_2_1_authentication_enabled(target_node, policy),
    ]


if __name__ == "__main__":
    import json
    import sys

    import yaml  # pip install pyyaml

    if len(sys.argv) < 2:
        sys.exit("Cách dùng: python3 -m checks.auth.checker <ip-hoặc-hostname-của-node>")
    target = sys.argv[1]
    with open("policies/lab.yml", "r", encoding="utf-8") as fh:
        policy_data = yaml.safe_load(fh)
    print(json.dumps(run_all_checks(target, policy_data), ensure_ascii=False, indent=2))