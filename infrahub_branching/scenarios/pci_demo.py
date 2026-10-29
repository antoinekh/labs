"""Steps of the PCI-DSS firewall demo: add the firewalls, onboard a PCI service, fix its attachment."""

import argparse
import asyncio

from infrahub_sdk import InfrahubClient

PE = "pe-par-01"
SERVICE = "svc-pe-par-01-1"
# Firewall name, PCI-DSS certified, firewall port, PE port, /31 subnet.
FIREWALLS = [
    ("fw-par-01", True, "eth1", "1/1/c3", "172.31.255.0/31"),
    ("fw-par-02", False, "eth1", "1/1/c4", "172.31.255.2/31"),
]


async def add_firewalls(client: InfrahubClient, branch: str) -> None:
    pe = await client.get(kind="NetDevice", name__value=PE, branch=branch)
    for name, certified, fw_port, pe_port, subnet in FIREWALLS:
        firewall = await client.create(
            kind="NetDevice",
            name=name,
            site=pe.site.value,
            role="firewall",
            asn=pe.asn.value,
            pci_certified=certified,
            branch=branch,
        )
        await firewall.save()
        base = subnet.split("/")[0].rsplit(".", 1)
        ends = []
        for device, port, host in ((firewall, fw_port, int(base[1])), (pe, pe_port, int(base[1]) + 1)):
            interface = await client.create(
                kind="NetInterface", name=port, ip_address=f"{base[0]}.{host}/31", device=device, branch=branch
            )
            await interface.save()
            ends.append(interface)
        interco = await client.create(
            kind="NetInterco", name=f"{name}--{PE}", subnet=subnet, interfaces=ends, branch=branch
        )
        await interco.save()
        print(f"{name}: pci_certified={certified}, linked to {PE} on {branch}")


async def onboard(client: InfrahubClient, branch: str) -> None:
    service = await client.get(kind="NetAppService", name__value=SERVICE, branch=branch)
    await service.devices.fetch()
    firewall = await client.get(kind="NetDevice", name__value="fw-par-02", branch=branch)
    service.compliance.value = "pci_dss"
    service.devices.add(firewall)
    await service.save()
    print(f"{SERVICE}: compliance=pci_dss, attached to {PE} and fw-par-02 on {branch}")


async def fix(client: InfrahubClient, branch: str) -> None:
    service = await client.get(kind="NetAppService", name__value=SERVICE, branch=branch)
    await service.devices.fetch()
    firewall = await client.get(kind="NetDevice", name__value="fw-par-01", branch=branch)
    for peer in list(service.devices.peers):
        service.devices.remove(peer.id)
    service.devices.add(firewall)
    await service.save()
    print(f"{SERVICE}: attached only to fw-par-01 on {branch}")


async def main(step: str, branch: str) -> None:
    client = InfrahubClient()
    if step == "firewalls":
        await add_firewalls(client, branch)
    elif step == "onboard":
        await onboard(client, branch)
    elif step == "fix":
        await fix(client, branch)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=["firewalls", "onboard", "fix"])
    parser.add_argument("--branch", default="main")
    args = parser.parse_args()
    asyncio.run(main(step=args.step, branch=args.branch))
