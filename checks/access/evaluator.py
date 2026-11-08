"""Pure TV3 evaluators. No CQL writes or remediation side effects."""
import ipaddress
from .policy import policy_problem

class IncompleteObservation(ValueError):
    pass

def role_closures(observation):
    if not isinstance(observation, dict) or observation.get("complete") is not True:
        raise IncompleteObservation("Role inventory is not proven complete")
    roles = observation.get("roles")
    if not isinstance(roles, list) or not roles:
        raise IncompleteObservation("Role inventory is empty or malformed")
    by_name = {}
    for role in roles:
        if not isinstance(role, dict) or not isinstance(role.get("role"), str) or not role["role"]:
            raise IncompleteObservation("Malformed role record")
        if role["role"] in by_name:
            raise IncompleteObservation("Duplicate role record")
        if any(type(role.get(k)) is not bool for k in ("is_superuser", "can_login")):
            raise IncompleteObservation("Incomplete role flags")
        if not isinstance(role.get("member_of"), list) or any(not isinstance(v, str) for v in role["member_of"]):
            raise IncompleteObservation("Incomplete role membership")
        by_name[role["role"]] = role
    done, visiting = {}, set()
    def visit(name):
        if name in visiting:
            raise IncompleteObservation("Cycle in observed role graph")
        if name not in by_name:
            raise IncompleteObservation("Membership refers to missing role")
        if name in done:
            return done[name]
        visiting.add(name)
        inherited = {name}
        for parent in by_name[name]["member_of"]:
            inherited.update(visit(parent))
        visiting.remove(name)
        done[name] = inherited
        return inherited
    for name in by_name:
        visit(name)
    return by_name, done

def resource_contains(approved, observed):
    """Approved parent resources cover descendants, never the reverse."""
    if not isinstance(approved, str) or not isinstance(observed, str):
        return False
    if approved == observed:
        return True
    a, o = approved.split("/"), observed.split("/")
    if a == ["data", "all"]:
        return o[0] == "data" and len(o) >= 2
    if len(a) == 3 and a[:2] == ["data", "keyspace"]:
        return len(o) == 4 and o[:2] == ["data", "table"] and a[2] == o[2]
    if a == ["roles", "all"]:
        return len(o) == 2 and o[0] == "roles"
    return False

def _permissions(observation, by_name):
    permissions = observation.get("permissions")
    if not isinstance(permissions, list):
        raise IncompleteObservation("Permission inventory is missing")
    for item in permissions:
        if not isinstance(item, dict) or item.get("role") not in by_name:
            raise IncompleteObservation("Permission refers to an unknown role")
        if not isinstance(item.get("permission"), str) or not isinstance(item.get("resource"), str):
            raise IncompleteObservation("Malformed permission record")
    return permissions

def _role_policy(policy):
    approved = policy["access"].get("approved_roles")
    if not isinstance(approved, list) or not approved:
        return None
    output = {}
    for role in approved:
        if not isinstance(role, dict) or not isinstance(role.get("role"), str) or role["role"] in output:
            return None
        if any(type(role.get(k)) is not bool for k in ("is_superuser", "can_login")):
            return None
        if not isinstance(role.get("member_of"), list) or any(not isinstance(n, str) for n in role["member_of"]):
            return None
        if not isinstance(role.get("permissions"), list):
            return None
        for grant in role["permissions"]:
            if not isinstance(grant, dict) or not isinstance(grant.get("permission"), str) or not isinstance(grant.get("resource"), str):
                return None
        output[role["role"]] = role
    if any(parent not in output for role in output.values() for parent in role["member_of"]):
        return None
    try:
        role_closures({"complete": True, "roles": list(output.values())})
    except IncompleteObservation:
        return None
    return output

def evaluate_superusers(observation, policy, now=None):
    roles, closures = role_closures(observation)
    actual = sorted(name for name, inherited in closures.items() if any(roles[n]["is_superuser"] for n in inherited))
    problem = policy_problem(policy, now)
    auth = policy.get("auth") if isinstance(policy, dict) else None
    approved = auth.get("approved_superusers") if isinstance(auth, dict) else None
    if problem or not isinstance(approved, list) or not approved or any(not isinstance(n, str) for n in approved):
        return "NEEDS_REVIEW", {"effective_superusers": actual}, None, problem or "Approved superuser policy is missing or malformed"
    unauthorized, missing = sorted(set(actual)-set(approved)), sorted(set(approved)-set(actual))
    return ("FAIL" if unauthorized or missing else "PASS",
        {"effective_superusers": actual, "unauthorized": unauthorized, "missing": missing},
        {"approved_superusers": sorted(approved)},
        "Unexpected or missing effective superusers" if unauthorized or missing else "Effective superusers match approved policy")

def evaluate_privileges(observation, policy, now=None):
    roles, closures = role_closures(observation)
    permissions = _permissions(observation, roles)
    problem = policy_problem(policy, now)
    approved = _role_policy(policy) if not problem else None
    if problem or approved is None or policy["access"].get("closed_world_permissions") is not True:
        return "NEEDS_REVIEW", {"observed_role_count": len(roles)}, None, problem or "A complete closed-world role/permission policy is required"
    auth = policy.get("auth")
    superusers = auth.get("approved_superusers") if isinstance(auth, dict) else None
    if not isinstance(superusers, list) or not superusers:
        return "NEEDS_REVIEW", None, None, "Approved superuser policy is missing"
    policy_closures = role_closures({"complete": True, "roles": list(approved.values())})[1]
    violations = []
    for name in sorted(set(roles) | set(approved)):
        if name not in approved:
            violations.append({"kind": "unapproved_role", "role": name})
            continue
        if name not in roles:
            violations.append({"kind": "missing_role", "role": name})
            continue
        current, expected = roles[name], approved[name]
        for flag in ("is_superuser", "can_login"):
            if current[flag] != expected[flag]:
                violations.append({"kind": "role_property", "role": name, "property": flag, "actual": current[flag], "expected": expected[flag]})
        if set(current["member_of"]) != set(expected["member_of"]):
            violations.append({"kind": "membership", "role": name, "actual": sorted(current["member_of"]), "expected": sorted(expected["member_of"])})
        if any(roles[n]["is_superuser"] for n in closures[name]) and name not in superusers:
            violations.append({"kind": "effective_superuser", "role": name})
        if name in superusers:
            continue
        allowed = [grant for parent in policy_closures[name] for grant in approved[parent]["permissions"]]
        effective = [grant for grant in permissions if grant['role'] in closures[name]]
        for required in allowed:
            if not any(g['permission']==required['permission'] and resource_contains(g['resource'],required['resource']) for g in effective):
                violations.append({'kind':'missing_permission','role':name,'permission':required['permission'],'resource':required['resource']})
        for grant in permissions:
            if grant["role"] not in closures[name]:
                continue
            if not any(g["permission"] == grant["permission"] and resource_contains(g["resource"], grant["resource"]) for g in allowed):
                violations.append({"kind": "excess_permission", "role": name, "granted_to": grant["role"], "permission": grant["permission"], "resource": grant["resource"]})
    return ("FAIL" if violations else "PASS", {"violations": violations, "observed_role_count": len(roles)},
        {"approved_roles": sorted(approved), "closed_world_permissions": True},
        "Role or effective permission deviates from policy" if violations else "Roles and effective permissions are within policy")

def evaluate_network(observation, policy, now=None):
    if not isinstance(observation, dict) or observation.get("complete") is not True:
        raise IncompleteObservation("Network collection is incomplete")
    config, sockets = observation.get("config"), observation.get("sockets")
    if not isinstance(config, dict) or not isinstance(sockets, list):
        raise IncompleteObservation("Missing runtime config or listening sockets")
    if observation.get("service_active") is not True:
        raise IncompleteObservation("Cassandra service is not active")
    problem = policy_problem(policy, now)
    networks = policy.get("access", {}).get("allowed_node_networks") if isinstance(policy, dict) else None
    if problem or not isinstance(networks, list) or not networks:
        return "NEEDS_REVIEW", config, None, problem or "Approved network policy is missing"
    try:
        allowed = [ipaddress.ip_network(n, strict=True) for n in networks]
    except (ValueError, TypeError):
        return "NEEDS_REVIEW", config, None, "Invalid approved CIDR"
    if observation.get("config_loaded") is not True:
        return "NEEDS_REVIEW", config, networks, "Cannot establish that the running process loaded the observed config"
    if any(config.get(a) and config.get(i) for a,i in [("listen_address","listen_interface"),("rpc_address","rpc_interface")]):
        return "FAIL", config, networks, "Both address and interface are configured for the same transport"
    forbidden = policy["access"].get("disallowed_listen_addresses", ["0.0.0.0", "::"])
    interfaces = observation.get("interfaces", {})
    def addresses(address_key, interface_key):
        if config.get(address_key):
            return [config[address_key]]
        if config.get(interface_key):
            return interfaces.get(config[interface_key], [])
        return []
    def permitted(value):
        try:
            ip = ipaddress.ip_address(value.split("%", 1)[0])
            return value not in forbidden and not ip.is_unspecified and any(ip in n for n in allowed if n.version == ip.version)
        except (ValueError, AttributeError):
            return False
    errors = []
    for ak, ik, pk, default in [("listen_address", "listen_interface", "storage_port", 7000), ("rpc_address", "rpc_interface", "native_transport_port", 9042)]:
        ips, port = addresses(ak, ik), config.get(pk, default)
        if type(port) is not int or not 1 <= port <= 65535:
            raise IncompleteObservation("Invalid observed transport port")
        approved_config = all(permitted(ip) for ip in ips) if config.get(ak) else any(permitted(ip) for ip in ips)
        if not ips or not approved_config:
            errors.append({"kind": "unapproved_config_bind", "field": ak, "addresses": ips})
        observed = [row.get("address") for row in sockets if row.get("port") == port]
        if not observed or any(not permitted(ip) or ip not in ips for ip in observed):
            errors.append({"kind": "runtime_bind_mismatch", "port": port, "observed": observed, "configured": ips})
    return ("FAIL" if errors else "PASS", {"config": config, "sockets": sockets, "violations": errors},
        {"allowed_node_networks": networks}, "Unapproved or inconsistent runtime bind" if errors else "Config and active sockets use approved private interfaces")
