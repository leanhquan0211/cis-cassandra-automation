"""TV1 evaluators for 1.1–1.6 and 3.4; no node changes are performed.

run_all_checks accepts injected collector facts for fixtures. A call without facts
returns ERROR for missing data; it never silently audits the controller laptop.
"""

from datetime import datetime, timezone
import json
import math
import re
import time
import uuid

CONTROLS = {"1.1": "M", "1.2": "A", "1.3": "A", "1.4": "A",
            "1.5": "A", "1.6": "M", "3.4": "A"}
JAVA_VERSION = "1.8.0_472"
CASSANDRA_VERSION = "4.0.19"


class MissingPolicy(Exception):
    pass


def redact(value):
    if isinstance(value, dict):
        return {str(k): "***" if re.search(r"password|secret|token|private.?key|credential", str(k), re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                       "***", value, flags=re.S)
        return re.sub(r'''(?i)(password|secret|token|credential)(\s*[:=]\s*)("[^"]*"|'[^']*'|[^\s,;]+)''',
                      r"\1\2***", value)
    return value


def result(control, target, run_id, policy_ref, status, actual, expected, reason, duration_ms=0):
    return redact({"schema_version": "1.0", "run_id": run_id,
                   "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                   "control_id": control, "owner": "TV1", "cis_status": CONTROLS[control],
                   "scope": "node", "target": target, "status": status,
                   "actual": actual, "expected": expected,
                   "evidence": json.dumps(redact(actual), sort_keys=True, allow_nan=False),
                   "policy_ref": policy_ref, "reason": reason, "duration_ms": duration_ms})


def _fact(facts, name):
    entry = facts.get(name)
    if not isinstance(entry, dict) or entry.get("ok") is not True or not isinstance(entry.get("data"), dict):
        raise ValueError("Missing, unreadable or invalid collector data")
    return entry["data"]


def _required(policy, key):
    if key not in policy or policy[key] is None:
        raise MissingPolicy("Policy does not define " + key)
    return policy[key]


def _integer(value):
    if type(value) is not int or value < 0:
        raise ValueError("Invalid numeric identity")
    return value


def _bool(value):
    if type(value) is not bool:
        raise ValueError("Invalid boolean")
    return value


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ValueError("Invalid version")
    return tuple(map(int, value.split(".")))


def _evaluate(control, facts, policy):
    if not isinstance(facts, dict) or not isinstance(policy, dict):
        raise ValueError("Facts and platform policy must be objects")
    if control == "1.1":
        data = _fact(facts, "account")
        if not _bool(data["exists"]):
            return False, data, "Dedicated account and group", "Account or group is absent"
        user, group = _required(policy, "dedicated_user"), _required(policy, "dedicated_group")
        forbidden = policy.get("disallowed_users", ["root"])
        if not isinstance(forbidden, list):
            raise ValueError("Invalid disallowed user policy")
        good = (_integer(data["uid"]) > 0 and _integer(data["group_gid"]) > 0 and
                _integer(data["gid"]) == data["group_gid"] and
                data["user"] == user and data["group"] == group and user not in forbidden)
        return good, data, {"user": user, "group": group}, "Dedicated non-root account and primary group"
    if control == "1.2":
        data = _fact(facts, "java")
        if policy.get("required_java_version", "1.8.0") not in {"1.8.0", JAVA_VERSION}:
            raise ValueError("Policy conflicts with pinned Java baseline")
        if not isinstance(data["version"], str) or not isinstance(data["vendor"], str):
            raise ValueError("Invalid Java version data")
        good = data["version"] == JAVA_VERSION and data["vendor"] == "Temurin"
        return good, data, "Temurin " + JAVA_VERSION, "Pinned lab baseline; does not establish latest upstream Java"
    if control == "1.3":
        data = _fact(facts, "python")
        version = _version(data["version"])
        minimum = _required(policy, "minimum_python_version")
        good = version >= _version(minimum)
        return good, data, {"minimum_python_version": minimum}, "Python version compared with explicit policy minimum"
    if control == "1.4":
        data = _fact(facts, "cassandra")
        if policy.get("required_cassandra_major", "4.0") != "4.0":
            raise ValueError("Policy conflicts with pinned Cassandra baseline")
        if not isinstance(data["version"], str):
            raise ValueError("Invalid Cassandra version data")
        return data["version"] == CASSANDRA_VERSION, data, CASSANDRA_VERSION, "Pinned lab baseline; does not establish latest upstream Cassandra"
    if control in {"1.5", "3.4"}:
        data = _fact(facts, "service")
        expected = "Active Cassandra JVM with effective non-root UID"
        if not _bool(data["active"]) or _integer(data["pid"]) == 0:
            return False, data, expected, "Cassandra service has no active process"
        good = _integer(data["uid"]) > 0 and _bool(data["is_cassandra"])
        if control == "3.4":
            account = _fact(facts, "account")
            user, group = _required(policy, "dedicated_user"), _required(policy, "dedicated_group")
            if not _bool(account["exists"]):
                return False, data, "Dedicated account", "Dedicated account is absent"
            good = (good and data["unit_user"] == user and data["unit_group"] == group and
                    user not in policy.get("disallowed_users", ["root"]) and
                    data["uid"] == _integer(account["uid"]) and
                    _integer(data["gid"]) == _integer(account["group_gid"]) and
                    account["user"] == user and account["group"] == group and
                    _integer(account["gid"]) == account["group_gid"])
            expected = {"service_user": user, "service_group": group, "runtime_identity_matches": True}
        return good, data, expected, "Runtime process identity checked with systemd and /proc"
    if control == "1.6":
        data = _fact(facts, "clock")
        synchronized = _bool(data["synchronized"])
        clock = _required(policy, "clock_sync")
        if not isinstance(clock, dict):
            raise ValueError("Invalid clock policy")
        if _required(clock, "enabled") is not True:
            raise MissingPolicy("Clock synchronization policy must explicitly require synchronization")
        maximum = _required(clock, "max_abs_offset_ms")
        if type(maximum) not in (int, float) or not math.isfinite(maximum) or maximum < 0:
            raise ValueError("Invalid clock threshold")
        if not synchronized:
            return False, data, clock, "Clock is not synchronized"
        offset = data.get("offset_ms")
        if offset is None:
            raise MissingPolicy("Clock synchronized but offset evidence is unavailable; manual review required")
        if type(offset) not in (int, float) or not math.isfinite(offset):
            raise ValueError("Invalid clock offset")
        services = _required(clock, "service_names")
        if not isinstance(services, list):
            raise ValueError("Invalid clock services policy")
        source = data["source"]
        return abs(offset) <= maximum and source in services, data, clock, "Measured offset and synchronization source compared with policy"
    raise ValueError("Unknown control")


def run_all_checks(target_node, policy, *, facts=None, run_id=None, policy_ref="policies/lab.yml"):
    facts = {} if facts is None else facts
    run_id = run_id or "run-" + uuid.uuid4().hex
    platform = policy.get("platform", {})
    results = []
    for control in CONTROLS:
        start = time.perf_counter()
        try:
            good, actual, expected, reason = _evaluate(control, facts, platform)
            status = "PASS" if good else "FAIL"
        except MissingPolicy as exc:
            probe_name = {"1.1": "account", "1.2": "java", "1.3": "python", "1.4": "cassandra",
                          "1.5": "service", "1.6": "clock", "3.4": "service"}[control]
            status, actual, expected, reason = "NEEDS_REVIEW", _fact(facts, probe_name), "Explicit platform policy and evidence", str(exc)
        except (KeyError, TypeError, ValueError, OverflowError):
            status, actual, expected, reason = "ERROR", None, "Readable and well-formed node evidence", "Collector data or policy is missing, unreadable or malformed"
        results.append(result(control, target_node, run_id, policy_ref, status, actual, expected, reason,
                              round((time.perf_counter() - start) * 1000, 3)))
    return results
