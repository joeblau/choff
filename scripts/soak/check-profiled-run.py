#!/usr/bin/env python3
"""Validate the separate CI leak-profiling run without accepting its timing metrics.

The preceding, unprofiled run must pass all eight standard soak checks. This
run still requires a complete test, all five correctness checks and zero leak
growth. Only the three observer-sensitive measurement failures are diagnostic.
"""

import argparse
import json
import sys
from pathlib import Path

MEASUREMENTS = {"memory.slope", "asr.chunkLatency", "realtime.firstAudio"}
CORRECTNESS = {
    "capture.droppedFrames", "conversation.complete", "realtime.rollover",
    "voiceid.background", "topics.count",
}


def validate(report, leaks, summary, minutes, status):
    checks = report["checks"]
    names = [check["name"] for check in checks]
    if len(names) != 8 or set(names) != MEASUREMENTS | CORRECTNESS:
        raise ValueError("the run must report every soak check exactly once")
    if any(type(check["passed"]) is not bool for check in checks):
        raise ValueError("invalid check verdict")
    failed = {check["name"] for check in checks if not check["passed"]}
    if failed & CORRECTNESS:
        raise ValueError("correctness checks failed: " + ", ".join(sorted(failed & CORRECTNESS)))
    if report["setup"]["audioSeconds"] < minutes * 60 or len(report["samples"]) < 3:
        raise ValueError("the requested session did not finish")
    if summary["totalTestCount"] != 1 or summary["skippedTests"] != 0 or summary["expectedFailures"] != 0:
        raise ValueError("expected one completed soak test, without skips or runner errors")
    failures = summary.get("testFailures", [])
    if failed:
        if status not in (1, 2) or summary["failedTests"] != 1 or summary["passedTests"] != 0 or len(failures) != 1:
            raise ValueError("the test failure does not match the diagnostic measurements")
        failure = failures[0]
        text = failure["failureText"]
        if (failure["testIdentifierString"] != "SoakTests/testLongSession()"
                or not text.startswith('XCTAssertEqual failed: ("failed: ')
                or not text.endswith('is not equal to ("passed") - The soak failed; see the attached report')):
            raise ValueError("unexpected XCTest failure")
        reported = text.split('("failed: ', 1)[1].split('")', 1)[0]
        if set(reported.split(", ")) != failed:
            raise ValueError("XCTest failure and report disagree")
    elif status != 0 or summary["passedTests"] != 1 or summary["failedTests"] != 0 or failures:
        raise ValueError("the soak command or test failed despite passing report checks")
    readings = sorted(leaks["readings"], key=lambda reading: reading["wall"])
    if (len(readings) < 2 or readings[0]["phase"] != "during-run" or readings[-1]["phase"] != "after-run"
            or readings[0]["wall"] >= readings[-1]["wall"]
            or len({reading["pid"] for reading in readings}) != 1):
        raise ValueError("need during-run and after-run leak readings from the same process")
    if (leaks["passed"] is not True or leaks["toleranceLeaks"] != 0 or leaks["toleranceBytes"] != 0
            or readings[-1]["leaks"] > readings[0]["leaks"]
            or readings[-1]["bytes"] > readings[0]["bytes"]):
        raise ValueError("leaked memory grew or leak tolerances changed")
    return failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--minutes", type=float, required=True)
    parser.add_argument("--status", type=int, required=True)
    args = parser.parse_args()
    try:
        report, leaks, summary = [json.loads((args.directory / name).read_text())
                                  for name in ("report.json", "leaks.json", "test-summary.json")]
        failed = validate(report, leaks, summary, args.minutes, args.status)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"profiled-soak: FAILED: {error}", file=sys.stderr)
        return 1
    print("profiled-soak: completed; all five correctness checks passed; no leak growth")
    if failed:
        print("Diagnostic measurement failures (acceptance uses the unprofiled run): " + ", ".join(sorted(failed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
