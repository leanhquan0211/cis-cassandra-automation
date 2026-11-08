"""SSH transport for the TV3 read-only probe; credentials travel only over stdin."""
import json
from pathlib import Path
import re
import shlex
import subprocess
from .common import redact
from .policy import load_yaml

class CollectionError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

def collector_from_runtime_file(path):
    """Compatibility adapter for TV1's original two-argument checker interface."""
    config=json.loads(Path(path).read_text())
    credentials={}
    if config.get('credentials_file'):
        secret=Path(config['credentials_file'])
        if secret.stat().st_mode & 0o077:raise ValueError('Credentials file must be private')
        credentials=json.loads(secret.read_text())
    return SSHCollector(load_yaml(config['inventory']),config['ssh_config'],credentials=credentials,
                        timeout=config.get('timeout',75))

def inventory_nodes(inventory):
    try:
        nodes = inventory["all"]["children"]["cassandra_nodes"]["hosts"]
    except (KeyError, TypeError):
        raise ValueError("Inventory must define cassandra_nodes.hosts") from None
    if not nodes or not isinstance(nodes, dict):
        raise ValueError("Inventory has no Cassandra nodes")
    for name, host in nodes.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name.startswith("-"):
            raise ValueError("Unsafe inventory alias")
        if not isinstance(host, dict) or not isinstance(host.get("ansible_host"),str):
            raise ValueError("Node address missing from inventory")
    return nodes

class SSHCollector:
    def __init__(self, inventory, ssh_config, *, credentials=None, timeout=60):
        self.nodes = inventory_nodes(inventory)
        self.ssh_config = str(Path(ssh_config).resolve())
        self.credentials = credentials or {}
        self.timeout = timeout
        self.cache = {}

    def collect(self, target, kind):
        key = (target, kind)
        if key in self.cache:
            return self.cache[key]
        node = self.nodes[target]
        request = {"kind":kind,"host":node["ansible_host"],"port":node.get("cql_port",9042)}
        if kind == "roles":
            request.update({k:self.credentials[k] for k in ("username","password")})
            if "tls" in self.credentials:
                request["tls"] = self.credentials["tls"]
        source = Path(__file__).with_name("remote_probe.py").read_text()
        command = "sudo /opt/cis-lab/venv/bin/python -c " + shlex.quote(source)
        completed = subprocess.run(["ssh","-F",self.ssh_config,target,command],
            input=json.dumps(request),text=True,capture_output=True,timeout=self.timeout)
        if completed.returncode:
            try:
                code = json.loads(completed.stdout).get("error_type", "PROBE_FAILED")
                if not isinstance(code,str) or not re.fullmatch(r"[A-Za-z_]+",code):
                    code = "PROBE_FAILED"
            except ValueError:
                code = "SSH_FAILED"
            raise CollectionError(code)
        try:
            payload = json.loads(completed.stdout)
            if payload.get("ok") is not True:
                raise CollectionError("Node reported a collection error")
            observation = redact(payload["observation"])
        except (ValueError, KeyError):
            raise CollectionError("Invalid node response") from None
        self.cache[key] = observation
        return observation
