#!/usr/bin/env python3
"""Read the default-route next hops of the three L1 routers in the two-exit lab without border-junos.

Usage:
  state_two_exit_nj.py <label>
"""

import sys
from pathlib import Path

import collect
import collect_two_exit as two_exit
from collect import Node, Vendor

collect.LAB = "isis-two-exit-nj"
two_exit.RECEIVERS = [
    Node("l1-srsim", Vendor.SRSIM, "172.31.114.21"),
    Node("l1-junos", Vendor.JUNOS, "172.31.114.22"),
    Node("l1-frr", Vendor.FRR, "172.31.114.23"),
]
two_exit.RESULTS = Path("results-two-exit-nj")

if len(sys.argv) != 2:
    print(__doc__)
    sys.exit(1)
two_exit.state(Node("border-frr", Vendor.FRR, "172.31.114.12"), sys.argv[1])
