"""Delete every branch whose name starts with a prefix."""

import argparse
import asyncio

from infrahub_sdk import InfrahubClient


async def main(prefix: str) -> None:
    client = InfrahubClient()
    branches = await client.branch.all()
    names = [name for name in branches if name.startswith(prefix)]
    for name in names:
        await client.branch.delete(name)
    print(f"deleted={len(names)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix")
    asyncio.run(main(parser.parse_args().prefix))
