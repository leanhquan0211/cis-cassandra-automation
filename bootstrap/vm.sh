#!/usr/bin/env bash
# Controller entry point. Never installs services on the controller/laptop.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:---help}"
if [[ "$mode" != --check && "$mode" != --deploy ]]; then
  printf '%s\n' 'Usage: bash bootstrap/vm.sh --check|--deploy INVENTORY HOST' >&2
  exit 2
fi
if [[ $# != 3 || ! "$3" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]]; then
  printf '%s\n' 'Supply an inventory and one cassandra_nodes host.' >&2
  exit 2
fi
command -v ansible-playbook >/dev/null
cd -- "$repo_dir"
args=(-i "$2" ansible/site.yml --limit "$3" --tags platform
      -e platform_bootstrap_confirmed=true)
if [[ "$mode" == --check ]]; then
  args+=(--check --diff)
fi
exec ansible-playbook "${args[@]}"
