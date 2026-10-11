#!/usr/bin/env python3
"""Start Time Profiler before the original expansion test on its own simulator.

These instrumented timings are diagnostic evidence, not acceptance results.
Failure to record never terminates or replaces the original test producer.
"""

import argparse
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


SOURCE_ROOTS = (
    "Blau", "BlauWidgets", "BlauTests", "BlauUITests", "BlauPerfTests",
    "Packages/BlauKit", "Config", "project.yml", "Makefile",
    "scripts/ci/profile-expansion.py", "scripts/ci/ui-test-shard.sh",
)


class TracingNotification:
    """Register before xctrace starts so its ready notification cannot be lost."""

    def __init__(self, name):
        self.library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        self.token = ctypes.c_int()
        status = self.library.notify_register_check(name.encode(), ctypes.byref(self.token))
        if status:
            raise RuntimeError(f"Could not register tracing notification: {status}")
        # A newly registered check token is initially marked changed. Consume
        # that state before starting the recorder; it is not a ready signal.
        self.received()

    def received(self):
        changed = ctypes.c_int()
        status = self.library.notify_check(self.token.value, ctypes.byref(changed))
        if status:
            raise RuntimeError(f"Could not read tracing notification: {status}")
        return bool(changed.value)

    def close(self):
        self.library.notify_cancel(self.token.value)


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
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *SOURCE_ROOTS], cwd=root
    ).decode().split("\0")
    return {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in paths if path
    }


def stop_recorder(recorder, record):
    """Stop only our recorder; the original test is never interrupted."""
    if recorder.poll() is None:
        recorder.send_signal(2)  # xctrace finalizes its trace on SIGINT.
        try:
            return recorder.wait(timeout=30)
        except subprocess.TimeoutExpired:
            record["profile_error"] = "Recorder did not finish after SIGINT; original test result retained."
            recorder.terminate()
            try:
                return recorder.wait(timeout=10)
            except subprocess.TimeoutExpired:
                recorder.kill()
    return recorder.wait()


def recorder_command(udid, output, options_path, notification):
    return [
        "xcrun", "xctrace", "record", "--no-prompt", "--template", "Time Profiler",
        "--instrument", "os_signpost", "--recording-options", str(options_path),
        "--device", udid, "--all-processes", "--notify-tracing-started", notification,
        "--time-limit", "10m", "--output", str(output / "expansion.trace"),
    ]


def profile(root, udid, output, observe_seconds=600, test_command=None, trace_command=None,
            readiness_seconds=60):
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
        "capture_scope": "All processes on the explicitly selected owned simulator; host is not selected.",
    }

    def save():
        result_path.write_text(json.dumps(record, indent=2) + "\n")

    save()
    command = test_command or ["make", "test-ui", "UI_TEST_SUITE=performance", "UI_SHARD=1/1"]
    record["test_command"] = command
    record["xcodebuild_flags"] = os.environ.get("XCODEBUILD_FLAGS", "")
    recorder = None
    notification = None
    options_path = output / "recording-options.json"
    with (output / "test.log").open("w") as test_log, (output / "trace.log").open("w") as trace_log:
        try:
            # Resolve options and receive the recorder's ready signal before
            # launching the test, including its first expansion sample.
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
            notification_name = "com.joeblau.choff.expansion-profile." + str(uuid.uuid4())
            notification = TracingNotification(notification_name)
            if trace_command is None:
                trace_command = recorder_command(udid, output, options_path, notification_name)
            record["recorder_command"] = trace_command
            recorder = subprocess.Popen(trace_command, cwd=root, stdout=trace_log, stderr=subprocess.STDOUT)
            record["recorder_pid"] = recorder.pid
            record["recorder_started_at"] = now()
            save()
            deadline = time.monotonic() + readiness_seconds
            while not notification.received():
                if recorder.poll() is not None:
                    raise RuntimeError(f"Recorder exited before its ready notification: {recorder.returncode}")
                if time.monotonic() >= deadline:
                    raise RuntimeError("Recorder readiness observation expired; original test will run unchanged.")
                time.sleep(0.05)
            record["recording_ready_at"] = now()
            save()
        except Exception as error:
            before = set()
            record["profile_error"] = str(error)
            if recorder is not None:
                record["trace_exit_code"] = stop_recorder(recorder, record)
        finally:
            if notification is not None:
                notification.close()
        # The original producer starts even when profiling cannot start. Its
        # command, assertions and exit code are unchanged.
        runner = subprocess.Popen(command, cwd=root, stdout=test_log, stderr=subprocess.STDOUT)
        record["test_pid"] = runner.pid
        record["test_started_at"] = now()
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
                record["app_observed_at"] = now()
                save()
        except Exception as error:
            record["profile_error"] = str(error)
            save()
        # Observation timeout or recorder failure does not interrupt the test.
        record["test_exit_code"] = runner.wait()
        record["test_finished_at"] = now()
        if recorder is not None:
            record["recorder_was_running_at_test_end"] = recorder.poll() is None
            record["trace_exit_code"] = stop_recorder(recorder, record)
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
    print(json.dumps({key: value for key, value in result.items() if key != "source_hashes"}, indent=2))
    raise SystemExit(result["exit_code"])
