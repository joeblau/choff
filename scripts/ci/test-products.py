#!/usr/bin/env python3
"""Identify and validate complete, reusable Xcode test products.

Only build products are cached. Tests and their result bundles always run
again; Debug coverage and optimized performance products use separate keys.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
MANIFEST = "choff-ci-test-products.json"


def fingerprint(repo=REPO, dependencies=None):
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).split(b"\0")
    digest = hashlib.sha256()
    for encoded in sorted(set(paths)):
        if not encoded:
            continue
        relative = os.fsdecode(encoded)
        # Documentation does not affect a build. All other tracked inputs,
        # including assets, test plans, configs and CI build commands, do.
        if relative.startswith("docs/") or relative in {"README.md", "CONTRIBUTING.md", "AGENTS.md", "CLAUDE.md"}:
            continue
        path = repo / relative
        content = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        digest.update(encoded + b"\0" + hashlib.sha256(content).digest())
    if dependencies is not None:
        workspace = json.loads(dependencies.read_text())["object"]
        if not workspace.get("dependencies") or workspace.get("prebuilts"):
            raise ValueError("expected resolved dependencies without unsupported prebuilt package inputs")
        graph = {
            "dependencies": [{"packageRef": item["packageRef"], "state": item["state"]}
                             for item in workspace["dependencies"]],
            "artifacts": [{key: item[key] for key in ("packageRef", "targetName", "kind", "source")}
                          for item in workspace.get("artifacts", [])],
        }
        for items in graph.values():
            items.sort(key=lambda item: json.dumps(item, sort_keys=True))
        digest.update(b"resolved-app-dependencies\0" + json.dumps(graph, sort_keys=True).encode())
    return digest.hexdigest()


def products_digest(products):
    digest = hashlib.sha256()
    for path in sorted(products.rglob("*")):
        if path.name == MANIFEST or (path.is_dir() and not path.is_symlink()):
            continue
        relative = path.relative_to(products).as_posix().encode()
        if path.is_symlink():
            content = os.fsencode(os.readlink(path))
            kind = b"link"
        else:
            content = path.read_bytes()
            kind = b"file"
        digest.update(relative + b"\0" + kind + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


def test_run(products):
    runs = list(products.glob("Blau_Blau_*.xctestrun"))
    if len(runs) != 1:
        raise ValueError("expected exactly one Blau test plan in cached products")
    plan = plistlib.loads(runs[0].read_bytes())
    targets = [target for configuration in plan["TestConfigurations"]
               if configuration.get("IsEnabled", True)
               for target in configuration["TestTargets"]]
    if {target["BlueprintName"] for target in targets} != {"BlauTests", "BlauUITests"}:
        raise ValueError("cached test plan must contain both native and UI test targets")
    for target in targets:
        host = target["TestHostPath"]
        if not host.startswith("__TESTROOT__/"):
            raise ValueError("cached test host must be relative to the product root")
        host_path = products / host.removeprefix("__TESTROOT__/")
        bundle = target["TestBundlePath"].replace("__TESTHOST__", str(host_path))
        bundle = bundle.replace("__TESTROOT__", str(products))
        for path in [host_path, Path(bundle)]:
            if not path.resolve().is_relative_to(products.resolve()) or not path.exists():
                raise ValueError(f"incomplete or nonportable cached test products: {path}")
        for path in target.get("DependentProductPaths", []):
            if not path.startswith("__TESTROOT__/"):
                raise ValueError("dependent products must be relative to the product root")
            resolved = products / path.removeprefix("__TESTROOT__/")
            if not resolved.resolve().is_relative_to(products.resolve()) or not resolved.exists():
                raise ValueError(f"missing dependent product: {path}")
    return runs[0]


def metadata(products, variant, source):
    run = test_run(products)
    plan = plistlib.loads(run.read_bytes())
    has_coverage = bool(plan.get("CodeCoverageBuildableInfos"))
    if has_coverage != (variant == "debug-coverage"):
        raise ValueError("test plan coverage metadata does not match the requested build variant")
    return run, {"source_fingerprint": source, "variant": variant,
                 "products_digest": products_digest(products)}


def record(products, variant, source):
    run, expected = metadata(products, variant, source)
    (products / MANIFEST).write_text(json.dumps(expected, indent=2) + "\n")
    return run


def validate(products, variant, source):
    run, expected = metadata(products, variant, source)
    if json.loads((products / MANIFEST).read_text()) != expected:
        raise ValueError("cached products do not match the current source, build variant or product hashes")
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("fingerprint", "record", "validate"))
    parser.add_argument("--products", type=Path)
    parser.add_argument("--variant", choices=("debug-coverage", "optimized"))
    parser.add_argument("--dependencies", type=Path)
    parser.add_argument("--expected-fingerprint")
    args = parser.parse_args()
    derived_data = args.products.parent.parent if args.products else Path(".build/DerivedData")
    dependencies = args.dependencies or derived_data / "SourcePackages/workspace-state.json"
    source = fingerprint(dependencies=dependencies)
    if args.expected_fingerprint is not None and source != args.expected_fingerprint:
        raise ValueError("build inputs changed after computing the cache key")
    if args.command == "fingerprint":
        print(source)
        return
    if args.products is None or args.variant is None:
        parser.error("record and validate require --products and --variant")
    products = args.products.resolve()
    if args.command == "record":
        run = record(products, args.variant, source)
    else:
        run = validate(products, args.variant, source)
    print(run)


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError) as error:
        print(f"test-products: {error}", file=sys.stderr)
        sys.exit(2)
