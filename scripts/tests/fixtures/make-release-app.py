#!/usr/bin/env python3
"""Builds a fake, ad hoc signed Choff.app for scripts/tests/test-release-scripts.sh.

    make-release-app.py OUTPUT_DIR [key=value ...]

Writes OUTPUT_DIR/Choff.app shaped like an App Store export: Info.plist,
an executable (a copy of /usr/bin/true), the repository's privacy manifests,
an embedded provisioning profile (a plain plist; the real one is CMS-signed)
and PlugIns/ChoffWidgets.appex, each signed ad hoc with entitlements so
`codesign -d --entitlements` reads them like a distribution build's.

Overrides (key=value) bend one property to produce a broken build:
  version, build, widget_build, environment, cloudkit, dev_key, encryption,
  aps, container_environment, get_task_allow, provisioned_devices,
  bundle_id, no_widget
"""

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]


def write_plist(path, value):
    with open(path, "wb") as handle:
        plistlib.dump(value, handle)


def sign(bundle, entitlements, scratch):
    path = scratch / f"{bundle.name}.entitlements"
    write_plist(path, entitlements)
    subprocess.run(
        ["codesign", "--force", "--sign", "-", "--entitlements", str(path), str(bundle)],
        check=True,
        capture_output=True,
    )


def main(argv):
    output = Path(argv[0])
    options = dict(argument.split("=", 1) for argument in argv[1:])
    version = options.get("version", "0.1.0")
    build = options.get("build", "42")
    bundle_id = options.get("bundle_id", "com.joeblau.choff")
    container = "iCloud.com.joeblau.choff"
    get_task_allow = options.get("get_task_allow", "false") == "true"

    app = output / "Choff.app"
    shutil.rmtree(app, ignore_errors=True)
    app.mkdir(parents=True)
    scratch = output / ".signing"
    scratch.mkdir(exist_ok=True)

    profile = {"Name": "iOS Team Store Provisioning Profile: com.joeblau.choff", "TeamIdentifier": ["ABCDE12345"]}
    if options.get("provisioned_devices") == "true":
        profile["ProvisionedDevices"] = ["00008110-000000000000001E"]

    info = {
        "CFBundleIdentifier": bundle_id,
        "CFBundleExecutable": "Choff",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build,
        "BlauEnvironment": options.get("environment", "release"),
        "BlauCloudKitEnabled": options.get("cloudkit", "YES"),
        "BlauXAIDevAPIKey": options.get("dev_key", ""),
        "ITSAppUsesNonExemptEncryption": options.get("encryption", "false") == "true",
    }

    if options.get("no_widget") != "true":
        widget = app / "PlugIns" / "ChoffWidgets.appex"
        widget.mkdir(parents=True)
        write_plist(
            widget / "Info.plist",
            {
                "CFBundleIdentifier": f"{bundle_id}.widgets",
                "CFBundleExecutable": "ChoffWidgets",
                "CFBundlePackageType": "XPC!",
                "CFBundleShortVersionString": version,
                "CFBundleVersion": options.get("widget_build", build),
            },
        )
        shutil.copy("/usr/bin/true", widget / "ChoffWidgets")
        shutil.copy(REPOSITORY / "BlauWidgets" / "PrivacyInfo.xcprivacy", widget / "PrivacyInfo.xcprivacy")
        write_plist(widget / "embedded.mobileprovision", profile)
        sign(
            widget,
            {"application-identifier": f"ABCDE12345.{bundle_id}.widgets", "get-task-allow": get_task_allow},
            scratch,
        )

    write_plist(app / "Info.plist", info)
    shutil.copy("/usr/bin/true", app / "Choff")
    shutil.copy(REPOSITORY / "Blau" / "Resources" / "PrivacyInfo.xcprivacy", app / "PrivacyInfo.xcprivacy")
    write_plist(app / "embedded.mobileprovision", profile)
    entitlements = {
        "application-identifier": f"ABCDE12345.{bundle_id}",
        "com.apple.developer.team-identifier": "ABCDE12345",
        "aps-environment": options.get("aps", "production"),
        "com.apple.developer.icloud-container-identifiers": [container],
        "com.apple.developer.icloud-services": ["CloudKit", "CloudDocuments"],
        "com.apple.developer.ubiquity-container-identifiers": [container],
        "com.apple.developer.icloud-container-environment": options.get("container_environment", "Production"),
        "get-task-allow": get_task_allow,
        "beta-reports-active": True,
    }
    sign(app, entitlements, scratch)
    shutil.rmtree(scratch)
    print(app)


if __name__ == "__main__":
    main(sys.argv[1:])
