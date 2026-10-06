#!/usr/bin/env python3
"""Generate the two-exit lab: three L1/L2 borders and three L1 routers, every L1 router linked to every border.

All metrics are 10, so each L1 router has an equal-cost default route through each border that sets ATT.
The next-hop list of the default route shows which borders an L1 router still uses.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from gen import (
    FRR_DAEMONS,
    SRSIM_LICENSE,
    Iface,
    Level,
    Router,
    Vendor,
    render_frr,
    render_junos,
    render_srsim,
    render_topology,
)

OUT_DIR = Path(__file__).parent / "two_exit"
BORDERS = [Vendor.SRSIM, Vendor.FRR, Vendor.JUNOS]
RECEIVERS = [Vendor.SRSIM, Vendor.JUNOS, Vendor.FRR]
AREA = "49.0011"


def build() -> tuple[list[Router], list[tuple[str, str]]]:
    core = Router("l2core", Vendor.FRR, "172.31.112.10", "10.255.0.1", "0000.0000.0001", "49.0100", (Level.L2,))
    routers = [core]
    links: list[tuple[str, str]] = []
    borders: list[Router] = []
    for b, bv in enumerate(BORDERS, start=1):
        border = Router(f"border-{bv.value}", bv, f"172.31.112.1{b}", f"10.255.{b}.1", f"0000.000{b}.0001", AREA, (Level.L1, Level.L2))
        core_if = Iface(len(core.ifaces), border.name, f"10.{b}.0.1", Level.L2)
        core.ifaces.append(core_if)
        border.ifaces.append(Iface(0, core.name, f"10.{b}.0.2", Level.L2))
        links.append((f"{core.name}:{core_if.name(core.vendor)}", f"{border.name}:{border.ifaces[0].name(border.vendor)}"))
        borders.append(border)
        routers.append(border)
    for r, rv in enumerate(RECEIVERS, start=1):
        rx = Router(f"l1-{rv.value}", rv, f"172.31.112.2{r}", f"10.255.9.{r}", f"0000.0009.000{r}", AREA, (Level.L1,))
        routers.append(rx)
        for b, border in enumerate(borders, start=1):
            b_if = Iface(len(border.ifaces), rx.name, f"10.{b}.{r}.1", Level.L1)
            border.ifaces.append(b_if)
            rx_if = Iface(len(rx.ifaces), border.name, f"10.{b}.{r}.2", Level.L1)
            rx.ifaces.append(rx_if)
            links.append((f"{border.name}:{b_if.name(border.vendor)}", f"{rx.name}:{rx_if.name(rx.vendor)}"))
    return routers, links


def main() -> None:
    routers, links = build()
    configs = OUT_DIR / "configs"
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    configs.mkdir(parents=True)
    for r in routers:
        if r.vendor is Vendor.SRSIM:
            ecmp = '/configure router "Base" ecmp 3\n'  # let SR OS install three next hops
            (configs / f"{r.name}.partial.cfg").write_text(render_srsim(r) + ecmp)
        elif r.vendor is Vendor.JUNOS:
            (configs / f"{r.name}.conf").write_text(render_junos(r))
        else:
            (configs / r.name).mkdir()
            (configs / r.name / "daemons").write_text(FRR_DAEMONS)
            (configs / r.name / "frr.conf").write_text(render_frr(r))
    # the topology is one level down, in two_exit/: a relative license path must go up one level
    license_path = SRSIM_LICENSE if Path(SRSIM_LICENSE).is_absolute() else f"../{SRSIM_LICENSE}"
    topology = render_topology(routers, links, "isis-two-exit", "isis_two_exit_mgmt", "172.31.112.0/24", license_path)
    (OUT_DIR / "isis_two_exit.clab.yml").write_text(topology)


if __name__ == "__main__":
    main()
