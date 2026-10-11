#!/usr/bin/env python3
"""Assign every discovered UI test to a shard using recorded test durations."""

import json
import math
from pathlib import Path
import statistics
import sys


def select(timings_path: str, spec: str, tests: list[str]) -> list[str]:
    shard, count = map(int, spec.split("/"))
    if not 1 <= shard <= count or len(tests) != len(set(tests)):
        raise ValueError("invalid shard or duplicate discovered tests")
    profile = json.loads(Path(timings_path).read_text())
    durations = profile["durationSeconds"]
    if not isinstance(durations, dict) or not durations:
        raise ValueError("durationSeconds must contain recorded test durations")
    for name, seconds in durations.items():
        if (
            not isinstance(name, str)
            or isinstance(seconds, bool)
            or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds)
            or seconds <= 0
        ):
            raise ValueError("recorded durations must be finite positive numbers")
    # New tests and the opt-in long cases have no measured CI duration.
    # They still run: use the median until a later reference records them.
    fallback = statistics.median(durations.values())
    buckets: list[list[str]] = [[] for _ in range(count)]
    costs = [0.0] * count
    for name in sorted(tests, key=lambda name: (-durations.get(name, fallback), name)):
        target = min(range(count), key=lambda index: (costs[index], index))
        buckets[target].append(name)
        costs[target] += durations.get(name, fallback)
    return sorted(buckets[shard - 1])


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise ValueError("usage: balance-ui-shards.py <timings.json> <K/N>")
        selected = select(sys.argv[1], sys.argv[2], sys.stdin.read().splitlines())
        if selected:
            print("\n".join(selected))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"balance-ui-shards: {error}", file=sys.stderr)
        sys.exit(2)
