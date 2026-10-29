"""Time branch creation and branch edits, and count what each one adds to the graph."""

import argparse
import asyncio
import os
import time
from dataclasses import dataclass

from infrahub_sdk import InfrahubClient
from neo4j import AsyncGraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://database:7687")


@dataclass
class GraphCount:
    nodes: int
    relationships: int

    def __sub__(self, other: "GraphCount") -> "GraphCount":
        return GraphCount(self.nodes - other.nodes, self.relationships - other.relationships)


async def graph_count() -> GraphCount:
    async with AsyncGraphDatabase.driver(NEO4J_URI, auth=("neo4j", "admin")) as driver:
        records, _, _ = await driver.execute_query(
            "MATCH (n) WITH count(n) AS nodes CALL () { MATCH ()-[r]->() RETURN count(r) AS rels } RETURN nodes, rels"
        )
    return GraphCount(nodes=records[0]["nodes"], relationships=records[0]["rels"])


async def create_branches(client: InfrahubClient, prefix: str, count: int) -> None:
    for index in range(count):
        before = await graph_count()
        started = time.monotonic()
        await client.branch.create(branch_name=f"{prefix}-{index}", sync_with_git=False, wait_until_completion=True)
        elapsed = time.monotonic() - started
        delta = await graph_count() - before
        print(f"create branch={prefix}-{index} seconds={elapsed:.3f} nodes+={delta.nodes} rels+={delta.relationships}")


async def edit_on_branch(client: InfrahubClient, branch: str, count: int) -> None:
    devices = await client.all(kind="NetDevice", branch=branch, limit=count)
    before = await graph_count()
    started = time.monotonic()
    for device in devices[:count]:
        device.status.value = "maintenance"
        await device.save()
    elapsed = time.monotonic() - started
    delta = await graph_count() - before
    print(
        f"edit branch={branch} devices={len(devices[:count])} seconds={elapsed:.3f} nodes+={delta.nodes} rels+={delta.relationships}"
    )


async def main(prefix: str, count: int, edits: int) -> None:
    client = InfrahubClient()
    await create_branches(client, prefix, count)
    if edits:
        await edit_on_branch(client, f"{prefix}-0", edits)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="bench")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--edits", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(main(prefix=args.prefix, count=args.count, edits=args.edits))
