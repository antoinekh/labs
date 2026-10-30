"""Build a branch that undoes what changed on main between two times, from the diff of main and its state before."""

import argparse
import asyncio

from infrahub_sdk import InfrahubClient
from infrahub_sdk.timestamp import Timestamp

DIFF_UPDATE = """
mutation($name: String!, $from: DateTime!, $to: DateTime!) {
  DiffUpdate(data: {branch: "main", name: $name, from_time: $from, to_time: $to}, wait_until_completion: true) { ok }
}
"""

DIFF_TREE = """
query($from: DateTime!, $to: DateTime!) {
  DiffTree(branch: "main", from_time: $from, to_time: $to) {
    nodes {
      uuid kind label status
      attributes { name status }
      relationships { name status }
    }
  }
}
"""


async def exists(client: InfrahubClient, kind: str, uuid: str, branch: str, at: str | None = None) -> bool:
    found = await client.filters(kind=kind, ids=[uuid], branch=branch, at=Timestamp(at) if at else None)
    return bool(found)


async def snapshot(client: InfrahubClient, kind: str, uuid: str, before: str) -> dict:
    """Return the attributes and the related ids of an object on main at the given time."""
    schema = await client.schema.get(kind=kind, branch="main")
    attributes = " ".join(f"{attribute.name} {{ value }}" for attribute in schema.attributes)
    relationships = " ".join(
        f"{rel.name} {{ edges {{ node {{ id }} }} }}" if rel.cardinality == "many" else f"{rel.name} {{ node {{ id }} }}"
        for rel in schema.relationships
        if rel.kind in ("Generic", "Attribute", "Parent", "Component")
    )
    query = f'query {{ {kind}(ids: ["{uuid}"]) {{ edges {{ node {{ {attributes} {relationships} }} }} }} }}'
    result = await client.execute_graphql(query=query, branch_name="main", at=before)
    node = result[kind]["edges"][0]["node"]
    data: dict = {attribute.name: node[attribute.name]["value"] for attribute in schema.attributes}
    for rel in schema.relationships:
        if rel.name not in node:
            continue
        if rel.cardinality == "many":
            data[rel.name] = [edge["node"]["id"] for edge in node[rel.name]["edges"]]
        elif node[rel.name] and node[rel.name]["node"]:
            data[rel.name] = node[rel.name]["node"]["id"]
    return data


async def main(before: str, after: str, branch: str) -> None:
    client = InfrahubClient()
    window = {"from": before, "to": after}
    await client.execute_graphql(query=DIFF_UPDATE, variables={"name": f"rollback-{branch}", **window})
    diff = await client.execute_graphql(query=DIFF_TREE, variables=window)
    nodes = diff["DiffTree"]["nodes"]
    if branch not in await client.branch.all():
        await client.branch.create(branch_name=branch, sync_with_git=False, wait_until_completion=True)

    new_ids: dict[str, str] = {}
    relationship_checks: list[tuple[str, str, str, list[str]]] = []
    for node in nodes:
        kind, uuid = node["kind"], node["uuid"]
        # The diff of main between two times reports a deleted object as updated, so existence decides.
        existed_before = await exists(client, kind, uuid, branch="main", at=before)
        exists_now = await exists(client, kind, uuid, branch=branch)
        if exists_now and not existed_before:
            obj = await client.get(kind=kind, id=uuid, branch=branch)
            await obj.delete()
            print(f"delete {obj.display_label}: added on main after {before}")
            continue
        data = await snapshot(client, kind, uuid, before)
        if existed_before and not exists_now:
            obj = await client.create(kind=kind, branch=branch, **data)
            await obj.save()
            new_ids[uuid] = obj.id
            print(f"create {data.get('name', uuid)} again with its values at {before}: new id {obj.id}")
            continue
        obj = await client.get(kind=kind, id=uuid, branch=branch)
        for attribute in node["attributes"]:
            getattr(obj, attribute["name"]).value = data[attribute["name"]]
            print(f"set {obj.display_label} {attribute['name']} back to {data[attribute['name']]!r}")
        await obj.save()
        for relationship in node["relationships"]:
            relationship_checks.append((kind, uuid, relationship["name"], data.get(relationship["name"], [])))

    for kind, uuid, name, peers_before in relationship_checks:
        expected = {new_ids.get(peer, peer) for peer in peers_before}
        current = await client.get(kind=kind, id=uuid, branch=branch)
        await getattr(current, name).fetch()
        if {peer.id for peer in getattr(current, name).peers} == expected:
            print(f"{current.display_label} {name}: back to its state at {before}")
        else:
            print(f"{current.display_label} {name}: differs from its state at {before}, fix it by hand")
    print(f"branch {branch} ready: open a proposed change to review the rollback")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, help="a time before the bad merge, for example 2026-10-30T08:00:00Z")
    parser.add_argument("--after", required=True, help="a time after the bad merge and before any change to keep")
    parser.add_argument("--branch", required=True, help="the rollback branch to create")
    args = parser.parse_args()
    asyncio.run(main(before=args.before, after=args.after, branch=args.branch))
