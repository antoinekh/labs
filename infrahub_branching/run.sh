#!/bin/bash
# Run a command in a one-off task-worker container, with this lab folder mounted on /lab.
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") [-h] COMMAND [ARGS...]

Run COMMAND in a one-off task-worker container of the infrahub-bench stack.
The container uses the SDK and infrahubctl of the running Infrahub image.
This folder is mounted on /lab.

Environment:
  INFRAHUB_MAX_CONCURRENT_EXECUTION  SDK batch concurrency (default: 2)

Examples:
  $(basename "$0") infrahubctl schema load /lab/schema/net.yml --wait 30
  $(basename "$0") python /lab/gen_data.py --sites 2
USAGE
}

if [[ -z ${1:-} || $1 == "-h" || $1 == "--help" ]]; then
  usage
  [[ -z ${1:-} ]] && exit 1 || exit 0
fi

cd "$(dirname "$0")"
docker compose -p infrahub-bench run --rm -v "$PWD:/lab" \
  -e INFRAHUB_MAX_CONCURRENT_EXECUTION="${INFRAHUB_MAX_CONCURRENT_EXECUTION:-2}" \
  task-worker "$@"
