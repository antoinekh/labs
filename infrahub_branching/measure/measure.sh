#!/bin/bash
# Print Neo4j store size and graph counts for the infrahub-bench stack.
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") [-h] LABEL

Print the Neo4j store size on disk, the node and relationship counts,
and the number of Infrahub branches. LABEL tags the output line.

Examples:
  $(basename "$0") empty
  $(basename "$0") after-demo-data
USAGE
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" || -z ${1:-} ]]; then
  usage
  [[ -z ${1:-} ]] && exit 1 || exit 0
fi

label=$1
db=infrahub-bench-database-1

# Store files only grow on disk at a checkpoint, which the database runs every 10 s.
sleep 15

store=$(docker exec $db du -sb /data/databases/neo4j | cut -f1)
tx=$(docker exec $db du -sb /data/transactions/neo4j | cut -f1)
counts=$(docker exec $db cypher-shell -u neo4j -p admin --format plain \
  "MATCH (n) WITH count(n) AS nodes CALL () { MATCH ()-[r]->() RETURN count(r) AS rels } RETURN nodes, rels" | tail -1)
branches=$(docker exec $db cypher-shell -u neo4j -p admin --format plain \
  "MATCH (b:Branch) RETURN count(b)" | tail -1)
echo "$(date -u +%FT%TZ) label=$label store_bytes=$store tx_bytes=$tx nodes_rels=$counts branches=$branches"
