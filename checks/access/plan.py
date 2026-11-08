"""Reviewable proposals only. This module has no apply or CQL executor."""
import hashlib
import json
from .common import utc_now, validate_results

def build_plan(results, policy_bytes=b""):
    rows = validate_results(results)
    actions, seen = [], set()
    for row in rows:
        if row["status"] != "FAIL":
            continue
        if row["control_id"] == "3.3":
            for v in row["actual"].get("violations",[]):
                if v["kind"] == "excess_permission":
                    action = {"action":"REVIEW_REVOKE_PERMISSION","role":v["granted_to"],"permission":v["permission"],"resource":v["resource"]}
                else:
                    action = {"action":"MANUAL_ROLE_REVIEW","role":v["role"],"finding":v["kind"]}
                key = json.dumps(action,sort_keys=True)
                if key not in seen:
                    seen.add(key); actions.append(action)
        elif row["control_id"] == "3.8":
            for role in row["actual"].get("unauthorized",[]):
                actions.append({"action":"REVIEW_EFFECTIVE_SUPERUSER","role":role,"warning":"Review role ancestry; demoting a child role does not remove inherited superuser"})
        elif row["control_id"] == "3.5":
            actions.append({"action":"MANUAL_NETWORK_REVIEW","target":row["target"],"warning":"Coordinate topology, bind addresses and TLS SANs before a change"})
    content = json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    failures=[{k:row[k] for k in ['control_id','scope','target','actual','expected','policy_ref']} for row in rows if row['status']=='FAIL']
    failures.sort(key=lambda row:(row['control_id'],row['scope'],row['target']))
    observation=json.dumps(failures,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    return {"schema_version":"1.0","created_at_utc":utc_now(),"owner":"Doan Van Tai",
        "source_results_sha256":hashlib.sha256(content).hexdigest(),"policy_sha256":hashlib.sha256(policy_bytes).hexdigest(),
        "observation_sha256":hashlib.sha256(observation).hexdigest(),"observed_failures":failures,
        "targets":sorted({row['target'] for row in rows if row['status']=='FAIL'}),
        "impact":"Revoking grants can break application access; admin changes can lock out operators; network changes can disrupt cluster communication. Review each affected role, ancestry and consumer before any change.",
        "approval_required":True,"executable":False,"actions":actions,
        "preconditions":["Recollect the stable fields in observed_failures and compare observation_sha256 and policy_sha256; source_results_sha256 records provenance, not a freshness comparison of timestamps","Verify replacement admin using a new connection before reducing admin access","Obtain human approval bound to this exact plan hash"],
        "verification":["Repeat relevant read-only audit","Test reader SELECT succeeds and MODIFY is rejected","Preserve before/after evidence"],
        "limitation":"Midterm plan proposals only; no automatic revoke, role deletion or apply implemented"}
