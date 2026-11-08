"""TV1 runner. Entry point: python -m cis_lab.cli (no __main__ outside ownership).

Exit codes: 0 all PASS; 1 FAIL; 2 execution/input error; 3 incomplete/review.
Fixtures never initiate SSH or invoke modules without a fixture injection contract.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import re
import sys
import uuid

import jsonschema
import yaml

from checks.platform.checker import redact, run_all_checks
from checks.platform.collector import collect_ssh
from config.render import atomic_write, load_mapping

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = {
    "platform": ("TV1", {"1.1": "M", "1.2": "A", "1.3": "A", "1.4": "A", "1.5": "A", "1.6": "M", "3.4": "A"}),
    "auth": ("TV2", {"2.1": "A", "2.2": "A", "3.1": "A", "3.2": "A"}),
    "access": ("TV3", {"3.3": "M", "3.5": "M", "3.6": "M", "3.7": "M", "3.8": "M"}),
    "observability_tls": ("TV4", {"4.1": "A", "4.2": "M", "5.1": "A", "5.2": "A"}),
}
CONTROL_METADATA = {control: (module, owner, label)
                    for module, (owner, controls) in REGISTRY.items()
                    for control, label in controls.items()}


class RunnerError(ValueError):
    """An operator-facing, fixed diagnostic containing no raw node/input values."""


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dump(path, data):
    atomic_write(path, json.dumps(redact(data), indent=2, allow_nan=False) + "\n")


def _decode_json(content):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("Non-finite JSON number")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite JSON number")
        return number
    return json.loads(content, object_pairs_hook=unique,
                      parse_constant=invalid, parse_float=finite_float)


def json_snapshot(path):
    """Validate and fingerprint the same bytes, without a second input read."""
    raw = Path(path).read_bytes()
    return _decode_json(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json_snapshot(path)[0]


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def distinct_output(output, *inputs):
    destination = Path(output)
    for source in inputs:
        original = Path(source)
        if destination.resolve() == original.resolve() or (
                destination.exists() and original.exists() and destination.samefile(original)):
            raise RunnerError("Output must not overwrite an input or its alias")


def string_list(value, *, empty=False):
    if (not isinstance(value, list) or (not value and not empty) or
            any(not isinstance(item, str) or not item.strip() for item in value) or
            len(value) != len(set(value))):
        raise RunnerError("Expected unique nonempty strings in a list")
    return set(value)


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        raise RunnerError("Timestamp must include an explicit timezone")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RunnerError("Invalid calendar timestamp") from None


def selected_modules(value):
    modules = value.split(",")
    if not modules or len(modules) != len(set(modules)) or any(m not in REGISTRY for m in modules):
        raise RunnerError("Select each known checker module at most once")
    return modules


def validate_results(results):
    schema = read_json(ROOT / "schemas/results.json")
    validator = jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker())
    if not isinstance(results, list) or not results:
        raise ValueError("Results must be a nonempty list")
    seen = set()
    for row in results:
        validator.validate(row)
        # Some distributions omit jsonschema's optional RFC3339 dependency.
        stamp = row["timestamp_utc"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", stamp):
            raise ValueError("Expected UTC RFC3339 timestamp")
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if not math.isfinite(row["duration_ms"]) or row["duration_ms"] < 0:
            raise ValueError("Invalid duration")
        if not row["run_id"] or not row["target"]:
            raise ValueError("Empty result context")
        metadata = CONTROL_METADATA.get(row["control_id"])
        if metadata is None or (row["owner"], row["cis_status"]) != metadata[1:]:
            raise RunnerError("Result owner or CIS label does not match assigned control")
        if row["scope"] != ("cluster" if row["control_id"] == "5.1" else "node"):
            raise RunnerError("Result scope does not match assigned control")
        key = row["target"], row["control_id"]
        if key in seen:
            raise ValueError("Duplicate control for target")
        seen.add(key)
    json.dumps(results, allow_nan=False)
    return results


def inventory_nodes(path, limit=None):
    if limit is not None and not limit.strip():
        raise RunnerError("An explicit --limit must select at least one host")
    inventory = load_mapping(path)
    nodes = {}

    def walk(group, inherited, selected=False):
        if not isinstance(group, dict):
            raise ValueError("Invalid inventory group")
        groupvars = group.get("vars", {})
        children = group.get("children", {})
        if not isinstance(groupvars, dict) or not isinstance(children, dict):
            raise RunnerError("Inventory vars and children must be mappings")
        variables = {**inherited, **groupvars}
        if selected:
            hosts = group.get("hosts") or {}
            if not isinstance(hosts, dict):
                raise ValueError("Hosts must be a mapping")
            for name, hostvars in hosts.items():
                if hostvars is not None and not isinstance(hostvars, dict):
                    raise RunnerError("Inventory host variables must be mappings")
                if name in nodes:
                    raise ValueError("Duplicate inventory host")
                nodes[name] = {**variables, **(hostvars or {})}
        for name, child in children.items():
            walk(child, variables, selected or name == "cassandra_nodes")

    walk(inventory.get("all", inventory), {})
    if limit:
        wanted = set(limit.split(","))
        if not wanted <= nodes.keys():
            raise ValueError("Unknown --limit host")
        nodes = {name: value for name, value in nodes.items() if name in wanted}
    if not nodes:
        raise ValueError("No cassandra_nodes in inventory")
    for name, values in nodes.items():
        for value in (name, values.get("ansible_host", name), values.get("ansible_user", "")):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]*", value):
                raise ValueError("Unsafe or missing SSH host/user")
        port = values.get("ansible_port", 22)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid SSH port")
        if values.get("ansible_connection", "ssh") != "ssh":
            raise ValueError("Node collector only supports explicit SSH targets")
    return nodes


def collect_nodes(args, policy):
    if args.fixture is not None and not args.fixture.strip():
        raise RunnerError("An explicit --fixture requires a readable file path")
    nodes = inventory_nodes(args.inventory, args.limit)
    fixture = read_json(args.fixture) if args.fixture else None
    if args.fixture and (not isinstance(fixture, dict) or not isinstance(fixture.get("nodes"), dict)):
        raise ValueError("Fixture must contain nodes mapping")
    collected = {}
    platform = policy.get("platform", {})
    if not isinstance(platform, dict):
        raise ValueError("Platform policy must be a mapping")
    # Validate the entire selection before the first SSH attempt. An invalid last
    # node must not leave a partially connected run.
    if args.fixture:
        if any(not isinstance(fixture["nodes"].get(name), dict) for name in nodes):
            raise RunnerError("Fixture missing selected node facts")
        return {name: fixture["nodes"][name] for name in nodes}
    configurations = {}
    for name, values in nodes.items():
        config = {"user": platform.get("dedicated_user", "cassandra"),
                  "group": platform.get("dedicated_group", "cassandra"),
                  "java": values.get("platform_java", "/opt/temurin8/bin/java"),
                  "nodetool": values.get("cassandra_install_dir", "/opt/cassandra") + "/bin/nodetool",
                  "python": values.get("ansible_python_interpreter", "/usr/bin/python3")}
        if any(not isinstance(value, str) or not value.strip() for value in config.values()):
            raise RunnerError("Collector paths and account names must be strings")
        identity = values.get("ansible_ssh_private_key_file")
        if identity is not None and not isinstance(identity, str):
            raise RunnerError("SSH identity path must be a string")
        configurations[name] = config
    for name, values in nodes.items():
        collected[name] = collect_ssh(values.get("ansible_host", name), configurations[name],
                                         user=values["ansible_user"], port=values.get("ansible_port", 22),
                                         identity=values.get("ansible_ssh_private_key_file"),
                                         become=args.become)
    return collected


def placeholder(module, control, target, run_id, policy_ref, status, reason):
    owner, controls = REGISTRY[module]
    return {"schema_version": "1.0", "run_id": run_id, "timestamp_utc": utcnow(),
            "control_id": control, "owner": owner, "cis_status": controls[control],
            "scope": "cluster" if control == "5.1" else "node", "target": target,
            "status": status, "actual": None, "expected": "Implemented module collector/evaluator",
            "evidence": "", "policy_ref": policy_ref, "reason": reason, "duration_ms": 0.0}


def dispatch(module, target, policy, facts, run_id, policy_ref, fixture_mode):
    if module == "platform":
        return run_all_checks(target, policy, facts=facts, run_id=run_id, policy_ref=policy_ref)
    _, controls = REGISTRY[module]
    status, reason = "NOT_IMPLEMENTED", "Module returned no implementation for this control"
    module_name = f"checks.{module}.checker"
    try:
        checker_module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name not in {module_name, f"checks.{module}", "checks"}:
            status, reason = "ERROR", "Checker dependency could not be imported"
        return [placeholder(module, c, target, run_id, policy_ref, status, reason) for c in controls]
    except Exception:
        return [placeholder(module, c, target, run_id, policy_ref, "ERROR", "Checker import failed")
                for c in controls]
    function = getattr(checker_module, "run_all_checks", None)
    if not callable(function):
        return [placeholder(module, c, target, run_id, policy_ref, status, reason) for c in controls]
    try:
        params = inspect.signature(function).parameters
        kwargs = {}
        if "facts" in params:
            kwargs["facts"] = facts
        elif fixture_mode:
            return [placeholder(module, c, target, run_id, policy_ref, "NOT_IMPLEMENTED",
                                "Module has no fixture injection adapter") for c in controls]
        for name, value in (("run_id", run_id), ("policy_ref", policy_ref)):
            if name in params:
                kwargs[name] = value
        rows = function(target, policy, **kwargs)
        if not isinstance(rows, list):
            raise ValueError("Invalid checker result")
        found = {}
        for row in rows:
            row = dict(row)
            control = row.get("control_id")
            if control not in controls or control in found or row.get("owner") != REGISTRY[module][0]:
                raise ValueError("Invalid checker ownership/control")
            if row.get("cis_status") != controls[control]:
                raise ValueError("Incorrect CIS automation label")
            row.update(run_id=run_id, target=target, policy_ref=policy_ref)
            validate_results([row])
            found[control] = redact(row)
        return [found.get(c) or placeholder(module, c, target, run_id, policy_ref, status, reason)
                for c in controls]
    except NotImplementedError:
        pass
    except Exception:
        status, reason = "ERROR", "Checker raised an exception or violated result contract; raw output suppressed"
    return [placeholder(module, c, target, run_id, policy_ref, status, reason) for c in controls]


def exit_status(rows):
    states = {row["status"] for row in rows}
    if "ERROR" in states:
        return 2
    if "FAIL" in states:
        return 1
    if states & {"NEEDS_REVIEW", "NOT_IMPLEMENTED"}:
        return 3
    return 0


def audit(args):
    modules = selected_modules(args.modules)
    for name in ("results.json", "run.json"):
        distinct_output(Path(args.out) / name, args.inventory, args.policy,
                        *([args.fixture] if args.fixture else []))
    policy = load_mapping(args.policy)
    collected = collect_nodes(args, policy)
    run_id = "run-" + uuid.uuid4().hex
    rows = []
    for node, facts in collected.items():
        for module in modules:
            rows.extend(dispatch(module, node, policy, facts, run_id, args.policy, bool(args.fixture)))
    validate_results(rows)
    out = Path(args.out)
    dump(out / "results.json", rows)
    dump(out / "run.json", {"schema_version": "1.0", "run_id": run_id, "timestamp_utc": utcnow(),
                            "source_mode": "fixture" if args.fixture else "ssh",
                            "fixture": args.fixture, "inventory": args.inventory,
                            "policy_ref": args.policy, "targets": list(collected),
                            "modules": modules,
                            "counts": dict(Counter(row["status"] for row in rows)),
                            "results_sha256": hashlib.sha256((out / "results.json").read_bytes()).hexdigest(),
                            "service_verification": "not performed" if args.fixture else "read-only node probes; CQL/TLS not verified"})
    print(json.dumps({"run_id": run_id, "source_mode": "fixture" if args.fixture else "ssh",
                      "counts": dict(Counter(row["status"] for row in rows)), "out": str(out)}))
    return exit_status(rows)


def preflight(args):
    if args.out:
        distinct_output(args.out, args.inventory, args.policy, *([args.fixture] if args.fixture else []))
    policy = load_mapping(args.policy)
    collected = collect_nodes(args, policy)
    checks = []
    for node, facts in collected.items():
        os_entry = facts.get("os", {})
        state = "ERROR"
        if isinstance(os_entry, dict) and os_entry.get("ok") is True and isinstance(os_entry.get("data"), dict):
            data = os_entry.get("data", {})
            name = f"{str(data.get('id', '')).title()} {data.get('version_id', '')}"
            supported = policy.get("platform", {}).get("supported_os_distros")
            if supported is None:
                state = "NEEDS_REVIEW"
            elif (isinstance(supported, list) and all(isinstance(item, str) for item in supported)
                  and isinstance(data.get("id"), str) and isinstance(data.get("version_id"), str)
                  and data["id"] and data["version_id"]):
                state = "PASS" if name in supported else "FAIL"
        checks.append({"target": node, "check": "supported_os", "status": state})
        for row in run_all_checks(node, policy, facts=facts, run_id="preflight", policy_ref=args.policy):
            checks.append({"target": node, "check": row["control_id"], "status": row["status"], "reason": row["reason"]})
    document = {"source_mode": "fixture" if args.fixture else "ssh", "timestamp_utc": utcnow(),
                "ready": all(c["status"] == "PASS" for c in checks), "checks": checks,
                "service_verification": "not performed" if args.fixture else "SSH node probes only"}
    if args.out:
        dump(args.out, document)
    print(json.dumps(document, indent=2))
    return exit_status(checks)


def plan(args):
    meta_path = Path(args.input).with_name("run.json")
    distinct_output(args.out, args.input, meta_path)
    content, results_digest = json_snapshot(args.input)
    rows = validate_results(content)
    run_ids = sorted({row["run_id"] for row in rows})
    if len(run_ids) != 1:
        raise RunnerError("A plan must come from exactly one audit run")
    targets = sorted({row["target"] for row in rows})
    counts = dict(Counter(row["status"] for row in rows))
    source_mode = "unknown"
    source_run_digest = None
    if meta_path.exists():
        meta, source_run_digest = json_snapshot(meta_path)
        if not isinstance(meta, dict):
            raise ValueError("Invalid audit provenance")
        if meta.get("results_sha256") != results_digest:
            raise ValueError("Audit provenance hash mismatch")
        if (meta.get("run_id") != run_ids[0] or string_list(meta.get("targets")) != set(targets) or
                meta.get("counts") != counts or
                any(row["policy_ref"] != meta.get("policy_ref") for row in rows)):
            raise RunnerError("Audit provenance context does not match results")
        modules = meta.get("modules")
        if not isinstance(modules, list):
            raise RunnerError("Regenerate audit: provenance does not include module coverage")
        selected_modules(",".join(modules))
        expected = {(target, control) for target in targets for module in modules
                    for control in REGISTRY[module][1]}
        if {(row["target"], row["control_id"]) for row in rows} != expected:
            raise RunnerError("Audit coverage is incomplete or contradicts provenance")
        source_mode = meta.get("source_mode")
        if source_mode not in {"fixture", "ssh"} or bool(meta.get("fixture")) != (source_mode == "fixture"):
            raise RunnerError("Audit provenance source is inconsistent")
    plan_id = "plan-" + uuid.uuid4().hex
    actions = [{"action_id": action_id(plan_id, row["target"], row["control_id"]),
                "target": row["target"], "control_id": row["control_id"], "owner": row["owner"],
                "module": CONTROL_METADATA[row["control_id"]][0], "scope": row["scope"],
                "reason": row["reason"], "expected": row["expected"], "executable": False,
                "action": "Owner must implement and review remediation; no automatic backend registered"}
               for row in rows if row["status"] == "FAIL"]
    document = {"schema_version": "1.0", "plan_id": plan_id,
                "created_at": utcnow(), "source_mode": source_mode,
                "target_environment": args.environment, "run_ids": run_ids, "targets": targets,
                "source_sha256": results_digest, "source_run_sha256": source_run_digest,
                "result_counts": counts, "total_results": len(rows),
                "actions": actions, "requires_approval": True,
                "blocked_results": sum(r["status"] in {"ERROR", "NEEDS_REVIEW", "NOT_IMPLEMENTED"} for r in rows)}
    validate_plan(document)
    dump(args.out, document)
    print(json.dumps({"plan": args.out, "actions": len(actions),
                      "sha256": file_hash(args.out),
                      "executable": False}))
    return 0


def action_id(plan_id, target, control):
    value = json.dumps([plan_id, target, control], separators=(",", ":")).encode()
    return "action-" + hashlib.sha256(value).hexdigest()[:24]


def validate_plan(document):
    if not isinstance(document, dict) or document.get("schema_version") != "1.0":
        raise RunnerError("Unsupported plan format; regenerate with the current runner")
    if not isinstance(document.get("plan_id"), str) or not re.fullmatch(r"plan-[a-f0-9]{32}", document["plan_id"]):
        raise RunnerError("Invalid plan ID")
    timestamp(document.get("created_at"))
    environment = document.get("target_environment")
    if not isinstance(environment, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", environment):
        raise RunnerError("Invalid target environment")
    if document.get("source_mode") not in {"ssh", "fixture", "unknown"} or document.get("requires_approval") is not True:
        raise RunnerError("Invalid plan source or approval requirement")
    if len(string_list(document.get("run_ids"))) != 1:
        raise RunnerError("A plan must identify one audit run")
    targets = string_list(document.get("targets"))
    for key in ("source_sha256", "source_run_sha256"):
        value = document.get(key)
        if key == "source_run_sha256" and value is None and document["source_mode"] == "unknown":
            continue
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise RunnerError("Plan audit hash is missing or invalid")
    counts = document.get("result_counts")
    states = {"PASS", "FAIL", "ERROR", "NEEDS_REVIEW", "NOT_IMPLEMENTED", "NOT_APPLICABLE"}
    if (not isinstance(counts, dict) or not counts or set(counts) - states or
            any(type(number) is not int or number <= 0 for number in counts.values())):
        raise RunnerError("Invalid plan result summary")
    blocked = sum(counts.get(state, 0) for state in ("ERROR", "NEEDS_REVIEW", "NOT_IMPLEMENTED"))
    if (type(document.get("total_results")) is not int or document["total_results"] != sum(counts.values()) or
            type(document.get("blocked_results")) is not int or document["blocked_results"] != blocked):
        raise RunnerError("Plan summary is inconsistent")
    actions = document.get("actions")
    if not isinstance(actions, list) or len(actions) != counts.get("FAIL", 0):
        raise RunnerError("Plan actions must correspond to FAIL results only")
    fields = {"action_id", "target", "control_id", "owner", "module", "scope", "reason", "expected", "executable", "action"}
    seen = set()
    for action in actions:
        if not isinstance(action, dict) or set(action) != fields:
            raise RunnerError("Invalid action shape; command payloads are not accepted")
        control, target = action["control_id"], action["target"]
        if not isinstance(control, str) or not isinstance(target, str):
            raise RunnerError("Action control and target must be strings")
        metadata = CONTROL_METADATA.get(control)
        if metadata is None or (action["module"], action["owner"]) != metadata[:2]:
            raise RunnerError("Action violates control ownership")
        if (target not in targets or (target, control) in seen or
                action["action_id"] != action_id(document["plan_id"], target, control) or
                action["scope"] != ("cluster" if control == "5.1" else "node")):
            raise RunnerError("Action ID, target or scope is invalid")
        if action["executable"] is not False or not isinstance(action["reason"], str) or not isinstance(action["action"], str):
            raise RunnerError("This runner accepts review-only actions without an execution backend")
        if action["expected"] is not None and not isinstance(action["expected"], (str, dict, list)):
            raise RunnerError("Action expected value violates the result contract")
        seen.add((target, control))
    json.dumps(document, allow_nan=False)
    return document


def approval_template(args):
    distinct_output(args.out, args.plan)
    content, digest = json_snapshot(args.plan)
    document = validate_plan(content)
    # Deliberately unsigned/incomplete. Creating a template is never approval.
    draft = {"approval_id": "", "plan_id": document["plan_id"], "plan_hash": digest,
             "target_environment": document["target_environment"], "approved_by": "",
             "approved_at": None, "expires_at": None, "approved_controls": [],
             "approved_targets": [], "approved_action_ids": [], "reason": "",
             "test_only": document["source_mode"] != "ssh"}
    dump(args.out, draft)
    print(json.dumps({"out": args.out, "approved": False,
                      "required_action_ids": [a["action_id"] for a in document["actions"]]}))
    return 0


def validate_approval(document, approval, digest):
    if not isinstance(approval, dict):
        raise RunnerError("Approval must be an object")
    for key in ("plan_id", "target_environment"):
        if approval.get(key) != document[key]:
            raise RunnerError("Approval does not match plan")
    if approval.get("plan_hash") != digest:
        raise RunnerError("Approval plan hash is invalid")
    for key in ("approval_id", "approved_by", "reason"):
        if not isinstance(approval.get(key), str) or not approval[key].strip():
            raise RunnerError("Approval identity and reason must be filled by the reviewer")
    if type(approval.get("test_only")) is not bool:
        raise RunnerError("Approval must explicitly identify whether it is test-only")
    start, expiry = timestamp(approval.get("approved_at")), timestamp(approval.get("expires_at"))
    if not timestamp(document["created_at"]) <= start <= datetime.now(timezone.utc) < expiry:
        raise RunnerError("Approval not current")
    for key, action_key in (("approved_controls", "control_id"), ("approved_targets", "target"),
                            ("approved_action_ids", "action_id")):
        if string_list(approval.get(key), empty=True) != {a[action_key] for a in document["actions"]}:
            raise RunnerError("Approval must cover exactly the planned actions, targets and controls")
    return approval


def apply(args):
    dry_run = getattr(args, "dry_run", False)
    out = getattr(args, "out", None)
    if out:
        if not dry_run:
            raise RunnerError("--out is available only with --dry-run")
        distinct_output(out, args.plan, args.approval)
    content, plan_digest = json_snapshot(args.plan)
    document = validate_plan(content)
    approval, approval_digest = json_snapshot(args.approval)
    if not dry_run and document["source_mode"] != "ssh":
        raise RunnerError("Only a node SSH audit may be used for apply")
    validate_approval(document, approval, plan_digest)
    if document["source_mode"] == "unknown":
        raise RunnerError("Unknown audit provenance cannot be used for apply or its dry run")
    if document["source_mode"] == "fixture" and approval["test_only"] is not True:
        raise RunnerError("Fixture approvals must be explicitly test-only")
    if not dry_run and approval["test_only"]:
        raise RunnerError("Test-only approvals cannot authorize node changes")
    if dry_run:
        blocked = []
        if document["source_mode"] == "fixture" or approval["test_only"]:
            blocked.append("TEST_INPUT_ONLY")
        if document["blocked_results"]:
            blocked.append("UNRESOLVED_AUDIT_RESULTS")
        if document["actions"]:
            blocked.append("OWNER_BACKEND_REQUIRED")
        review = {"schema_version": "1.0", "mode": "dry_run", "plan_id": document["plan_id"],
                  "plan_sha256": plan_digest, "approval_sha256": approval_digest,
                  "source_mode": document["source_mode"], "timestamp_utc": utcnow(),
                  "approval_checks": "PASS", "approver_authentication": "not implemented",
                  "execution_ready": False, "node_changes_performed": False,
                  "blocked_reasons": blocked, "actions": document["actions"]}
        if out:
            dump(out, review)
        print(json.dumps(redact(review), indent=2))
        return 3 if blocked else 0
    # Remediation implementations stay with their owners. A dry run never loads
    # or calls such code; there is no shell, SSH or Ansible apply path here.
    raise RunnerError("No apply backend registered; no node changes performed")


def report(args):
    distinct_output(args.out, args.input)
    rows = validate_results(read_json(args.input))
    from cis_lab.report import generate_html_report
    output = Path(args.out)
    if output.exists():
        raise RunnerError("Report output already exists; choose a fresh path")
    try:
        generate_html_report(redact(rows), str(output))
    except Exception:
        raise RunnerError("TV3 report backend failed; raw output suppressed") from None
    if not output.is_file() or output.stat().st_size == 0:
        raise RunnerError("TV3 HTML report is not implemented; no report produced")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="CIS Cassandra lab runner (TV1)")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "audit"):
        child = subs.add_parser(name)
        child.add_argument("--inventory", default="inventories/dev.yml")
        child.add_argument("--policy", default="policies/lab.yml")
        child.add_argument("--limit", help="Comma-separated inventory host names")
        child.add_argument("--fixture", help="Offline node facts JSON; disables SSH")
        child.add_argument("--become", action="store_true", help="Read node facts via sudo -n (for /proc permissions)")
        child.add_argument("--out", default="artifacts/latest" if name == "audit" else None)
        if name == "audit":
            child.add_argument("--modules", default=",".join(REGISTRY))
    child = subs.add_parser("plan")
    child.add_argument("--input", required=True)
    child.add_argument("--out", required=True)
    child.add_argument("--environment", default="dev")
    child = subs.add_parser("apply")
    child.add_argument("--plan", required=True)
    child.add_argument("--approval", required=True)
    child.add_argument("--dry-run", action="store_true", help="Validate approval and review actions offline; never changes nodes")
    child.add_argument("--out", help="Optional JSON output for the dry run")
    child = subs.add_parser("approval-template", help="Create an incomplete approval form for a reviewer")
    child.add_argument("--plan", required=True)
    child.add_argument("--out", required=True)
    child = subs.add_parser("report")
    child.add_argument("--input", required=True)
    child.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        return {"audit": audit, "preflight": preflight, "plan": plan,
                "apply": apply, "report": report, "approval-template": approval_template}[args.command](args)
    except RunnerError as exc:
        print("CIS-LAB ERROR: " + str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError, jsonschema.ValidationError):
        # Do not print exception strings: parser errors can contain credentials or YAML snippets.
        print("CIS-LAB ERROR: input, policy, contract or approval rejected; no apply performed. "
              "Check command requirements in bootstrap/README.md.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
