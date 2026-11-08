"""TV3 shared contracts. Người thực hiện: Doan Van Tai."""
from datetime import datetime, timezone
from pathlib import Path
import copy
import json
import math
import re

CONTROLS = {
    **{f"1.{i}": ("TV1", "M" if i in (1, 6) else "A") for i in range(1, 7)},
    "2.1": ("TV2", "A"), "2.2": ("TV2", "A"),
    "3.1": ("TV2", "A"), "3.2": ("TV2", "A"), "3.3": ("TV3", "M"),
    "3.4": ("TV1", "A"), **{f"3.{i}": ("TV3", "M") for i in range(5, 9)},
    "4.1": ("TV4", "A"), "4.2": ("TV4", "M"), "5.1": ("TV4", "A"), "5.2": ("TV4", "A"),
}
STATUSES = ("PASS", "FAIL", "NEEDS_REVIEW", "ERROR", "NOT_IMPLEMENTED", "NOT_APPLICABLE")
ROOT = Path(__file__).resolve().parents[2]
SECRET_KEYS = re.compile(r"password|passwd|secret|credential|private.key|salted_hash|access.token", re.I)

def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def redact(value):
    if isinstance(value, dict):
        return {str(k): "***" if SECRET_KEYS.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "***", value, flags=re.S)
        return re.sub(r"(?i)((?:password|passwd|secret|token)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)", r"\1***", value)
    return value

def result(control, target, status, actual, expected, reason, *, run_id, policy_ref, evidence, duration_ms=0.0):
    owner, cis = CONTROLS[control]
    return redact({"schema_version": "1.0", "run_id": run_id, "timestamp_utc": utc_now(),
        "control_id": control, "owner": owner, "cis_status": cis,
        "scope": "cluster" if control in ("3.3","3.6","3.7","3.8","5.1") else "node", "target": target,
        "status": status, "actual": actual, "expected": expected, "reason": reason,
        "policy_ref": policy_ref, "evidence": evidence, "duration_ms": round(duration_ms, 3)})

def validate_results(results, schema_path=None):
    from jsonschema import Draft7Validator, FormatChecker
    if not isinstance(results, list):
        raise ValueError("Results must be a JSON array")
    schema = json.loads(Path(schema_path or ROOT / "schemas/results.json").read_text())
    Draft7Validator.check_schema(schema)
    checker = FormatChecker()
    @checker.checks("date-time", raises=(ValueError, TypeError))
    def date_time(value):
        return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",value)) and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    validator = Draft7Validator(schema, format_checker=checker)
    seen = set()
    for row in results:
        validator.validate(row)
        if (row["owner"], row["cis_status"]) != CONTROLS[row["control_id"]]:
            raise ValueError("Control ownership/CIS label mismatch")
        if row['control_id'] in ('3.3','3.5','3.6','3.7','3.8'):
            expected_scope='node' if row['control_id']=='3.5' else 'cluster'
            if row['scope']!=expected_scope:raise ValueError('TV3 control scope mismatch')
        if not math.isfinite(row["duration_ms"]):
            raise ValueError("Non-finite duration")
        if datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")).utcoffset().total_seconds() != 0:
            raise ValueError("timestamp_utc must be UTC")
        key = (row["run_id"], row["control_id"], row["scope"], row["target"])
        if key in seen:
            raise ValueError("Duplicate control/scope/target within one run")
        seen.add(key)
    return copy.deepcopy(results)
