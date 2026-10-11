#!/usr/bin/env python3
"""Attach Time Profiler to the original expansion test on its own simulator.

These instrumented timings are diagnostic evidence, not acceptance results.
Failure to attach never terminates or replaces the original test producer.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


SOURCE_PATHS = (
    "Blau/Timeline/TopicActionsLayout.swift",
    "Blau/Timeline/TopicDetail.swift",
    "Blau/Timeline/TopicTimelineView.swift",
    "BlauUITests/TopicDetailUITests.swift",
    "Packages/BlauKit/Sources/BlauTelemetry/Log.swift",
    "Packages/BlauKit/Sources/BlauTelemetry/Signposts.swift",
)


def app_pids(udid):
    rows = subprocess.check_output(["ps", "-axo", "pid=,comm="], text=True)
    return {
        int(row.split(None, 1)[0])
        for row in rows.splitlines()
        if f"/Devices/{udid}/" in row
        and row.rstrip().endswith("/Choff.app/Choff")
    }


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def hashes(root):
    return {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in SOURCE_PATHS
    }


def profile(root, udid, output, observe_seconds=600, test_command=None, trace_command=None):
    root = Path(root).resolve()
    output = Path(output).resolve()
    # A fresh directory prevents accidentally reusing an earlier trace/result.
    output.mkdir(parents=True, exist_ok=False)
    result_path = output / "producer.json"
    record = {
        "status": "running",
        "source": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "source_hashes": hashes(root),
        "started_at": now(),
        "simulator_udid": udid,
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "qualification": "Instrumented timings are excluded from acceptance and the 900-second CI budget.",
    }

    def save():
        result_path.write_text(json.dumps(record, indent=2) + "\n")

    save()
    command = test_command or ["make", "test-ui", "UI_TEST_SUITE=performance", "UI_SHARD=1/1"]
    record["test_command"] = command
    record["xcodebuild_flags"] = os.environ.get("XCODEBUILD_FLAGS", "")
    recorder = None
    options_path = output / "recording-options.json"
    with (output / "test.log").open("w") as test_log, (output / "trace.log").open("w") as trace_log:
        try:
            # Resolve options before launching the test, so attachment does
            # not wait for this subprocess while the first expansion runs.
            if trace_command is None:
                options = subprocess.check_output(
                    ["xcrun", "xctrace", "record", "--template", "Time Profiler",
                     "--instrument", "os_signpost", "--show-recording-options"],
                    text=True, stderr=trace_log,
                )
                settings = json.loads(options)
                settings["Time Profiler"]["highFrequencySampling"] = False
                settings["os_signpost"]["dynamicTracingEnabledSubsystems"] = ["com.joeblau.blau"]
                options_path.write_text(json.dumps(settings, indent=2) + "\n")
            before = app_pids(udid)
        except Exception as error:
            before = set()
            record["profile_error"] = str(error)
        runner = subprocess.Popen(command, cwd=root, stdout=test_log, stderr=subprocess.STDOUT)
        record["test_pid"] = runner.pid
        save()
        try:
            if "profile_error" not in record:
                deadline = time.monotonic() + observe_seconds
                while runner.poll() is None and time.monotonic() < deadline:
                    matches = app_pids(udid) - before
                    if len(matches) == 1:
                        record["app_pid"] = matches.pop()
                        break
                    time.sleep(0.1)
                if "app_pid" not in record:
                    raise RuntimeError("No unique fresh Choff process on the selected simulator; original test continues.")
                if trace_command is None:
                    trace_command = [
                        "xcrun", "xctrace", "record", "--no-prompt", "--template", "Time Profiler",
                        "--instrument", "os_signpost", "--recording-options", str(options_path),
                        "--device", udid, "--attach", str(record["app_pid"]),
                        "--time-limit", "120s", "--output", str(output / "expansion.trace"),
                    ]
                record["recorder_command"] = trace_command
                recorder = subprocess.Popen(trace_command, cwd=root, stdout=trace_log, stderr=subprocess.STDOUT)
                record["recorder_pid"] = recorder.pid
                save()
        except Exception as error:
            record["profile_error"] = str(error)
            save()
        # Observation timeout or recorder failure does not interrupt the test.
        record["test_exit_code"] = runner.wait()
        if recorder is not None:
            record["trace_exit_code"] = recorder.wait()
    record["source_hash_matches"] = record["source_hashes"] == hashes(root)
    record["status"] = "completed"
    record["finished_at"] = now()
    record["exit_code"] = record["test_exit_code"] or (
        0 if record.get("trace_exit_code") == 0 and record["source_hash_matches"]
        and "profile_error" not in record else 1
    )
    save()
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--udid", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = profile(Path(__file__).resolve().parents[2], args.udid, args.output)
    print(json.dumps(result, indent=2))
    raise SystemExit(result["exit_code"])
