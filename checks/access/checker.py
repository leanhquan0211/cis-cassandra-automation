"""TV3 midterm checks. Người thực hiện: Doan Van Tai.

The original two-argument entrypoint is preserved. TV1 can inject a collector
or pre-collected snapshot; no dependency on unfinished TV2 code is assumed.
"""
import time
import uuid
import os
from .common import result
from .evaluator import evaluate_network, evaluate_privileges, evaluate_superusers

def run_all_checks(target_node, policy, *, collector=None, snapshot=None, run_id=None,
                   policy_ref="policies/lab.yml", now=None):
    run_id = run_id or "tv3-" + uuid.uuid4().hex
    setup_error=None
    if collector is None and snapshot is None and os.environ.get('CIS_LAB_ACCESS_RUNTIME'):
        try:
            from .collector import collector_from_runtime_file
            collector=collector_from_runtime_file(os.environ['CIS_LAB_ACCESS_RUNTIME'])
        except Exception as error:
            setup_error=error
    output = []
    for control, kind, evaluate in [("3.3", "roles", evaluate_privileges),
                                    ("3.5", "network", evaluate_network),
                                    ("3.8", "roles", evaluate_superusers)]:
        start = time.perf_counter()
        try:
            if setup_error is not None:raise setup_error
            if snapshot is not None:
                observation = snapshot[kind]
            elif collector is not None:
                observation = collector.collect(target_node, kind)
            else:
                raise ValueError("Collector/snapshot not provided")
            status, actual, expected, reason = evaluate(observation, policy, now)
            evidence = observation.get("evidence", "Pre-collected observation; provenance must be supplied by caller")
        except Exception as error:
            status, actual, expected = "ERROR", None, None
            reason = f"Collection/evaluation could not complete ({getattr(error, 'code', type(error).__name__)})"
            evidence = f"target={target_node}; collection={kind}; no compliance conclusion"
        output.append(result(control, target_node, status, actual, expected, reason,
            run_id=run_id, policy_ref=policy_ref, evidence=evidence,
            duration_ms=(time.perf_counter()-start)*1000))
    for control in ("3.6", "3.7"):
        output.append(result(control, target_node, "NOT_IMPLEMENTED", None, None,
            "Final-term control; no midterm compliance conclusion", run_id=run_id,
            policy_ref=policy_ref, evidence="No implemented evaluator for this control"))
    return output
