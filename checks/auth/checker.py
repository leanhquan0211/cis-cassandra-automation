"""
checks.auth.checker
Owner: TV2 (Đoàn Thanh Đệ)
Controls: 2.1, 2.2, 3.1, 3.2

2.1 và 2.2: SSH vào node -> đọc /etc/cassandra/cassandra.yaml -> tìm dòng "<khóa>:" -> so với policy.
    2.1  authenticator  (policy: auth.authenticator = PasswordAuthenticator)
    2.2  authorizer     (policy: auth.authorizer    = CassandraAuthorizer)

3.2: thử đăng nhập CQL bằng tài khoản mặc định cassandra/cassandra (qua cis_lab.connection).
    Đăng nhập được   -> FAIL (mật khẩu mặc định chưa đổi)
    Bị từ chối       -> PASS
    Lỗi kết nối      -> ERROR (không bao giờ coi lỗi kết nối là PASS)

Yêu cầu khi chạy trên ctrl-dev:
    pip install cassandra-driver pyyaml
    - 2.1/2.2 dùng `ssh <target>` (user hiện tại + key ~/.ssh/id_rsa). Lần đầu phải
      `ssh ubuntu@<ip>` thủ công một lần để chấp nhận host key.
    - 3.2 cần ctrl-dev kết nối được <target>:9042. Cassandra mặc định chỉ lắng nghe CQL ở
      localhost, nên node phải đặt rpc_address thành IP private (khóa thuộc namespace TV3).
    - Truyền IP private của node làm target (ví dụ 192.168.56.139).

Chạy thử (trên ctrl-dev, ở thư mục gốc của repo):
    python3 -m checks.auth.checker 192.168.56.139
"""

import subprocess
import time
from typing import Any, Dict, List, Tuple

from cis_lab.connection import execute_cql

CONF_PATH = "/etc/cassandra/cassandra.yaml"
CQL_PORT = 9042

# Tài khoản và mật khẩu mặc định của Cassandra theo CIS 3.2 (thông tin công khai, không phải bí mật)
DEFAULT_ROLE = "cassandra"
DEFAULT_PASSWORD = "cassandra"


# ------------------------------------------------------------------------------
# Hàm dùng chung
# ------------------------------------------------------------------------------

def _make_result(
    control_id: str,
    scope: str,
    target_node: str,
    status: str,
    actual: Any,
    expected: str,
    evidence: str,
    reason: str,
    start: float,
) -> Dict[str, Any]:
    """Tạo dict đúng schemas/results.json."""
    return {
        "schema_version": "1.0",
        "run_id": "run-local",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "control_id": control_id,
        "owner": "TV2",
        "cis_status": "A",
        "scope": scope,
        "target": target_node,
        "status": status,
        "actual": actual,
        "expected": expected,
        "evidence": evidence,
        "policy_ref": "policies/lab.yml",
        "reason": reason,
        "duration_ms": round((time.time() - start) * 1000, 2),
    }


# ------------------------------------------------------------------------------
# CIS 2.1 và 2.2 - đọc cassandra.yaml
# ------------------------------------------------------------------------------

def _read_config_value(target_node: str, key: str) -> Tuple[Any, Any]:
    """
    SSH vào node, đọc cassandra.yaml, trả về (giá trị của `key`, dòng gốc).
    Không có dòng `key:` đang hoạt động -> trả về (None, None).
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
        if line.startswith(f"{key}:"):
            value = line.split(":", 1)[1].split("#")[0].strip()
            return value, line.strip()
    return None, None


def _check_setting(
    target_node: str,
    policy: Dict[str, Any],
    control_id: str,
    key: str,
    open_value: str,
    default_expected: str,
    open_reason: str,
) -> Dict[str, Any]:
    """
    Logic chung cho 2.1 và 2.2.
        key              khóa trong cassandra.yaml (authenticator / authorizer)
        open_value       giá trị "mở toang" bị coi là FAIL (AllowAllAuthenticator / AllowAllAuthorizer)
        default_expected giá trị đúng nếu policy không khai báo
        open_reason      lý do ghi vào kết quả khi FAIL

    Kết quả:
        ERROR        : không đọc được cấu hình trên node
        FAIL         : chưa đặt khóa (dùng mặc định "mở toang") hoặc đang là open_value
        PASS         : đúng giá trị policy yêu cầu
        NEEDS_REVIEW : giá trị khác (không phải open_value nhưng cũng không khớp policy)
    """
    start = time.time()
    expected = policy.get("auth", {}).get(key, default_expected)

    status, actual, evidence, reason = "ERROR", None, "", ""
    try:
        value, line = _read_config_value(target_node, key)
    except RuntimeError as exc:
        evidence = str(exc)
        reason = "Không thu thập được cấu hình nên không thể kết luận PASS/FAIL"
    else:
        short_name = (value or "").split(".")[-1]  # chấp nhận cả tên đầy đủ org.apache...X
        if not value or short_name == open_value:
            status = "FAIL"
            actual = value or f"chưa đặt (mặc định {open_value})"
            evidence = line or f"{CONF_PATH}: không có dòng '{key}:' đang hoạt động"
            reason = open_reason
        elif short_name == expected:
            status, actual, evidence = "PASS", value, line
            reason = f"{key} đúng theo policy ({expected})"
        else:
            status, actual, evidence = "NEEDS_REVIEW", value, line
            reason = f"{key} khác policy ({expected}), cần người xem xét"

    return _make_result(control_id, "node", target_node, status, actual,
                        f"{key}: {expected}", evidence, reason, start)


def check_2_1_authentication_enabled(target_node: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    """CIS 2.1: authenticator phải là PasswordAuthenticator."""
    return _check_setting(
        target_node, policy, "2.1", "authenticator",
        open_value="AllowAllAuthenticator",
        default_expected="PasswordAuthenticator",
        open_reason="AllowAllAuthenticator không yêu cầu đăng nhập",
    )


def check_2_2_authorization_enabled(target_node: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    """CIS 2.2: authorizer phải là CassandraAuthorizer."""
    return _check_setting(
        target_node, policy, "2.2", "authorizer",
        open_value="AllowAllAuthorizer",
        default_expected="CassandraAuthorizer",
        open_reason="AllowAllAuthorizer cấp mọi quyền cho mọi role, không có phân quyền",
    )


# ------------------------------------------------------------------------------
# CIS 3.2 - mật khẩu mặc định của role cassandra phải được đổi
# ------------------------------------------------------------------------------

def check_3_2_default_password_changed(target_node: str, policy: Dict[str, Any]) -> Dict[str, Any]:
    """
    CIS 3.2: đăng nhập bằng cassandra/cassandra phải bị từ chối.
        FAIL  : đăng nhập thành công (mật khẩu mặc định còn hiệu lực)
        PASS  : bị từ chối vì sai thông tin đăng nhập (AUTH_FAILED)
        ERROR : mọi trường hợp còn lại (từ chối kết nối, timeout, thiếu driver...)
                Lỗi kết nối không cho ta biết gì về mật khẩu nên không được coi là PASS hay FAIL.
    """
    start = time.time()
    expected = f"Đăng nhập {DEFAULT_ROLE}/*** (mật khẩu mặc định) bị từ chối"
    result = execute_cql(
        "SELECT release_version FROM system.local",
        host=target_node, port=CQL_PORT,
        username=DEFAULT_ROLE, password=DEFAULT_PASSWORD,
    )

    if result["success"]:
        version = result["rows"][0].get("release_version", "?") if result["rows"] else "?"
        return _make_result(
            "3.2", "cluster", target_node, "FAIL",
            f"Đăng nhập {DEFAULT_ROLE}/*** thành công (mật khẩu mặc định còn hiệu lực)", expected,
            f"CQL {target_node}:{CQL_PORT} với role {DEFAULT_ROLE}: kết nối được (Cassandra {version})",
            "Mật khẩu mặc định chưa được đổi. Nếu 2.1 cũng FAIL thì xác thực đang tắt "
            "và mọi thông tin đăng nhập đều vào được.",
            start,
        )

    if result["error_type"] == "AUTH_FAILED":
        return _make_result(
            "3.2", "cluster", target_node, "PASS",
            f"Đăng nhập {DEFAULT_ROLE}/*** bị từ chối", expected,
            f"CQL {target_node}:{CQL_PORT}: AUTH_FAILED ({result['error'][:200]})",
            "Cassandra từ chối mật khẩu mặc định",
            start,
        )

    hint = ""
    if result["error_type"] == "CONNECTION_REFUSED":
        hint = " Gợi ý: rpc_address của node có thể đang là localhost, cần đặt thành IP private."
    elif result["error_type"] == "DRIVER_MISSING":
        hint = " Gợi ý: pip install cassandra-driver"
    return _make_result(
        "3.2", "cluster", target_node, "ERROR", None, expected,
        f"{result['error_type']}: {result['error'][:300]}",
        f"Không kết nối CQL được nên không thể kết luận về mật khẩu.{hint}",
        start,
    )


def run_all_checks(target_node: str, policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Làm xong 3.1 thì thêm vào danh sách này.
    return [
        check_2_1_authentication_enabled(target_node, policy),
        check_2_2_authorization_enabled(target_node, policy),
        check_3_2_default_password_changed(target_node, policy),
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