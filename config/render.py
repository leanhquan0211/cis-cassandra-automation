"""
config.render
Owner: TV1 (Bùi Cao Minh Quân)
Role: Ghép các cấu hình mong muốn (desired_config) theo namespace được phân công,
      tránh trường hợp ghi đè khóa của module khác trong cassandra.yaml.
"""

from typing import Dict, Any

NAMESPACE_OWNERSHIP = {
    "cluster_name": "TV1",
    "seed_provider": "TV1",
    "data_file_directories": "TV1",
    "commitlog_directory": "TV1",
    "saved_caches_directory": "TV1",
    "authenticator": "TV2",
    "authorizer": "TV2",
    "role_manager": "TV2",
    "listen_address": "TV3",
    "listen_interface": "TV3",
    "network_authorizer": "TV3",
    "rpc_address": "TV3",
    "audit_logging_options": "TV4",
    "server_encryption_options": "TV4",
    "client_encryption_options": "TV4",
}

def merge_cassandra_yaml(base_yaml: Dict[str, Any], module_updates: Dict[str, Any], module_owner: str) -> Dict[str, Any]:
    """
    Hợp nhất cấu hình vào file cassandra.yaml có kiểm tra quyền sở hữu key.
    Từ chối nếu module_owner cố tình ghi đè vào key của thành viên khác.
    """
    result = dict(base_yaml)
    for key, value in module_updates.items():
        expected_owner = NAMESPACE_OWNERSHIP.get(key)
        if expected_owner and expected_owner != module_owner:
            raise PermissionError(f"Xung đột cấu hình: {module_owner} không có quyền sửa key '{key}' (thuộc quyền {expected_owner})")
        result[key] = value
    return result
