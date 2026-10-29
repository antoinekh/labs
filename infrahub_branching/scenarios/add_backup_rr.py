"""On a branch, give every PE that peers with a route reflector a session to a backup route reflector."""

import argparse
import asyncio

from infrahub_sdk import InfrahubClient

ASN = 64500


async def main(branch: str, drained: str, backup: str) -> None:
    client = InfrahubClient()
    drained_rr = await client.get(kind="NetDevice", name__value=drained, branch=branch, include=["bgp_sessions"])
    backup_rr = await client.get(kind="NetDevice", name__value=backup, branch=branch)
    backup_loopback = (await client.filters(kind="NetBgpSession", device__ids=[backup_rr.id], branch=branch, limit=1))[
        0
    ]
    sessions = await client.filters(
        kind="NetBgpSession", device__ids=[drained_rr.id], branch=branch, prefetch_relationships=True
    )
    added = 0
    for session in sessions:
        pe_session = await client.get(
            kind="NetBgpSession", id=session.peer.id, branch=branch, prefetch_relationships=True
        )
        pe = pe_session.device.peer
        pe_side = await client.create(
            kind="NetBgpSession",
            branch=branch,
            device=pe,
            local_ip=pe_session.local_ip.value,
            remote_ip=backup_loopback.local_ip.value,
            remote_as=ASN,
        )
        await pe_side.save()
        rr_side = await client.create(
            kind="NetBgpSession",
            branch=branch,
            device=backup_rr,
            local_ip=backup_loopback.local_ip.value,
            remote_ip=pe_session.local_ip.value,
            remote_as=ASN,
            peer=pe_side,
        )
        await rr_side.save()
        added += 1
    print(f"branch={branch} backup={backup} pe_sessions_added={added}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--drained", required=True)
    parser.add_argument("--backup", required=True)
    args = parser.parse_args()
    asyncio.run(main(branch=args.branch, drained=args.drained, backup=args.backup))
