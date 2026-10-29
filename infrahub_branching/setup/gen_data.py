"""Generate a small ISP backbone in the Net schema: routers, intercos, iBGP sessions and application services."""

import argparse
import asyncio
import ipaddress
import time
from dataclasses import dataclass, field

from infrahub_sdk import InfrahubClient
from infrahub_sdk.node import InfrahubNode

ASN = 64500
SITE_NAMES = ["par", "lys", "mrs", "bdx", "lil", "nte", "stg", "tls", "nce", "ren"]
INTERCO_POOL = ipaddress.ip_network("10.0.0.0/8")
LOOPBACK_POOL = ipaddress.ip_network("192.168.0.0/16")


LINKS_PER_SITE = 16
DEVICES_PER_SITE = 8


@dataclass
class Site:
    index: int
    name: str
    p: list[str] = field(default_factory=list)
    pe: list[str] = field(default_factory=list)
    rr: str = ""


def site_name(index: int) -> str:
    base = SITE_NAMES[index % len(SITE_NAMES)]
    return base if index < len(SITE_NAMES) else f"{base}{index // len(SITE_NAMES)}"


def build_sites(first: int, count: int) -> list[Site]:
    sites = []
    for index in range(first, first + count):
        name = site_name(index)
        sites.append(
            Site(
                index=index,
                name=name,
                p=[f"p-{name}-0{i}" for i in (1, 2)],
                pe=[f"pe-{name}-0{i}" for i in (1, 2, 3, 4)],
                rr=f"rr-{name}-01",
            )
        )
    return sites


def site_links(site: Site, following: Site | None) -> list[tuple[str, str]]:
    """Each PE dual-homes to the two local P, the RR to both local P, and the P chain to the next site."""
    result = [(site.p[0], site.p[1])]
    for pe in site.pe:
        result.extend((pe, p) for p in site.p)
    result.extend((site.rr, p) for p in site.p)
    if following:
        result.extend([(site.p[0], following.p[0]), (site.p[1], following.p[1])])
    return result


def loopback(site: Site, position: int) -> str:
    """Addresses derive from the site index so that later runs can add sites without overlap."""
    return str(LOOPBACK_POOL[site.index * DEVICES_PER_SITE + position + 1])


def route_reflectors_for(site: Site) -> list[str]:
    """Each PE peers with its local RR and with the RR of the first site, or of the second one for the first site."""
    remote = f"rr-{site_name(1 if site.index == 0 else 0)}-01"
    return [site.rr, remote]


async def save_all(client: InfrahubClient, nodes: list[InfrahubNode]) -> None:
    batch = await client.create_batch()
    for node in nodes:
        batch.add(task=node.save, node=node)
    async for _ in batch.execute():
        pass


async def main(first_site: int, sites_count: int, services_per_pe: int) -> None:
    client = InfrahubClient()
    sites = build_sites(first_site, sites_count)
    started = time.monotonic()

    devices: dict[str, InfrahubNode] = {}
    loopbacks: dict[str, str] = {}
    for site in sites:
        names = [(p, "core") for p in site.p] + [(pe, "pe") for pe in site.pe] + [(site.rr, "rr")]
        for position, (name, role) in enumerate(names):
            devices[name] = await client.create(kind="NetDevice", name=name, site=site.name, role=role, asn=ASN)
            loopbacks[name] = loopback(site, position)
    await save_all(client, list(devices.values()))

    for site in sites:
        for rr in route_reflectors_for(site):
            if rr not in devices:
                devices[rr] = await client.get(kind="NetDevice", name__value=rr)
                rr_site_index = 0 if rr == f"rr-{site_name(0)}-01" else 1
                loopbacks[rr] = loopback(Site(index=rr_site_index, name=""), DEVICES_PER_SITE - 2)

    interfaces: list[InfrahubNode] = []
    intercos: list[InfrahubNode] = []
    port_counter: dict[str, int] = dict.fromkeys(devices, 0)
    for site, following in zip(sites, [*sites[1:], None]):
        for link_index, (a_name, b_name) in enumerate(site_links(site, following)):
            subnet = ipaddress.ip_network(f"{INTERCO_POOL[(site.index * LINKS_PER_SITE + link_index) * 2]}/31")
            ends = []
            for device_name, address in ((a_name, subnet[0]), (b_name, subnet[1])):
                port_counter[device_name] += 1
                ends.append(
                    await client.create(
                        kind="NetInterface",
                        name=f"1/1/c{port_counter[device_name]}",
                        ip_address=f"{address}/31",
                        device=devices[device_name],
                    )
                )
            interfaces.extend(ends)
            intercos.append(
                await client.create(kind="NetInterco", name=f"{a_name}--{b_name}", subnet=str(subnet), interfaces=ends)
            )
    await save_all(client, interfaces)
    await save_all(client, intercos)

    pe_side: list[InfrahubNode] = []
    rr_side: list[InfrahubNode] = []
    for site in sites:
        for pe in site.pe:
            for rr in route_reflectors_for(site):
                pe_session = await client.create(
                    kind="NetBgpSession",
                    device=devices[pe],
                    local_ip=loopbacks[pe],
                    remote_ip=loopbacks[rr],
                    remote_as=ASN,
                )
                pe_side.append(pe_session)
                rr_side.append(
                    await client.create(
                        kind="NetBgpSession",
                        device=devices[rr],
                        local_ip=loopbacks[rr],
                        remote_ip=loopbacks[pe],
                        remote_as=ASN,
                        peer=pe_session,
                    )
                )
    await save_all(client, pe_side)
    await save_all(client, rr_side)

    services: list[InfrahubNode] = []
    criticalities = ["low", "high", "critical"]
    for site in sites:
        for pe_index, pe in enumerate(site.pe):
            for service_index in range(services_per_pe):
                services.append(
                    await client.create(
                        kind="NetAppService",
                        name=f"svc-{pe}-{service_index + 1}",
                        owner=f"team-{site.name}",
                        criticality=criticalities[(pe_index + service_index) % len(criticalities)],
                        devices=[devices[pe]],
                    )
                )
    await save_all(client, services)

    elapsed = time.monotonic() - started
    print(
        f"sites={len(sites)} devices={len(devices)} interfaces={len(interfaces)} intercos={len(intercos)} "
        f"bgp_sessions={len(pe_side) + len(rr_side)} services={len(services)} seconds={elapsed:.1f}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sites", type=int, default=2)
    parser.add_argument("--first-site", type=int, default=0)
    parser.add_argument("--services-per-pe", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(main(first_site=args.first_site, sites_count=args.sites, services_per_pe=args.services_per_pe))
