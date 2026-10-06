#!/usr/bin/env python3
"""Generate the multi-border IS-IS interop lab (topology and startup configs).

Three independent pods share one L2 core. Each pod has one L1/L2 border router
of a different vendor and three L1 routers (SR-SIM, Junos, FRR).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

LAB_DIR = Path(__file__).parent
MGMT_SUBNET = "172.31.111.0/24"
# SR-SIM image and license: override with the SRSIM_IMAGE and SRSIM_LICENSE environment variables.
# The license is not included: save it next to the topology as license.txt (ignored by git).
SRSIM_IMAGE = os.environ.get("SRSIM_IMAGE", "nokia_srsim:26.3.R1")
SRSIM_LICENSE = os.environ.get("SRSIM_LICENSE", "license.txt")
JUNOS_IMAGE = "vrnetlab/juniper_vjunos-router:23.4R2-S6.9"
FRR_IMAGE = "quay.io/frrouting/frr:10.2.5"
JUNOS_ADMIN_HASH = "$6$O7juqF0W$Sq1Qi4.G1UQHnRn7FLjEZM8KgC7nW40babgsBo3f631SKlb3G9E3gk7T4h9.KaW1jIms9E5h8V/lQetEgJhAi/"
JUNOS_ROOT_HASH = "$6$APKoGjlf$eqyC5C5kHcWU7OWRy3J9ftfZJ/AMsROvDTT/NV4RelyhwGf0vpjgm42rKNk3weKEkm4kk4A5TIzlIZOJcQQUm/"


class Vendor(Enum):
    SRSIM = "srsim"
    FRR = "frr"
    JUNOS = "junos"


class Level(Enum):
    L1 = 1
    L2 = 2


@dataclass
class Iface:
    index: int  # 0-based position on the router
    peer: str
    address: str  # a.b.c.d (prefix length is always 30)
    level: Level

    def name(self, vendor: Vendor) -> str:
        """Interface name as used in the topology links."""
        if vendor is Vendor.SRSIM:
            return f"1/1/c{self.index + 1}/1"
        if vendor is Vendor.JUNOS:
            return f"ge-0/0/{self.index}"
        return f"eth{self.index + 1}"


@dataclass
class Router:
    name: str
    vendor: Vendor
    mgmt_ip: str
    loopback: str
    system_id: str
    area: str
    levels: tuple[Level, ...]
    ifaces: list[Iface] = field(default_factory=list)

    @property
    def net(self) -> str:
        return f"{self.area}.{self.system_id}.00"


def system_id(pod: int, n: int) -> str:
    """System ID of router n in a pod (pod 0 is the L2 core)."""
    return f"0000.000{pod}.000{n}"


def build_routers() -> tuple[list[Router], list[tuple[str, str]]]:
    """Return the routers and the links as (node:iface, node:iface) pairs."""
    routers: list[Router] = []
    links: list[tuple[str, str]] = []
    core = Router("l2core", Vendor.FRR, "172.31.111.10", "10.255.0.1", "0000.0000.0001", "49.0100", (Level.L2,))
    routers.append(core)
    receiver_vendors = [Vendor.SRSIM, Vendor.JUNOS, Vendor.FRR]
    for pod, border_vendor in enumerate([Vendor.SRSIM, Vendor.FRR, Vendor.JUNOS], start=1):
        area = f"49.001{pod}"
        border = Router(
            f"{border_vendor.value}-border", border_vendor, f"172.31.111.{pod}1", f"10.255.{pod}.1", system_id(pod, 1), area,
            (Level.L1, Level.L2),
        )
        routers.append(border)
        core_if = Iface(len(core.ifaces), border.name, f"10.{pod}.0.1", Level.L2)
        core.ifaces.append(core_if)
        border.ifaces.append(Iface(0, core.name, f"10.{pod}.0.2", Level.L2))
        links.append((f"{core.name}:{core_if.name(core.vendor)}", f"{border.name}:{border.ifaces[0].name(border.vendor)}"))
        for n, rv in enumerate(receiver_vendors, start=2):
            rx = Router(
                f"{border_vendor.value}-l1{rv.value}", rv, f"172.31.111.{pod}{n}", f"10.255.{pod}.{n}", system_id(pod, n), area,
                (Level.L1,),
            )
            routers.append(rx)
            subnet = n - 1
            b_if = Iface(len(border.ifaces), rx.name, f"10.{pod}.{subnet}.1", Level.L1)
            border.ifaces.append(b_if)
            rx_if = Iface(0, border.name, f"10.{pod}.{subnet}.2", Level.L1)
            rx.ifaces.append(rx_if)
            links.append((f"{border.name}:{b_if.name(border.vendor)}", f"{rx.name}:{rx_if.name(rx.vendor)}"))
    return routers, links


def render_srsim(r: Router) -> str:
    lines = [
        f'/configure system name "{r.name}"',
        "/configure card 1 card-type iom-1",
        "/configure card 1 mda 1 mda-type me6-100gb-qsfp28",
        "/configure card 1 mda 2 mda-type me12-100gb-qsfp28",
    ]
    for i in r.ifaces:
        c = i.index + 1
        lines += [
            f"/configure port 1/1/c{c} connector breakout c1-100g",
            f"/configure port 1/1/c{c} admin-state enable",
            f"/configure port 1/1/c{c}/1 ethernet mode hybrid",
            f"/configure port 1/1/c{c}/1 admin-state enable",
        ]
    lines += [
        f'/configure router "Base" interface "system" ipv4 primary address {r.loopback}',
        '/configure router "Base" interface "system" ipv4 primary prefix-length 32',
    ]
    for i in r.ifaces:
        lines += [
            f'/configure router "Base" interface "to-{i.peer}" port 1/1/c{i.index + 1}/1:0',
            f'/configure router "Base" interface "to-{i.peer}" ipv4 primary address {i.address}',
            f'/configure router "Base" interface "to-{i.peer}" ipv4 primary prefix-length 30',
        ]
    cap = "1/2" if len(r.levels) == 2 else str(r.levels[0].value)
    lines += [
        '/configure router "Base" isis 0 admin-state enable',
        f'/configure router "Base" isis 0 level-capability {cap}',
        f'/configure router "Base" isis 0 system-id {r.system_id}',
        f'/configure router "Base" isis 0 area-address [{r.area}]',
    ]
    for lvl in r.levels:
        lines.append(f'/configure router "Base" isis 0 level {lvl.value} wide-metrics-only true')
    lines.append('/configure router "Base" isis 0 interface "system" passive true')
    for i in r.ifaces:
        lines += [
            f'/configure router "Base" isis 0 interface "to-{i.peer}" interface-type point-to-point',
            f'/configure router "Base" isis 0 interface "to-{i.peer}" level-capability {i.level.value}',
        ]
    return "\n".join(lines) + "\n"


def render_frr(r: Router) -> str:
    out = [f"hostname {r.name}", "!", "interface lo", f" ip address {r.loopback}/32", " ip router isis LAB", " isis passive", "!"]
    for i in r.ifaces:
        out += [
            f"interface {i.name(Vendor.FRR)}",
            f" ip address {i.address}/30",
            " ip router isis LAB",
            f" isis circuit-type level-{i.level.value}{'-only' if i.level is Level.L2 else ''}",
            " isis network point-to-point",
            " no isis hello padding",
            "!",
        ]
    is_type = "level-1-2" if len(r.levels) == 2 else f"level-{r.levels[0].value}{'-only' if r.levels[0] is Level.L2 else ''}"
    out += ["router isis LAB", f" net {r.net}", f" is-type {is_type}", " metric-style wide", "!"]
    return "\n".join(out) + "\n"


FRR_DAEMONS = """zebra=yes
isisd=yes
bgpd=no
ospfd=no
ospf6d=no
ripd=no
ripngd=no
pimd=no
ldpd=no
nhrpd=no
"""


def render_junos(r: Router) -> str:
    ifaces = ""
    isis_ifaces = ""
    for i in r.ifaces:
        name = i.name(Vendor.JUNOS)
        ifaces += f"""    {name} {{
        unit 0 {{
            family inet {{
                address {i.address}/30;
            }}
            family iso;
        }}
    }}
"""
        disabled = Level.L1 if i.level is Level.L2 else Level.L2
        isis_ifaces += f"""        interface {name}.0 {{
            point-to-point;
            level {disabled.value} disable;
        }}
"""
    levels = "".join(f"        level {lvl.value} wide-metrics-only;\n" for lvl in r.levels)
    disabled_levels = "".join(
        f"        level {lvl.value} disable;\n" for lvl in (Level.L1, Level.L2) if lvl not in r.levels
    )
    return f"""version 23.4R2-S6.9;
system {{
    host-name {r.name};
    root-authentication {{
        encrypted-password "{JUNOS_ROOT_HASH}"; ## SECRET-DATA
    }}
    login {{
        user admin {{
            uid 2000;
            class super-user;
            authentication {{
                encrypted-password "{JUNOS_ADMIN_HASH}"; ## SECRET-DATA
            }}
        }}
    }}
    services {{
        netconf {{
            ssh;
        }}
        ssh {{
            root-login allow;
        }}
    }}
    management-instance;
}}
chassis {{
    fpc 0 {{
        pic 0 {{
            number-of-ports 12;
        }}
    }}
}}
interfaces {{
{ifaces}    fxp0 {{
        unit 0 {{
            family inet {{
                address 10.0.0.15/24;
            }}
            family inet6 {{
                address 2001:db8::2/64;
            }}
        }}
    }}
    lo0 {{
        unit 0 {{
            family inet {{
                address {r.loopback}/32;
            }}
            family iso {{
                address {r.net};
            }}
        }}
    }}
}}
routing-instances {{
    mgmt_junos {{
        routing-options {{
            rib mgmt_junos.inet6.0 {{
                static {{
                    route ::/0 next-hop 2001:db8::1;
                }}
            }}
            static {{
                route 0.0.0.0/0 next-hop 10.0.0.2;
            }}
        }}
    }}
}}
protocols {{
    isis {{
{isis_ifaces}        interface lo0.0 {{
            passive;
        }}
{disabled_levels}{levels}    }}
}}
"""


def render_topology(
    routers: list[Router],
    links: list[tuple[str, str]],
    name: str = "isis-interop-drain",
    network: str = "isis_interop_drain_mgmt",
    subnet: str = MGMT_SUBNET,
    license_path: str = SRSIM_LICENSE,
) -> str:
    out = f"""name: {name}

mgmt:
  network: {network}
  ipv4-subnet: {subnet}

topology:
  kinds:
    nokia_srsim:
      image: {SRSIM_IMAGE}
      type: sr-1
      license: {license_path}
    juniper_vjunosrouter:
      image: {JUNOS_IMAGE}

  nodes:
"""
    for r in routers:
        out += f"    {r.name}:\n"
        if r.vendor is Vendor.SRSIM:
            out += f"      kind: nokia_srsim\n      mgmt-ipv4: {r.mgmt_ip}\n      startup-config: configs/{r.name}.partial.cfg\n"
        elif r.vendor is Vendor.JUNOS:
            out += f"      kind: juniper_vjunosrouter\n      mgmt-ipv4: {r.mgmt_ip}\n      startup-config: configs/{r.name}.conf\n"
        else:
            out += f"""      kind: linux
      image: {FRR_IMAGE}
      mgmt-ipv4: {r.mgmt_ip}
      binds:
        - configs/{r.name}/daemons:/etc/frr/daemons
        - configs/{r.name}/frr.conf:/etc/frr/frr.conf
      exec:
        - ip route del default dev eth0
"""
    out += "\n  links:\n"
    for a, b in links:
        out += f'    - endpoints: ["{a}", "{b}"]\n'
    return out


def main() -> None:
    routers, links = build_routers()
    configs = LAB_DIR / "configs"
    shutil.rmtree(configs, ignore_errors=True)
    configs.mkdir()
    for r in routers:
        if r.vendor is Vendor.SRSIM:
            (configs / f"{r.name}.partial.cfg").write_text(render_srsim(r))
        elif r.vendor is Vendor.JUNOS:
            (configs / f"{r.name}.conf").write_text(render_junos(r))
        else:
            (configs / r.name).mkdir()
            (configs / r.name / "daemons").write_text(FRR_DAEMONS)
            (configs / r.name / "frr.conf").write_text(render_frr(r))
    (LAB_DIR / "isis_interop_drain.clab.yml").write_text(render_topology(routers, links))


if __name__ == "__main__":
    main()
