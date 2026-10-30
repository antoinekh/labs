"""Merge a bad cleanup into main through a proposed change, to have something to roll back."""

import argparse
import asyncio
import time

from infrahub_sdk import InfrahubClient
from infrahub_sdk.timestamp import Timestamp

BRANCH = "cleanup-lys"
# The cleanup targets the decommissioned pe-lys-04, but its filter matches every service of Lyon.
DOWNGRADED = ["svc-pe-lys-01-2", "svc-pe-lys-02-1", "svc-pe-lys-03-1"]
DELETED = "svc-pe-lys-02-2"

VALIDATORS = """
query($pc: ID!) {
  CoreValidator(proposed_change__ids: [$pc]) { edges { node { display_label state { value } conclusion { value } } } }
}
"""

MERGE = """
mutation($id: String!) {
  CoreProposedChangeMerge(data: {id: $id}, wait_until_completion: true) { ok }
}
"""


async def main(merge: bool) -> None:
    client = InfrahubClient()
    if BRANCH not in await client.branch.all():
        await client.branch.create(branch_name=BRANCH, sync_with_git=False, wait_until_completion=True)
    for name in DOWNGRADED:
        service = await client.get(kind="NetAppService", name__value=name, branch=BRANCH)
        service.criticality.value = "low"
        await service.save()
    deleted = await client.get(kind="NetAppService", name__value=DELETED, branch=BRANCH)
    await deleted.delete()
    print(f"{BRANCH}: criticality set to low on {', '.join(DOWNGRADED)}, {DELETED} deleted")

    proposed_change = await client.create(
        kind="CoreProposedChange", name="Clean up the Lyon services", source_branch=BRANCH, destination_branch="main"
    )
    await proposed_change.save()
    print(f"proposed change {proposed_change.id}")
    if not merge:
        return

    while True:
        await asyncio.sleep(10)
        result = await client.execute_graphql(query=VALIDATORS, variables={"pc": proposed_change.id})
        validators = [edge["node"] for edge in result["CoreValidator"]["edges"]]
        if len(validators) >= 3 and all(v["state"]["value"] == "completed" for v in validators):
            break
    for validator in validators:
        print(f"  {validator['display_label']}: {validator['conclusion']['value']}")
    print(f"before the merge: {Timestamp().to_string()}")
    started = time.monotonic()
    try:
        await client.execute_graphql(query=MERGE, variables={"id": proposed_change.id}, timeout=300)
    except Exception as exc:  # noqa: BLE001
        print(f"merge call: {exc}")
    print(f"merge requested, {time.monotonic() - started:.0f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-merge", action="store_true", help="open the proposed change but do not merge it")
    args = parser.parse_args()
    asyncio.run(main(merge=not args.no_merge))
