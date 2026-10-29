"""Time the same list query on main, on a fresh branch, and on a branch with many changes."""

import argparse
import asyncio
import statistics
import time

from infrahub_sdk import InfrahubClient

QUERY = """
query Devices {
  NetDevice(limit: 1100) { count edges { node { name { value } status { value } site { value } } } }
}
"""


async def timed_query(client: InfrahubClient, branch: str, runs: int) -> list[float]:
    timings = []
    for _ in range(runs):
        started = time.monotonic()
        await client.execute_graphql(query=QUERY, branch_name=branch)
        timings.append(time.monotonic() - started)
    return timings


async def main(changes: int, runs: int) -> None:
    client = InfrahubClient()
    for name in ("read-fresh", "read-changed"):
        await client.branch.create(branch_name=name, sync_with_git=False, wait_until_completion=True)
    devices = await client.all(kind="NetDevice", branch="read-changed", limit=changes)
    batch = await client.create_batch()
    for device in devices[:changes]:
        device.status.value = "maintenance"
        batch.add(task=device.save, node=device)
    async for _ in batch.execute():
        pass
    await timed_query(client, "main", 2)
    for branch in ("main", "read-fresh", "read-changed"):
        timings = await timed_query(client, branch, runs)
        print(
            f"branch={branch} runs={runs} median={statistics.median(timings):.3f}s "
            f"min={min(timings):.3f}s max={max(timings):.3f}s"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changes", type=int, default=1000)
    parser.add_argument("--runs", type=int, default=7)
    args = parser.parse_args()
    asyncio.run(main(changes=args.changes, runs=args.runs))
