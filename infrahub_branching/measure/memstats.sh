#!/bin/bash
# Print the memory use of the Infrahub application containers.
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") [-h] LABEL

Print the memory use of the server, task workers and database containers of
the infrahub-bench stack. LABEL tags the output line.

Example:
  $(basename "$0") 27-branches
USAGE
}

if [[ -z ${1:-} || $1 == "-h" || $1 == "--help" ]]; then
  usage
  [[ -z ${1:-} ]] && exit 1 || exit 0
fi

stats=$(docker stats --no-stream --format '{{.Name}}={{.MemUsage}}' \
  infrahub-bench-infrahub-server-1 infrahub-bench-task-worker-1 infrahub-bench-task-worker-2 infrahub-bench-database-1 \
  | sed -e 's/infrahub-bench-//' -e 's/ \/.*//' | tr '\n' ' ')
echo "$(date -u +%FT%TZ) label=$1 $stats"
