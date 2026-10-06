#!/bin/bash
# Print the default-route next hops and the LSP flags of border-frr on both access routers.

usage() {
  cat <<'EOF'
Usage: state.sh <label>

Print the default route of l1-srsim and l1-frr, and the L1 LSP of border-frr as each one sees it.
The second octet of a next hop tells the border: 10.1.x.x is border-srsim, 10.2.x.x is border-frr.

Example:
  state.sh overload
EOF
}

if [[ $1 == "-h" || $1 == "--help" || -z $1 ]]; then
  usage
  exit 0
fi

lab="clab-isis-two-exit-no-junos"
echo "### border-frr: $1"
echo "- l1-srsim:"
printf 'environment more false\nshow router route-table 0.0.0.0/0 exact\nshow router isis database border-frr.00-00\nlogout\n' \
  | timeout 60 ssh -tt -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR admin@172.31.113.21 \
  | tr -d '\r' | grep -E '^\s+10\.[0-9.]+\s+[0-9]+\s*$|^0\.0\.0\.0/0|No\. of Routes|^border-frr\.00-00|^\s+OV\s*$'
echo "- l1-frr:"
docker exec "$lab-l1-frr" vtysh -c 'show ip route 0.0.0.0/0' -c 'show isis database' 2>/dev/null \
  | grep -E '^\s+\* |% Network not in table|^border-frr\.00-00'
