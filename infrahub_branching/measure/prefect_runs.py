"""Summarise queue and run time of Prefect flow runs whose name matches a pattern, from a JSON export."""

import json
import sys
from datetime import datetime


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def percentile(values: list[float], fraction: float) -> float:
    return values[min(len(values) - 1, int(len(values) * fraction))]


runs = [run for run in json.load(open(sys.argv[1])) if run["end_time"]]
queue = sorted((parse(r["start_time"]) - parse(r["created"])).total_seconds() for r in runs)
run = sorted((parse(r["end_time"]) - parse(r["start_time"])).total_seconds() for r in runs)
for name, values in (("queue", queue), ("run", run)):
    print(
        f"{name}: n={len(values)} min={values[0]:.2f} median={percentile(values, 0.5):.2f} p90={percentile(values, 0.9):.2f} max={values[-1]:.2f}"
    )
