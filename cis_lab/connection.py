"""
cis_lab.connection
Owner: TV2 (Đoàn Thanh Đệ)
Role: Helper kết nối CQL trên node Cassandra bằng cassandra-driver (kết nối trực tiếp).
Support: TV4 hỗ trợ tham số TLS/SSL (truststore, certfile).

Yêu cầu:
    pip install cassandra-driver
    Máy chạy code phải kết nối được tới <host>:<port> của node (cổng 9042).
    Cassandra mặc định chỉ lắng nghe CQL ở localhost, nên node phải đặt rpc_address
    thành IP private (khóa này thuộc namespace của TV3).

Giá trị error_type:
    AUTH_FAILED, TIMEOUT, CONNECTION_REFUSED, INVALID_QUERY   (theo bản khung ban đầu)
    UNAUTHORIZED     tài khoản đã đăng nhập nhưng không đủ quyền chạy câu lệnh
    TLS_ERROR        lỗi TLS/SSL (cấu hình ssl_context sai hoặc bắt tay TLS thất bại)
    CONNECTION_ERROR lỗi mạng khác (không có route, kết nối bị reset...)
    DRIVER_MISSING   chưa cài cassandra-driver
    UNKNOWN          lỗi chưa phân loại

Thử nhanh từ dòng lệnh:
    CASSANDRA_USER=cassandra CASSANDRA_PASSWORD=... \\
        python -m cis_lab.connection 192.168.56.139 "SELECT release_version FROM system.local"
"""

import collections.abc
import ssl
from typing import Any, Dict, Optional

try:
    from cassandra import AuthenticationFailed, InvalidRequest, OperationTimedOut, Unauthorized
    from cassandra.auth import PlainTextAuthProvider
    from cassandra.cluster import Cluster, NoHostAvailable
    from cassandra.connection import ConnectionException
    from cassandra.policies import WhiteListRoundRobinPolicy
    from cassandra.protocol import SyntaxException
    from cassandra.query import dict_factory

    _DRIVER_ERROR = None
except ImportError as _exc:  # chưa cài cassandra-driver
    _DRIVER_ERROR = str(_exc)

DEFAULT_TIMEOUT_S = 10.0


def _mask(text: str, secret: Optional[str], username: Optional[str] = None) -> str:
    """
    Che mật khẩu nếu nó lỡ xuất hiện trong thông báo lỗi (phòng hờ, thực tế driver
    không in mật khẩu). Bỏ qua mật khẩu ngắn (< 6 ký tự) hoặc trùng tên user, vì thay
    chúng ở mọi chỗ sẽ làm hỏng thông báo (ví dụ mật khẩu mặc định "cassandra" trùng
    tên role "cassandra"; mật khẩu mặc định này vốn là thông tin công khai).
    """
    if not secret or len(secret) < 6 or secret == username:
        return text
    return text.replace(secret, "***")


def _to_plain(value: Any) -> Any:
    """
    Đổi giá trị của driver sang kiểu Python/JSON thông thường:
    set (ví dụ cột member_of) -> list, map -> dict, UUID/datetime... -> str.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, collections.abc.Mapping):
        return {str(k): _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)) or (
        isinstance(value, collections.abc.Iterable) and not isinstance(value, (bytes, bytearray))
    ):
        items = [_to_plain(v) for v in value]
        try:
            return sorted(items) if isinstance(value, (set, frozenset)) or type(value).__name__ == "SortedSet" else items
        except TypeError:
            return items
    return str(value)


def _build_ssl_context(cfg: Dict[str, Any]) -> "ssl.SSLContext":
    """
    Tạo SSLContext từ dict cấu hình. Các khóa (đều tùy chọn):
        truststore  đường dẫn file CA dạng PEM (không có thì dùng CA mặc định của hệ điều hành)
        certfile    chứng chỉ client dạng PEM (khi node bật require_client_auth)
        keyfile     private key của certfile (nếu không nằm chung file)
    Luôn xác minh chứng chỉ server và tên host, tối thiểu TLS 1.2. Không có tùy chọn
    nào để tắt xác minh (AGENTS.md mục 5), và không bao giờ tự lùi về kết nối không mã hóa.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # mặc định: CERT_REQUIRED + check_hostname=True
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if cfg.get("truststore"):
        ctx.load_verify_locations(cafile=cfg["truststore"])
    else:
        ctx.load_default_certs()
    if cfg.get("certfile"):
        ctx.load_cert_chain(cfg["certfile"], cfg.get("keyfile"))
    return ctx


def _classify(exc: BaseException) -> str:
    """Xếp lỗi của driver vào một error_type. NoHostAvailable gói lỗi thật bên trong .errors."""
    candidates = list(exc.errors.values()) if isinstance(exc, NoHostAvailable) else []
    candidates.append(exc)

    def has(*types: type) -> bool:
        return any(isinstance(e, types) for e in candidates)

    if has(AuthenticationFailed):
        return "AUTH_FAILED"
    if has(ssl.SSLError):
        return "TLS_ERROR"
    if has(Unauthorized):
        return "UNAUTHORIZED"
    if has(InvalidRequest, SyntaxException):
        return "INVALID_QUERY"
    if has(ConnectionRefusedError):
        return "CONNECTION_REFUSED"
    if has(OperationTimedOut, TimeoutError) or any("timed out" in str(e).lower() for e in candidates):
        return "TIMEOUT"
    if has(OSError, ConnectionException):
        return "CONNECTION_ERROR"
    return "UNKNOWN"


def _failure(error_type: str, error: str) -> Dict[str, Any]:
    return {"success": False, "rows": [], "error": error, "error_type": error_type}


def execute_cql(
    cql: str,
    host: str = "127.0.0.1",
    port: int = 9042,
    username: Optional[str] = None,
    password: Optional[str] = None,
    ssl_context: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    """
    Thực thi MỘT câu CQL trên node mục tiêu.

    Args:
        ssl_context: dict cấu hình TLS (xem _build_ssl_context). None = không dùng TLS.
        timeout:     giây, áp dụng cho kết nối và cho câu lệnh.

    Returns:
        dict luôn có đủ 4 khóa:
            success    : bool
            rows       : list[dict] (rỗng nếu lỗi hoặc câu lệnh không trả dòng nào)
            error      : str, thông báo lỗi đã che mật khẩu ("" nếu thành công)
            error_type : str, xem danh sách ở đầu file ("" nếu thành công)
    """
    if _DRIVER_ERROR:
        return _failure("DRIVER_MISSING", f"Chưa cài cassandra-driver (pip install cassandra-driver): {_DRIVER_ERROR}")

    try:
        ctx = _build_ssl_context(ssl_context) if ssl_context is not None else None
    except (OSError, ssl.SSLError, ValueError) as exc:
        return _failure("TLS_ERROR", _mask(f"Cấu hình TLS không hợp lệ: {exc}", password, username))

    auth = PlainTextAuthProvider(username, password) if username is not None else None
    cluster = Cluster(
        contact_points=[host],
        port=port,
        auth_provider=auth,
        ssl_context=ctx,
        protocol_version=4,                       # Cassandra 4.0 hỗ trợ v4, tránh bước dò phiên bản
        connect_timeout=timeout,
        control_connection_timeout=timeout,
        load_balancing_policy=WhiteListRoundRobinPolicy([host]),  # chỉ nói chuyện với đúng node này
        schema_metadata_enabled=False,            # không cần metadata, kết nối nhanh hơn
        token_metadata_enabled=False,
    )
    try:
        session = cluster.connect()
        session.default_timeout = timeout
        session.row_factory = dict_factory
        rows = [_to_plain(row) for row in session.execute(cql)]
        return {"success": True, "rows": rows, "error": "", "error_type": ""}
    except Exception as exc:  # driver ném nhiều loại lỗi, ta phân loại ở _classify
        return _failure(_classify(exc), _mask(str(exc), password, username))
    finally:
        cluster.shutdown()


if __name__ == "__main__":
    import json
    import os
    import sys

    if len(sys.argv) < 3:
        sys.exit('Cách dùng: [CASSANDRA_USER=.. CASSANDRA_PASSWORD=..] python -m cis_lab.connection <host> "<CQL>"')
    result = execute_cql(
        sys.argv[2],
        host=sys.argv[1],
        username=os.environ.get("CASSANDRA_USER"),
        password=os.environ.get("CASSANDRA_PASSWORD"),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if result["success"] else 1)