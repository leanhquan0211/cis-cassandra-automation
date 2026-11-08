"""Read-only node probe, executed with Python 3.10 via SSH stdin.

No role changes, config writes, passwords in argv, or TLS verification bypass.
"""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
import yaml

logging.disable(logging.CRITICAL)

def resource_name(value):
    if value == "<all keyspaces>":
        return "data/all"
    if value == "<all roles>":
        return "roles/all"
    for pattern, prefix in [(r"<keyspace ([A-Za-z_][A-Za-z0-9_]*)>", "data/keyspace/"),
                            (r"<role ([^<>]+)>", "roles/")]:
        match = re.fullmatch(pattern, value)
        if match:
            return prefix + match[1]
    match = re.fullmatch(r"<table ([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)>", value)
    if match:
        return "data/table/" + match[1] + "/" + match[2]
    return "opaque/" + value

def roles(request, config):
    from cassandra.auth import PlainTextAuthProvider
    from cassandra.cluster import Cluster
    from cassandra.policies import WhiteListRoundRobinPolicy
    from cassandra.query import dict_factory
    if config.get("authenticator") != "PasswordAuthenticator" or config.get("authorizer") != "CassandraAuthorizer":
        raise RuntimeError("AUTH_PRECONDITION")
    settings = dict(contact_points=[request["host"]], port=request.get("port", 9042),
        protocol_version=4, connect_timeout=8,
        load_balancing_policy=WhiteListRoundRobinPolicy([request["host"]]),
        auth_provider=PlainTextAuthProvider(username=request["username"], password=request["password"]))
    if config.get("client_encryption_options", {}).get("enabled"):
        tls = request.get("tls", {})
        context = ssl.create_default_context(cafile=tls.get("ca_file"))
        if tls.get("cert_file"):
            context.load_cert_chain(tls["cert_file"], tls["key_file"])
        settings["ssl_context"] = context
    cluster = Cluster(**settings)
    try:
        session = cluster.connect()
        session.row_factory = dict_factory
        def read():
            all_roles = list(session.execute("SELECT role, is_superuser, can_login, member_of FROM system_auth.roles", timeout=15))
            named = {row["role"] for row in session.execute("LIST ROLES", timeout=15)}
            normalized = sorted([{"role": r["role"], "is_superuser": r["is_superuser"], "can_login": r["can_login"],
                                  "member_of": sorted(r["member_of"] or [])} for r in all_roles], key=lambda r:r["role"])
            if named != {r["role"] for r in normalized}:
                raise RuntimeError("INCOMPLETE_ROLE_ENUMERATION")
            if not any(r["role"] == request["username"] and r["is_superuser"] for r in normalized):
                raise RuntimeError("AUDIT_SUPERUSER_REQUIRED_FOR_COMPLETENESS")
            permissions = sorted([{"role": row.get("role",row.get("username")), "resource":resource_name(row["resource"]),
                                   "permission": row["permission"]} for row in session.execute("LIST ALL PERMISSIONS", timeout=15)],
                                 key=lambda r:(r["role"],r["resource"],r["permission"]))
            return {"roles":normalized,"permissions":permissions}
        first, second = read(), read()
        if first != second:
            raise RuntimeError("OBSERVATION_CHANGED_DURING_COLLECTION")
        return dict(first, complete=True, endpoint=request["host"], audit_role=request["username"],
            cassandra_version=session.execute("SELECT release_version FROM system.local",timeout=15).one()["release_version"],
            completeness_basis="authenticated superuser; full LIST/SELECT enumeration; two equal sequential observations",
            evidence="Read-only CQL: system_auth.roles (no hashes), LIST ROLES, LIST ALL PERMISSIONS; endpoint="+request["host"])
    finally:
        cluster.shutdown()

def network(request, config, config_path):
    active = subprocess.check_output(["systemctl","is-active","cassandra"],text=True).strip() == "active"
    pid = int(subprocess.check_output(["systemctl","show","cassandra","--property=MainPID","--value"],text=True))
    environment = dict(part.split("=",1) for part in Path(f"/proc/{pid}/environ").read_bytes().decode().split("\0") if "=" in part)
    args = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
    boot = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines() if line.startswith("btime "))
    # Field 22 after removing parenthesized command name; ticks since boot.
    ticks = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()[19])
    start = boot + ticks/os.sysconf("SC_CLK_TCK")
    overrides = [a.split("=",1)[1] for a in args if a.startswith("-Dcassandra.config=")]
    correct_path = environment.get("CASSANDRA_CONF") == str(config_path.parent)
    correct_override = not overrides or overrides == ["file://"+str(config_path)]
    sockets = []
    for line in subprocess.check_output(["ss","-H","-lnt"],text=True).splitlines():
        address, port = line.split()[3].rsplit(":",1)
        sockets.append({"address":address.strip("[]"),"port":int(port)})
    interfaces = {}
    for interface in json.loads(subprocess.check_output(["ip","-j","address","show"],text=True)):
        interfaces[interface["ifname"]] = [a["local"] for a in interface["addr_info"]]
    keys = ["listen_address","listen_interface","rpc_address","rpc_interface","storage_port","native_transport_port"]
    return {"complete":True,"service_active":active,"config_loaded":correct_path and correct_override and config_path.stat().st_mtime <= start+1,
        "config":{k:config[k] for k in keys if k in config},"sockets":sockets,"interfaces":interfaces,
        "config_sha256":hashlib.sha256(config_path.read_bytes()).hexdigest(),"process_start_epoch":start,
        "evidence":"SSH: active systemd MainPID, process environment/start time, cassandra.yaml SHA256, ss -lnt and ip -j address"}

def main():
    request = json.load(sys.stdin)
    config_path = Path(request.get("config_path", "/etc/cassandra/cassandra.yaml"))
    if str(config_path) != "/etc/cassandra/cassandra.yaml":
        raise RuntimeError("UNAPPROVED_CONFIG_PATH")
    config = yaml.safe_load(config_path.read_text())
    return roles(request, config) if request["kind"] == "roles" else network(request, config, config_path)

if __name__ == "__main__":
    try:
        print(json.dumps({"ok":True,"observation":main()}))
    except Exception as error:
        # Deliberately omit raw error text; credential values must never reach evidence.
        safe_codes = {"AUTH_PRECONDITION","INCOMPLETE_ROLE_ENUMERATION","AUDIT_SUPERUSER_REQUIRED_FOR_COMPLETENESS","OBSERVATION_CHANGED_DURING_COLLECTION","UNAPPROVED_CONFIG_PATH"}
        code = str(error) if isinstance(error,RuntimeError) and str(error) in safe_codes else type(error).__name__
        children = [type(e).__name__ for e in getattr(error,"errors",{}).values()]
        if "AuthenticationFailed" in children or code=="AuthenticationFailed":code="AUTH_FAILED"
        elif code in ("OperationTimedOut","TimeoutError"):code="TIMEOUT"
        elif code=="Unauthorized":code="PERMISSION_DENIED"
        print(json.dumps({"ok":False,"error_type":code}))
        sys.exit(1)
