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
    def run_case(self, test_code, trace_code, observe_seconds=1):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "profile"
            result = PROFILE.profile(
                ROOT, "owned-simulator", output, observe_seconds=observe_seconds,
                test_command=[sys.executable, "-c", test_code],
                trace_command=[sys.executable, "-c", trace_code],
            )
            self.assertEqual(json.loads((output / "producer.json").read_text()), result)
            self.assertEqual(result["status"], "completed")
            return result, (output / "test.log").read_text()

    def test_failing_profiler_preserves_original_test_failure(self):
        with patch.object(PROFILE, "app_pids", side_effect=[set(), {1234}]):
            result, log = self.run_case("import time; time.sleep(.15); raise SystemExit(65)", "raise SystemExit(7)")
        self.assertEqual(result["test_exit_code"], 65)
        self.assertEqual(result["trace_exit_code"], 7)
        self.assertEqual(result["exit_code"], 65)
        self.assertEqual(result["app_pid"], 1234)
        self.assertTrue(result["source_hash_matches"])

    def test_missing_app_does_not_terminate_successful_test(self):
        with patch.object(PROFILE, "app_pids", return_value=set()):
            result, log = self.run_case("import time; time.sleep(.2); print('original test completed')", "raise SystemExit(0)", observe_seconds=.01)
        self.assertEqual(result["test_exit_code"], 0)
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("original test completed", log)
        self.assertIn("profile_error", result)
        self.assertNotIn("recorder_pid", result)

    def test_profiler_failure_cannot_be_reported_as_success(self):
        with patch.object(PROFILE, "app_pids", side_effect=[set(), {1234}]):
            result, log = self.run_case("import time; time.sleep(.15)", "raise SystemExit(7)")
        self.assertEqual(result["test_exit_code"], 0)
        self.assertEqual(result["trace_exit_code"], 7)
        self.assertEqual(result["exit_code"], 1)


if __name__ == "__main__":
    unittest.main()
