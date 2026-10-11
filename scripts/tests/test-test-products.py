#!/usr/bin/env python3
"""Hermetic stale/corrupt/incomplete cache checks; no Xcode or simulator."""

import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "test_products", Path(__file__).resolve().parents[1] / "ci/test-products.py")
products = importlib.util.module_from_spec(spec)
spec.loader.exec_module(products)


class TestProducts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / "Products"
        self.build.mkdir()
        self.run = self.build / "Blau_Blau_simulator-arm64.xctestrun"
        self.targets = []
        for name in ("BlauTests", "BlauUITests"):
            host = self.build / (name + ".app")
            bundle = host / "PlugIns" / (name + ".xctest")
            bundle.mkdir(parents=True)
            (bundle / name).write_bytes(b"built test executable")
            self.targets.append({"BlueprintName": name,
                                 "TestHostPath": "__TESTROOT__/" + host.name,
                                 "TestBundlePath": "__TESTHOST__/PlugIns/" + bundle.name})
        self.write_plan()

    def write_plan(self):
        self.run.write_bytes(plistlib.dumps({"CodeCoverageBuildableInfos": [{"Name": "Choff.app"}], "TestConfigurations": [
            {"IsEnabled": True, "TestTargets": self.targets}]}))

    def test_complete_cache_can_move_without_rewriting_paths(self):
        products.record(self.build, "debug-coverage", "source")
        moved = self.root / "MovedProducts"
        self.build.rename(moved)
        self.assertEqual(products.validate(moved, "debug-coverage", "source"), moved / self.run.name)

    def test_source_change_cannot_reuse_previous_products(self):
        products.record(self.build, "debug-coverage", "source")
        with self.assertRaisesRegex(ValueError, "do not match"):
            products.validate(self.build, "debug-coverage", "changed-source")

    def test_performance_cannot_reuse_debug_products(self):
        products.record(self.build, "debug-coverage", "source")
        with self.assertRaisesRegex(ValueError, "coverage"):
            products.validate(self.build, "optimized", "source")

    def test_uninstrumented_products_cannot_be_marked_as_debug_coverage(self):
        plan = plistlib.loads(self.run.read_bytes())
        plan.pop("CodeCoverageBuildableInfos")
        self.run.write_bytes(plistlib.dumps(plan))
        with self.assertRaisesRegex(ValueError, "coverage"):
            products.record(self.build, "debug-coverage", "source")

    def test_optimized_products_have_their_own_valid_manifest(self):
        plan = plistlib.loads(self.run.read_bytes())
        plan.pop("CodeCoverageBuildableInfos")
        self.run.write_bytes(plistlib.dumps(plan))
        products.record(self.build, "optimized", "source")
        self.assertEqual(products.validate(self.build, "optimized", "source"), self.run)

    def test_modified_binary_cannot_pass_validation(self):
        products.record(self.build, "debug-coverage", "source")
        binary = next(self.build.rglob("BlauTests.xctest/BlauTests"))
        binary.write_bytes(b"different executable")
        with self.assertRaisesRegex(ValueError, "do not match"):
            products.validate(self.build, "debug-coverage", "source")

    def test_missing_test_target_is_rejected(self):
        self.targets.pop()
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "both native and UI"):
            products.record(self.build, "debug-coverage", "source")

    def test_missing_bundle_is_rejected(self):
        self.targets[0]["TestBundlePath"] = "__TESTHOST__/Missing.xctest"
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            products.record(self.build, "debug-coverage", "source")

    def test_absolute_host_is_rejected(self):
        self.targets[0]["TestHostPath"] = str(self.build / "BlauTests.app")
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "relative"):
            products.record(self.build, "debug-coverage", "source")

    def test_product_path_cannot_escape_the_cache(self):
        self.targets[0]["TestHostPath"] = "__TESTROOT__/.."
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "nonportable"):
            products.record(self.build, "debug-coverage", "source")

    def test_missing_dependent_product_is_rejected(self):
        self.targets[0]["DependentProductPaths"] = ["__TESTROOT__/Missing.appex"]
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "missing dependent"):
            products.record(self.build, "debug-coverage", "source")

    def test_ambiguous_test_plan_is_rejected(self):
        (self.build / "Blau_Blau_other.xctestrun").write_bytes(self.run.read_bytes())
        with self.assertRaisesRegex(ValueError, "exactly one"):
            products.record(self.build, "debug-coverage", "source")

    def test_build_inputs_change_fingerprint_but_docs_do_not(self):
        repo = self.root / "Repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        inputs = ["Blau/View.swift", "Blau/Assets/Contents.json", "Blau/Resources/help.md", "Blau.xctestplan",
                  "project.yml", "Config/Debug.xcconfig", ".github/workflows/ci.yml",
                  "Packages/BlauKit/Package.resolved", "README.md", "docs/ci.md"]
        for name in inputs:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("initial")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        original = products.fingerprint(repo)
        for name in inputs:
            with self.subTest(path=name):
                path = repo / name
                path.write_text("changed")
                changed = products.fingerprint(repo)
                if name in {"README.md", "docs/ci.md"}:
                    self.assertEqual(changed, original)
                else:
                    self.assertNotEqual(changed, original)
                path.write_text("initial")

    def test_resolved_revision_and_artifact_checksum_invalidate_the_key(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        workspace = self.root / "workspace-state.json"
        dependency = {"packageRef": {"identity": "dependency", "location": "https://example.test/package"},
                      "state": {"checkoutState": {"revision": "first"}}}
        artifact = {"packageRef": dependency["packageRef"], "targetName": "Binary", "kind": "xcframework",
                    "source": {"checksum": "first"}, "path": "/machine-specific/path"}
        state = {"object": {"dependencies": [dependency], "artifacts": [artifact]}}
        workspace.write_text(json.dumps(state))
        original = products.fingerprint(self.root, workspace)
        dependency["state"]["checkoutState"]["revision"] = "second"
        workspace.write_text(json.dumps(state))
        self.assertNotEqual(products.fingerprint(self.root, workspace), original)
        dependency["state"]["checkoutState"]["revision"] = "first"
        artifact["source"]["checksum"] = "second"
        workspace.write_text(json.dumps(state))
        self.assertNotEqual(products.fingerprint(self.root, workspace), original)
        artifact["source"]["checksum"] = "first"
        artifact["path"] = "/another-machine/path"
        workspace.write_text(json.dumps(state))
        self.assertEqual(products.fingerprint(self.root, workspace), original)


if __name__ == "__main__":
    unittest.main()
