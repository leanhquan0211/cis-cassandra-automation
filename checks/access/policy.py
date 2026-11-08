"""Strict YAML loading and policy lifecycle validation; no implicit approval."""
from datetime import date, datetime, timezone
from pathlib import Path
import yaml

class UniqueLoader(yaml.SafeLoader):
    pass

def _mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"Duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping

UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)

def load_yaml(path):
    value = yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    if not isinstance(value, dict):
        raise ValueError("Expected a YAML mapping")
    return value

def policy_problem(policy, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(policy, dict) or policy.get("policy_version") != "1.0":
        return "Missing or unsupported policy version"
    if not isinstance(policy.get("approved_by"), str) or not policy["approved_by"].strip():
        return "Policy has no recorded human approver"
    try:
        approved = datetime.fromisoformat(str(policy["approved_at"]).replace("Z", "+00:00"))
        due = date.fromisoformat(str(policy["review_due"]))
        if approved.tzinfo is None or approved > now:
            return "Policy approval is missing a timezone or is in the future"
        if due < now.date() or due < approved.date():
            return "Policy is expired or has an invalid review deadline"
    except (KeyError, TypeError, ValueError):
        return "Policy approval dates are missing or invalid"
    if not isinstance(policy.get("access"), dict):
        return "Access policy is missing"
    return None
