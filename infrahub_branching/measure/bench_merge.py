"""Time the edit, diff and merge of a branch that changes N application services."""

import argparse
import asyncio
import time

from infrahub_sdk import InfrahubClient

from bench_branch import graph_count

DIFF_UPDATE = """
mutation DiffUpdate($branch: String!) {
  DiffUpdate(data: {branch: $branch}, wait_until_completion: true) { ok }
}
"""

BRANCH_MERGE = """
mutation BranchMerge($branch: String!) {
  BranchMerge(data: {name: $branch}, wait_until_completion: true) { ok }
}
"""


async def timed(label: str, coroutine) -> float:
    started = time.monotonic()
    await coroutine
    elapsed = time.monotonic() - started
    print(f"  {label} seconds={elapsed:.2f}")
    return elapsed


async def run(client: InfrahubClient, size: int) -> None:
    branch = f"bulk-{size}"
    print(f"size={size} branch={branch}")
    await client.branch.create(branch_name=branch, sync_with_git=False, wait_until_completion=True)
    services = await client.all(kind="NetAppService", branch=branch, limit=size)
    before = await graph_count()

    async def edit() -> None:
        batch = await client.create_batch()
        for service in services[:size]:
            service.owner.value = f"team-noc-{size}"
            batch.add(task=service.save, node=service)
        async for _ in batch.execute():
            pass

    await timed("edit", edit())
    delta = await graph_count() - before
    print(f"  after edit nodes+={delta.nodes} rels+={delta.relationships}")
    await timed("diff", client.execute_graphql(query=DIFF_UPDATE, variables={"branch": branch}))
    delta = await graph_count() - before
    print(f"  after diff nodes+={delta.nodes} rels+={delta.relationships}")
    await timed("merge", client.execute_graphql(query=BRANCH_MERGE, variables={"branch": branch}))
    delta = await graph_count() - before
    print(f"  after merge nodes+={delta.nodes} rels+={delta.relationships}")


async def main(sizes: list[int]) -> None:
    client = InfrahubClient()
    for size in sizes:
        await run(client, size)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sizes", type=int, nargs="+")
    asyncio.run(main(parser.parse_args().sizes))
