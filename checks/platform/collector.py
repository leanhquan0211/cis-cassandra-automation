"""TV1 read-only node collector; standalone stdlib source runs via SSH stdin.

Each probe produces {ok: bool, data: object} or {ok: false, error: TYPE}.
Raw stderr, environment and process arguments never leave the node.
"""

import argparse
import base64
import grp
import json
import os
from pathlib import Path
import pwd
import re
import shlex
import subprocess


class ProbeError(Exception):
    pass


def command(argv, timeout=15, env_overrides=None):
    env = dict(os.environ, LC_ALL="C", LANG="C", **(env_overrides or {}))
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    if proc.returncode:
        raise ProbeError("COMMAND_FAILED")
    return proc.stdout + proc.stderr


def probe(function):
    try:
        return {"ok": True, "data": function()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "TIMEOUT"}
    except (OSError, ValueError, KeyError, ProbeError) as exc:
        return {"ok": False, "error": str(exc) if isinstance(exc, ProbeError) else type(exc).__name__}


def os_facts():
    values = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed = shlex.split(value)
            values[key] = parsed[0] if parsed else ""
    if not values["ID"] or not values["VERSION_ID"]:
        raise ProbeError("UNPARSEABLE_OS_RELEASE")
    return {"id": values["ID"], "version_id": values["VERSION_ID"]}


def account_facts(user, group):
    try:
        account = pwd.getpwnam(user)
        team = grp.getgrnam(group)
    except KeyError:
        return {"exists": False}
    return {"exists": True, "user": account.pw_name, "uid": account.pw_uid,
            "gid": account.pw_gid, "group": team.gr_name, "group_gid": team.gr_gid,
            "shell": account.pw_shell}


def service_facts(unit):
    text = command(["systemctl", "show", unit, "--no-pager",
                    "--property=LoadState,ActiveState,User,Group,MainPID"])
    props = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    if props.get("LoadState") in {"not-found", "masked"}:
        return {"active": False, "unit_user": "", "unit_group": "", "pid": 0}
    if props.get("LoadState") != "loaded":
        raise ProbeError("UNPARSEABLE_OR_BROKEN_SYSTEMD_UNIT")
    data = {"active": props["ActiveState"] == "active", "unit_user": props["User"],
            "unit_group": props["Group"], "pid": int(props["MainPID"])}
    if data["active"] and data["pid"] > 0:
        root = Path("/proc") / str(data["pid"])
        status = dict(line.split(":", 1) for line in (root / "status").read_text().splitlines() if ":" in line)
        data.update(uid=int(status["Uid"].split()[1]), gid=int(status["Gid"].split()[1]),
                    exe=os.readlink(root / "exe"),
                    is_cassandra=b"org.apache.cassandra.service.CassandraDaemon" in
                    (root / "cmdline").read_bytes().split(b"\0"))
    return data


def java_facts(executable):
    output = command([executable, "-version"])
    match = re.search(r'version "([^"]+)"', output)
    if not match:
        raise ProbeError("UNPARSEABLE_JAVA_VERSION")
    return {"version": match[1], "vendor": "Temurin" if "Temurin" in output else "other",
            "executable": executable}


def python_facts(executable):
    output = command([executable, "--version"])
    match = re.fullmatch(r"Python (\d+\.\d+\.\d+)\s*", output)
    if not match:
        raise ProbeError("UNPARSEABLE_PYTHON_VERSION")
    return {"version": match[1]}


def cassandra_facts(nodetool, java_home="/opt/temurin8"):
    output = command([nodetool, "version"], env_overrides={"JAVA_HOME": java_home})
    match = re.fullmatch(r"ReleaseVersion:\s*(\S+)\s*", output)
    if not match:
        raise ProbeError("UNPARSEABLE_CASSANDRA_VERSION")
    return {"version": match[1], "source": "nodetool version"}


def clock_facts():
    try:
        output = command(["chronyc", "tracking"])
    except FileNotFoundError:
        output = command(["timedatectl", "show", "--property=NTPSynchronized", "--value"])
        if output.strip() not in {"yes", "no"}:
            raise ProbeError("UNPARSEABLE_CLOCK_STATE")
        return {"synchronized": output.strip() == "yes", "offset_ms": None,
                "source": "timedatectl"}
    fields = dict((k.strip(), v.strip()) for k, v in
                  (line.split(":", 1) for line in output.splitlines() if ":" in line))
    offset = re.fullmatch(r"([0-9.]+) seconds (fast|slow) of NTP time", fields["System time"])
    if not offset:
        raise ProbeError("UNPARSEABLE_CLOCK_OFFSET")
    return {"synchronized": fields["Leap status"] == "Normal" and int(fields["Stratum"]) > 0,
            "offset_ms": float(offset[1]) * 1000, "source": "chrony"}


def collect(config):
    service = probe(lambda: service_facts(config.get("service", "cassandra.service")))
    # Assess the JVM running Cassandra, not whichever java the SSH login resolves.
    executable = (service.get("data", {}).get("exe") or
                  config.get("java", "/opt/temurin8/bin/java"))
    return {"os": probe(os_facts),
            "account": probe(lambda: account_facts(config.get("user", "cassandra"),
                                                  config.get("group", "cassandra"))),
            "service": service, "java": probe(lambda: java_facts(executable)),
            "python": probe(lambda: python_facts(config.get("python", "/usr/bin/python3"))),
            "cassandra": probe(lambda: cassandra_facts(config.get("nodetool", "/opt/cassandra/bin/nodetool"),
                                                       str(Path(executable).parent.parent))),
            "clock": probe(clock_facts)}


def collect_ssh(host, config, *, user, port=22, identity=None, timeout=120, become=False):
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1", "-T", "-p", str(port)]
    if identity:
        argv += ["-i", str(Path(identity).expanduser())]
    encoded = base64.b64encode(json.dumps(config).encode()).decode()
    remote = ("sudo -n -- " if become else "") + "python3 - --config-b64 " + shlex.quote(encoded)
    argv += ["--", f"{user}@{host}", remote]
    try:
        proc = subprocess.run(argv, input=Path(__file__).read_text(), capture_output=True,
                              text=True, timeout=timeout)
        if proc.returncode:
            raise ProbeError("SSH_OR_REMOTE_COMMAND_FAILED")
        result = json.loads(proc.stdout)
        if not isinstance(result, dict):
            raise ValueError("Invalid collector response")
        return result
    except (OSError, ValueError, subprocess.TimeoutExpired, ProbeError) as exc:
        code = str(exc) if isinstance(exc, ProbeError) else type(exc).__name__
        return {name: {"ok": False, "error": code}
                for name in ("os", "account", "service", "java", "python", "cassandra", "clock")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-b64", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(json.loads(base64.b64decode(args.config_b64))), allow_nan=False))
