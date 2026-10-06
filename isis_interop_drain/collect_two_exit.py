#!/usr/bin/env python3
"""Drain one border at a time in the two-exit lab and show the default-route next hops of the L1 routers.

Usage:
  collect_two_exit.py state              next hops of the default route on each L1 router
  collect_two_exit.py matrix             every border with every mode, saves raw outputs in results-two-exit/
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import collect
from collect import DB_CMD, MODE_CMDS, NONE_CMDS, ROUTE_CMD, Node, Vendor, border_flags, run_cli, strip_prompts

collect.LAB = "isis-two-exit"
BORDERS = [Node(f"border-{v.value}", v, f"172.31.112.1{i}") for i, v in enumerate(Vendor, start=1)]
RECEIVERS = [Node(f"l1-{v}", Vendor(v), f"172.31.112.2{i}") for i, v in enumerate(["srsim", "junos", "frr"], start=1)]
RESULTS = Path("results-two-exit")
# the second octet of the link address (10.<border>.<receiver>.x) tells which border is the next hop
BORDER_BY_OCTET = {str(i): b.name for i, b in enumerate(BORDERS, start=1)}


def next_hops(vendor: Vendor, out: str) -> list[str]:
    """Border names used as next hops of the default route."""
    if vendor is Vendor.SRSIM:
        ips = re.findall(r"^\s+(\d+\.\d+\.\d+\.\d+)\s+\d+\s*$", out, re.M)
    elif vendor is Vendor.FRR:
        ips = re.findall(r"\* (\d+\.\d+\.\d+\.\d+),", out)
    else:
        ips = re.findall(r"to (\d+\.\d+\.\d+\.\d+) via", out)
    return sorted(BORDER_BY_OCTET[ip.split(".")[1]] for ip in ips)


def state(border: Node, label: str) -> None:
    print(f"### drained {border.name}: {label}")
    out_dir = RESULTS / f"{border.name}-{label}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for rx in RECEIVERS:
        out = strip_prompts(run_cli(rx, [DB_CMD[rx.vendor], ROUTE_CMD[rx.vendor]]))
        (out_dir / f"{rx.name}.txt").write_text(out)
        hops = ", ".join(h.removeprefix("border-") for h in next_hops(rx.vendor, out)) or "none"
        print(f"- {rx.name}: default route via [{hops}] (LSP of {border.name}: {border_flags(rx.vendor, out, border.name)})")
    sys.stdout.flush()


def set_mode(border: Node, mode: str) -> None:
    run_cli(border, NONE_CMDS[border.vendor])
    if mode != "none":
        run_cli(border, MODE_CMDS[(border.vendor, mode)])
    time.sleep(40)  # flooding and SPF


def matrix() -> None:
    for border in BORDERS:
        modes = ["none", "overload", "max-metric"] + (["overload-suppress-att"] if border.vendor is Vendor.SRSIM else [])
        for mode in modes:
            set_mode(border, mode)
            state(border, mode)
        set_mode(border, "none")


def reparse() -> None:
    """Print the matrix again from the saved raw outputs, without touching the lab."""
    for border_dir in sorted(RESULTS.iterdir()):
        border = next(b for b in BORDERS if border_dir.name.startswith(b.name))
        label = border_dir.name.removeprefix(f"{border.name}-")
        print(f"### drained {border.name}: {label}")
        for rx in RECEIVERS:
            out = (border_dir / f"{rx.name}.txt").read_text()
            hops = ", ".join(h.removeprefix("border-") for h in next_hops(rx.vendor, out)) or "none"
            print(f"- {rx.name}: default route via [{hops}] (LSP of {border.name}: {border_flags(rx.vendor, out, border.name)})")


def main() -> None:
    if sys.argv[1:] == ["reparse"]:
        reparse()
    elif sys.argv[1:] == ["state"]:
        state(BORDERS[0], "none")
    elif sys.argv[1:] == ["matrix"]:
        matrix()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
