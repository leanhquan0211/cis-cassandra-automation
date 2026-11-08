"""TV1: strict, non-mutating namespace merge and offline YAML renderer."""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile

import yaml

NAMESPACE_OWNERSHIP = {
    **dict.fromkeys(("cluster_name", "seed_provider", "data_file_directories",
                     "commitlog_directory", "saved_caches_directory"), "TV1"),
    **dict.fromkeys(("authenticator", "authorizer", "role_manager"), "TV2"),
    **dict.fromkeys(("listen_address", "listen_interface", "network_authorizer",
                     "rpc_address"), "TV3"),
    **dict.fromkeys(("audit_logging_options", "server_encryption_options",
                     "client_encryption_options"), "TV4"),
}


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently accepting the last value."""


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result:
            raise ValueError("YAML mapping keys must be unique strings")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_mapping(path):
    with Path(path).open(encoding="utf-8") as handle:
        value = yaml.load(handle, Loader=UniqueKeyLoader)
    if not isinstance(value, dict):
        raise ValueError("Expected a YAML/JSON object")
    json.dumps(value, allow_nan=False)
    return value


def merge_cassandra_yaml(base_yaml, module_updates, module_owner):
    if module_owner not in {"TV1", "TV2", "TV3", "TV4"}:
        raise PermissionError("Unknown module owner")
    if not isinstance(base_yaml, dict) or not isinstance(module_updates, dict):
        raise ValueError("Base and updates must be dictionaries")
    for key in module_updates:
        if NAMESPACE_OWNERSHIP.get(key) != module_owner:
            raise PermissionError(f"{module_owner} cannot update key {key!r}")
    result = deepcopy(base_yaml)
    for key, value in module_updates.items():
        if value is None:
            raise ValueError(f"Null update is not allowed: {key}")
        result[key] = deepcopy(value)
    if "listen_address" in result and "listen_interface" in result:
        raise ValueError("listen_address and listen_interface are mutually exclusive")
    return result


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if (path.is_file() and not path.is_symlink() and path.stat().st_mode & 0o777 == 0o600
            and path.read_text(encoding="utf-8") == content):
        return
    fd, name = tempfile.mkstemp(prefix=".cis-lab-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render an offline Cassandra config candidate")
    parser.add_argument("--base", required=True)
    parser.add_argument("--updates", required=True, help="Mapping TV1..TV4 -> owned updates")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    base, updates, out = map(Path, (args.base, args.updates, args.out))
    if out.resolve() in {base.resolve(), updates.resolve()} or out.resolve().is_relative_to(Path('/etc')):
        parser.error("Output must be a separate offline candidate, outside /etc")
    try:
        result = load_mapping(base)
        for owner, values in load_mapping(updates).items():
            result = merge_cassandra_yaml(result, values, owner)
        atomic_write(out, yaml.safe_dump(result, sort_keys=False))
    except (OSError, ValueError, PermissionError, TypeError, yaml.YAMLError):
        parser.exit(2, "Render rejected: unreadable input or invalid namespace/YAML; no candidate written\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
