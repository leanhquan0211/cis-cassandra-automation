"""Run the TV1 fixture workflow without a VM, SSH or external commands.

Usage from repository root: python -m bootstrap.offline_demo --out /tmp/tv1-demo
The only approval produced here is explicitly test-only and cannot authorize apply.
"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from cis_lab import cli

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "checks/platform/fixtures"


def invoke(arguments, expected):
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = cli.main([str(arg) for arg in arguments])
    if code != expected:
        raise RuntimeError("Unexpected fixture workflow exit code")
    return code


def run(output):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Demo output must be a fresh or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    inventory, policy = ROOT / "inventories/dev.yml", ROOT / "bootstrap/fixture-policy.yml"
    summary = {"source_mode": "fixture", "timestamp_utc": cli.utcnow(),
               "service_verification": "not performed", "node_changes_performed": False, "cases": {}}
    # Guard both the runner entry and external process/network primitives. This
    # remains an offline demo even if a future checker accidentally attempts I/O.
    with patch.object(cli, "collect_ssh", side_effect=RuntimeError("SSH forbidden in demo")) as ssh, \
            patch("subprocess.run", side_effect=RuntimeError("Processes forbidden in demo")) as process, \
            patch("socket.socket", side_effect=RuntimeError("Network forbidden in demo")) as network:
        for name, code in (("good", 0), ("bad", 1), ("read_error", 2)):
            out = output / name
            invoke(["audit", "--inventory", inventory, "--limit", "cass-dev1", "--policy", policy,
                    "--modules", "platform", "--fixture", FIXTURES / (name + ".json"), "--out", out], code)
            summary["cases"][name] = {"exit_code": code, "counts": cli.read_json(out / "run.json")["counts"]}

        mixed = {"nodes": {"cass-dev1": cli.read_json(FIXTURES / "good.json")["nodes"]["cass-dev1"],
                           "cass-dev2": cli.read_json(FIXTURES / "bad.json")["nodes"]["cass-dev1"],
                           "cass-int3": cli.read_json(FIXTURES / "read_error.json")["nodes"]["cass-dev1"]}}
        fixture = output / "mixed.fixture.json"
        cli.dump(fixture, mixed)
        out = output / "mixed"
        invoke(["audit", "--inventory", inventory, "--policy", policy, "--modules", "platform",
                "--fixture", fixture, "--out", out], 2)
        summary["cases"]["mixed_three_nodes"] = {"exit_code": 2, "counts": cli.read_json(out / "run.json")["counts"]}

        out = output / "team-policy"
        invoke(["audit", "--inventory", inventory, "--limit", "cass-dev1", "--policy", ROOT / "policies/lab.yml",
                "--modules", "platform", "--fixture", FIXTURES / "good.json", "--out", out], 3)
        summary["cases"]["team_policy"] = {"exit_code": 3, "counts": cli.read_json(out / "run.json")["counts"]}

        preflight = output / "preflight.fixture.json"
        invoke(["preflight", "--inventory", inventory, "--limit", "cass-dev1", "--policy", policy,
                "--fixture", FIXTURES / "good.json", "--out", preflight], 0)

        plan = output / "mixed/plan.json"
        template = output / "mixed/approval-template.json"
        invoke(["plan", "--input", output / "mixed/results.json", "--out", plan,
                "--environment", "fixture-demo"], 0)
        invoke(["approval-template", "--plan", plan, "--out", template], 0)
        document, approval = cli.read_json(plan), cli.read_json(template)
        if document["source_mode"] != "fixture" or approval["test_only"] is not True:
            raise RuntimeError("Demo approval requires fixture source")
        now = datetime.now(timezone.utc)
        approval.update(approval_id="fixture-approval-NOT-FOR-NODES",
                        approved_by="fixture-reviewer-NOT-A-HUMAN-APPROVAL",
                        approved_at=now.isoformat(), expires_at=(now + timedelta(minutes=5)).isoformat(),
                        approved_controls=sorted({a["control_id"] for a in document["actions"]}),
                        approved_targets=sorted({a["target"] for a in document["actions"]}),
                        approved_action_ids=[a["action_id"] for a in document["actions"]],
                        reason="OFFLINE FIXTURE TEST ONLY; never authorizes node changes")
        approved = output / "mixed/approval.fixture.json"
        cli.dump(approved, approval)
        receipt = output / "mixed/dry-run.json"
        invoke(["apply", "--dry-run", "--plan", plan, "--approval", approved, "--out", receipt], 3)
        invoke(["apply", "--plan", plan, "--approval", approved], 2)
        invalid = output / "mixed/approval-invalid.fixture.json"
        cli.dump(invalid, {**approval, "plan_hash": "0" * 64})
        invoke(["apply", "--dry-run", "--plan", plan, "--approval", invalid], 2)
        summary["plan"] = {"actions": len(document["actions"]), "blocked_results": document["blocked_results"],
                           "action_targets": sorted({a["target"] for a in document["actions"]})}
        summary["approval"] = {"template_is_approval": False, "test_only": True,
                               "dry_run_exit_code": 3, "node_apply_exit_code": 2, "wrong_hash_exit_code": 2}
        ssh.assert_not_called()
        process.assert_not_called()
        network.assert_not_called()
    cli.dump(output / "summary.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="TV1 offline fixture demo; no VM or Cassandra needed")
    parser.add_argument("--out", help="Fresh/empty output directory; otherwise creates a directory in /tmp")
    args = parser.parse_args(argv)
    try:
        output = Path(args.out).resolve() if args.out else Path(tempfile.mkdtemp(prefix="cis-tv1-demo-"))
        summary = run(output)
    except (OSError, ValueError, RuntimeError, AssertionError):
        print("Offline demo failed; choose an empty output directory and check dependencies.")
        return 2
    print(json.dumps({"out": str(output), "source_mode": "fixture", "cases": summary["cases"],
                      "plan": summary["plan"], "approval": summary["approval"],
                      "service_verification": "not performed", "node_changes_performed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
