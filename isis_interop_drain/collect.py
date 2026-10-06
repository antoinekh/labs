#!/usr/bin/env python3
"""Collect and change the IS-IS state of the interop lab. Runs on the containerlab server.

Usage:
  collect.py state [pod ...]            print the border flags and the default routes
  collect.py set <pod> <mode>           change the border of a pod, then print its state
  collect.py raw <pod>:<role> <command> run show commands on one node (role: border, srsim, junos, frr)
  collect.py maxlink [reverse]          set 16777215, then 16777214, on the link of each L1 router to the border (pod srsim)
  collect.py matrix                     run every pod with every mode, save raw outputs in results/
Pods: srsim, frr, junos (the vendor of the L1/L2 border router).
Modes: none, overload, max-metric, overload-suppress-att (srsim only).
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

PODS = ["srsim", "frr", "junos"]
RECEIVER_VENDORS = ["srsim", "junos", "frr"]
LAB = "isis-interop-drain"  # containerlab lab name, used in the container names
SROS_PASSWORD = "NokiaSros1!"
JUNOS_PASSWORD = "admin@123"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10"]


class Vendor(Enum):
    SRSIM = "srsim"
    FRR = "frr"
    JUNOS = "junos"


@dataclass
class Node:
    name: str
    vendor: Vendor
    ip: str


def node(pod: str, role: str) -> Node:
    """Border (role 'border') or L1 router (role is the vendor) of a pod."""
    pod_index = PODS.index(pod) + 1
    if role == "border":
        return Node(f"{pod}-border", Vendor(pod), f"172.31.111.{pod_index}1")
    return Node(f"{pod}-l1{role}", Vendor(role), f"172.31.111.{pod_index}{RECEIVER_VENDORS.index(role) + 2}")


def run_cli(n: Node, commands: list[str]) -> str:
    """Run CLI commands on a node and return the raw output."""
    if n.vendor is Vendor.FRR:
        args = ["docker", "exec", f"clab-{LAB}-{n.name}", "vtysh"]
        for c in commands:
            args += ["-c", c]
        return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
    if n.vendor is Vendor.SRSIM:
        script = "environment more false\n" + "\n".join(commands) + "\nlogout\n"
        args = ["sshpass", "-p", SROS_PASSWORD, "ssh", "-tt", *SSH_OPTS, f"admin@{n.ip}"]
    else:
        script = "\n".join(commands) + "\n"
        args = ["sshpass", "-p", JUNOS_PASSWORD, "ssh", "-T", *SSH_OPTS, f"admin@{n.ip}"]
    return subprocess.run(args, input=script, capture_output=True, text=True, timeout=90).stdout


DB_CMD = {Vendor.SRSIM: "show router isis database", Vendor.FRR: "show isis database", Vendor.JUNOS: "show isis database"}
ROUTE_CMD = {
    Vendor.SRSIM: "show router route-table 0.0.0.0/0 exact",
    Vendor.FRR: "show ip route 0.0.0.0/0",
    Vendor.JUNOS: "show route 0.0.0.0/0 exact table inet.0",
}


def strip_prompts(out: str) -> str:
    """Remove the prompt lines, which echo the command that was sent."""
    return "\n".join(line for line in out.splitlines() if not re.match(r"^(A:)?\S*@\S*[>#]", line))


def border_flags(vendor: Vendor, db: str, border: str) -> str:
    """Flags (ATT, OL) of the L1 LSP of the border, as read in a database dump."""
    lines = db.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith(f"{border}.00-00"):
            continue
        if vendor is Vendor.FRR:
            m = re.search(r"(\d)/(\d)/(\d)\s*$", line)
            if m:
                att, _, ol = m.groups()
                return f"ATT={att} OL={ol}"
        # SR OS wraps the flags on a continuation line that starts with a space
        nxt = lines[i + 1] if i + 1 < len(lines) and lines[i + 1].startswith(" ") else ""
        text = line + " " + nxt
        if vendor is Vendor.SRSIM:
            return f"ATT={int('ATT' in text)} OL={int(re.search(r'\bOV\b', text) is not None)}"
        return f"ATT={int('Attached' in line)} OL={int('Overload' in line)}"
    return "no LSP"


def default_route(vendor: Vendor, out: str) -> str:
    """Summary of the IS-IS default route in a route-table dump."""
    if vendor is Vendor.SRSIM:
        m = re.search(r"No\. of Routes: (\d+)", out)
        if m and m.group(1) == "0":
            return "no"
        nh = re.search(r"^\s+(\d+\.\d+\.\d+\.\d+)\s+\S*\s*\d*\s*$", out, re.M)
        return f"yes via {nh.group(1)}" if nh else "yes"
    if vendor is Vendor.FRR:
        if "Routing entry for 0.0.0.0/0" not in out:
            return "no"
        nh = re.search(r"\* (\d+\.\d+\.\d+\.\d+)", out)
        return f"yes via {nh.group(1)}" if nh else "yes"
    if "0.0.0.0/0" not in out:
        return "no"
    nh = re.search(r"to (\d+\.\d+\.\d+\.\d+)", out)
    return f"yes via {nh.group(1)}" if nh else "yes"


def pod_state(pod: str, label: str = "") -> dict[str, str]:
    result: dict[str, str] = {}
    border = node(pod, "border")
    results_dir = Path("results") / f"{pod}-{label}"
    if label:
        results_dir.mkdir(parents=True, exist_ok=True)
    for role in RECEIVER_VENDORS:
        rx = node(pod, role)
        out = strip_prompts(run_cli(rx, [DB_CMD[rx.vendor], ROUTE_CMD[rx.vendor]]))
        if label:
            (results_dir / f"{rx.name}.txt").write_text(out)
        flags = border_flags(rx.vendor, out, border.name)
        result[role] = f"{default_route(rx.vendor, out)} (LSP {flags})"
    return result


def print_state(pods: list[str], label: str = "") -> None:
    for pod in pods:
        print(f"### border {pod} {label}")
        for role, text in pod_state(pod, label).items():
            print(f"- l1{role}: default route {text}")


NONE_CMDS = {
    Vendor.SRSIM: [
        "edit-config private",
        '/configure router "Base" isis 0 delete overload',
        '/configure router "Base" isis 0 delete suppress-attached-bit',
        "commit",
    ],
    Vendor.FRR: ["configure terminal", "router isis LAB", "no set-overload-bit", "no advertise-high-metrics"],
    Vendor.JUNOS: [
        "configure",
        "delete protocols isis overload",
        "commit and-quit",
    ],
}
MODE_CMDS = {
    (Vendor.SRSIM, "overload"): ["edit-config private", '/configure router "Base" isis 0 overload', "commit", "quit-config"],
    (Vendor.SRSIM, "max-metric"): [
        "edit-config private",
        '/configure router "Base" isis 0 overload max-metric true',
        "commit",
    ],
    (Vendor.SRSIM, "overload-suppress-att"): [
        "edit-config private",
        '/configure router "Base" isis 0 overload',
        '/configure router "Base" isis 0 suppress-attached-bit true',
        "commit",
    ],
    (Vendor.FRR, "overload"): ["configure terminal", "router isis LAB", "set-overload-bit"],
    (Vendor.FRR, "max-metric"): ["configure terminal", "router isis LAB", "advertise-high-metrics"],
    (Vendor.JUNOS, "overload"): ["configure", "set protocols isis overload", "commit and-quit"],
    (Vendor.JUNOS, "max-metric"): ["configure", "set protocols isis overload advertise-high-metrics", "commit and-quit"],
}


def set_mode(pod: str, mode: str) -> None:
    border = node(pod, "border")
    run_cli(border, NONE_CMDS[border.vendor])
    if mode != "none":
        run_cli(border, MODE_CMDS[(border.vendor, mode)])
    time.sleep(40)  # SPF delay and LSP flooding


def border_dump(pod: str, label: str) -> None:
    """Save the full L1 LSP of the border and the IS-IS status, as seen on the border itself."""
    border = node(pod, "border")
    cmds = {
        Vendor.SRSIM: ["show router isis database detail", "show router isis status"],
        Vendor.FRR: ["show isis database detail", "show isis summary"],
        Vendor.JUNOS: ["show isis database extensive", "show isis overview"],
    }[border.vendor]
    out = strip_prompts(run_cli(border, cmds))
    (Path("results") / f"{pod}-{label}" / f"{border.name}-self.txt").write_text(out)


def matrix() -> None:
    for pod in PODS:
        modes = ["none", "overload", "max-metric"] + (["overload-suppress-att"] if pod == "srsim" else [])
        for mode in modes:
            set_mode(pod, mode)
            print_state([pod], mode)
            border_dump(pod, mode)
            sys.stdout.flush()
        set_mode(pod, "none")


def link_metric_cmds(vendor: Vendor, border: str, metric: int | None) -> list[str]:
    """Commands that set (or remove, when metric is None) the L1 metric of the link to the border."""
    if vendor is Vendor.SRSIM:
        path = f'/configure router "Base" isis 0 interface "to-{border}" level 1'
        return ["edit-config private", f"{path} delete metric" if metric is None else f"{path} metric {metric}", "commit"]
    if vendor is Vendor.JUNOS:
        path = "protocols isis interface ge-0/0/0.0 level 1 metric"
        return ["configure", f"delete {path}" if metric is None else f"set {path} {metric}", "commit and-quit"]
    cmd = "no isis metric level-1" if metric is None else f"isis metric level-1 {metric}"
    return ["configure terminal", "interface eth1", cmd]


ROUTES_CMD = {Vendor.SRSIM: "show router route-table", Vendor.FRR: "show ip route isis", Vendor.JUNOS: "show route protocol isis"}


def border_link_metric_cmds(border: Node, metric: int | None) -> list[str]:
    """Set (or remove) the L1 metric on the three L1 links of an SR-SIM border."""
    cmds = ["edit-config private"]
    for role in RECEIVER_VENDORS:
        peer = node(border.name.removesuffix("-border"), role).name
        path = f'/configure router "Base" isis 0 interface "to-{peer}" level 1'
        cmds.append(f"{path} delete metric" if metric is None else f"{path} metric {metric}")
    return cmds + ["commit"]


def maxlink(pod: str = "srsim", reverse: bool = False) -> None:
    """Set a high metric on the links between the border and the L1 routers.

    Forward: on each L1 router, toward the border. Reverse: on the border, toward each L1 router.
    """
    border = node(pod, "border")
    direction = "reverse" if reverse else "forward"
    for metric in (16777215, 16777214, None):
        label = f"maxlink-{direction}-{metric or 'restore'}"
        out_dir = Path("results") / label
        out_dir.mkdir(parents=True, exist_ok=True)
        if reverse:
            run_cli(border, border_link_metric_cmds(border, metric))
        else:
            for role in RECEIVER_VENDORS:
                rx = node(pod, role)
                run_cli(rx, link_metric_cmds(rx.vendor, border.name, metric))
        time.sleep(40)
        print(f"### {direction} metric {metric or 'restored (10)'}")
        for n in [node(pod, r) for r in RECEIVER_VENDORS] + [border]:
            out = strip_prompts(run_cli(n, [DB_CMD[n.vendor], ROUTE_CMD[n.vendor], ROUTES_CMD[n.vendor]]))
            (out_dir / f"{n.name}.txt").write_text(out)
            if n is not border:
                print(f"- {n.name}: default route {default_route(n.vendor, out)}")
        sys.stdout.flush()


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] not in {"state", "set", "raw", "matrix", "maxlink"}:
        print(__doc__)
        sys.exit(1)
    if args[0] == "state":
        print_state(args[1:] or PODS)
    elif args[0] == "matrix":
        matrix()
    elif args[0] == "maxlink":
        maxlink(reverse="reverse" in args[1:])
    elif args[0] == "set":
        set_mode(args[1], args[2])
        print_state([args[1]], args[2])
        border_dump(args[1], args[2])
    else:
        pod, _, role = args[1].partition(":")
        print(run_cli(node(pod, role), args[2:]))


if __name__ == "__main__":
    main()
