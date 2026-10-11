#!/usr/bin/env python3
"""Check profiler failures cannot suppress or interrupt the original test."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("profile_expansion", ROOT / "scripts/ci/profile-expansion.py")
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class ProducerTests(unittest.TestCase):
    def run_case(self, test_code, trace_code, observe_seconds=1, readiness_seconds=1):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "profile"
            ready = Path(directory) / "ready"

            class FakeNotification:
                def received(self):
                    return ready.exists()

                def close(self):
                    pass

            prefix = "import pathlib,sys,signal; signal.signal(signal.SIGINT, lambda *_: sys.exit(0)); "
            with patch.object(PROFILE, "TracingNotification", return_value=FakeNotification()):
                result = PROFILE.profile(
                    ROOT, "owned-simulator", output, observe_seconds=observe_seconds,
                    test_command=[sys.executable, "-c", test_code],
                    trace_command=[sys.executable, "-c", prefix + trace_code, str(ready)],
                    readiness_seconds=readiness_seconds,
                )
            self.assertEqual(json.loads((output / "producer.json").read_text()), result)
            self.assertEqual(result["status"], "completed")
            return result, (output / "test.log").read_text()

    def test_failing_profiler_preserves_original_test_failure(self):
        with patch.object(PROFILE, "app_pids", side_effect=[set(), {1234}]):
            result, log = self.run_case("import time; time.sleep(.15); raise SystemExit(65)",
                                        "pathlib.Path(sys.argv[1]).touch(); raise SystemExit(7)")
        self.assertEqual(result["test_exit_code"], 65)
        self.assertEqual(result["trace_exit_code"], 7)
        self.assertEqual(result["exit_code"], 65)
        self.assertEqual(result["app_pid"], 1234)
        self.assertTrue(result["source_hash_matches"])

    def test_missing_app_does_not_terminate_successful_test(self):
        with patch.object(PROFILE, "app_pids", return_value=set()):
            result, log = self.run_case("import time; time.sleep(.2); print('original test completed')",
                                        "pathlib.Path(sys.argv[1]).touch(); import time; time.sleep(10)", observe_seconds=.01)
        self.assertEqual(result["test_exit_code"], 0)
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("original test completed", log)
        self.assertIn("profile_error", result)
        self.assertIn("recorder_pid", result)
        self.assertLess(result["recording_ready_at"], result["test_started_at"])

    def test_profiler_failure_cannot_be_reported_as_success(self):
        with patch.object(PROFILE, "app_pids", side_effect=[set(), {1234}]):
            result, log = self.run_case("import time; time.sleep(.15)",
                                        "pathlib.Path(sys.argv[1]).touch(); raise SystemExit(7)")
        self.assertEqual(result["test_exit_code"], 0)
        self.assertEqual(result["trace_exit_code"], 7)
        self.assertEqual(result["exit_code"], 1)

    def test_original_test_starts_only_after_recording_is_ready(self):
        with patch.object(PROFILE, "app_pids", side_effect=[set(), {1234}]):
            result, log = self.run_case("import time; time.sleep(.1); print('original completed')",
                                        "import time; time.sleep(.1); pathlib.Path(sys.argv[1]).touch(); time.sleep(10)")
        self.assertEqual(result["test_exit_code"], 0)
        self.assertEqual(result["trace_exit_code"], 0)
        self.assertEqual(result["exit_code"], 0)
        self.assertLess(result["recording_ready_at"], result["test_started_at"])
        self.assertTrue(result["recorder_was_running_at_test_end"])
        self.assertIn("original completed", log)

    def test_readiness_timeout_preserves_the_original_test_failure(self):
        with patch.object(PROFILE, "app_pids", return_value=set()):
            result, log = self.run_case("print('original ran'); raise SystemExit(65)",
                                        "import time; time.sleep(10)", readiness_seconds=.05)
        self.assertEqual(result["test_exit_code"], 65)
        self.assertEqual(result["exit_code"], 65)
        self.assertIn("readiness observation expired", result["profile_error"])
        self.assertNotIn("recording_ready_at", result)
        self.assertIn("original ran", log)

    def test_recorder_is_explicitly_limited_to_the_owned_simulator(self):
        command = PROFILE.recorder_command("owned-simulator", Path("output"), Path("options"), "ready-name")
        self.assertIn("--all-processes", command)
        self.assertEqual(command[command.index("--device") + 1], "owned-simulator")
        self.assertEqual(command[command.index("--notify-tracing-started") + 1], "ready-name")
        self.assertNotIn("--attach", command)


if __name__ == "__main__":
    unittest.main()
