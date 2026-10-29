"""List the application services that depend on a router, through the Graph Traversal API."""

import argparse
import asyncio

from infrahub_sdk import InfrahubClient

QUERY = """
query Impact($source: String!, $depth: Int!) {
  InfrahubReachableNodes(data: {source_id: $source, target_kinds: ["NetAppService"], max_depth: $depth, max_results: 200}) {
    count
    dependencies {
      depth
      node { display_label }
      path { hops { node { kind display_label } } }
    }
  }
}
"""


async def main(device_name: str, branch: str, depth: int) -> None:
    client = InfrahubClient()
    device = await client.get(kind="NetDevice", name__value=device_name, branch=branch)
    result = await client.execute_graphql(
        query=QUERY, variables={"source": device.id, "depth": depth}, branch_name=branch
    )
    reachable = result["InfrahubReachableNodes"]
    print(f"{device_name} on {branch}: {reachable['count']} application services")
    for dependency in reachable["dependencies"][:5]:
        hops = " > ".join(hop["node"]["display_label"] for hop in dependency["path"]["hops"])
        print(f"  depth={dependency['depth']} {hops}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--depth", type=int, default=5)
    args = parser.parse_args()
    asyncio.run(main(device_name=args.device, branch=args.branch, depth=args.depth))
