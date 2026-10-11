import Foundation
import Testing

@testable import Blau

/// Guards the app configuration generated from `project.yml`. The unit-test
/// bundle is hosted in the app, so `Bundle.main` is the built Choff.app.
@Suite("App configuration")
struct AppConfigurationTests {
    private let info = Bundle.main.infoDictionary ?? [:]

    @Test func bundleIdentifierIsChoff() {
        #expect(Bundle.main.bundleIdentifier == "com.joeblau.choff")
    }

    @Test func displayNameIsChoff() {
        #expect(info["CFBundleDisplayName"] as? String == "Choff")
    }

    @Test func versionsComeFromBuildSettings() throws {
        let marketing = try #require(info["CFBundleShortVersionString"] as? String)
        let build = try #require(info["CFBundleVersion"] as? String)
        #expect(!marketing.isEmpty && !marketing.contains("$("))
        #expect(!build.isEmpty && !build.contains("$("))
    }

    @Test func declaresMicrophoneUsage() throws {
        let description = try #require(info["NSMicrophoneUsageDescription"] as? String)
        #expect(!description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    @Test func declaresBackgroundModes() throws {
        let modes = try #require(info["UIBackgroundModes"] as? [String])
        #expect(Set(modes) == ["audio", "remote-notification", "processing"])
    }

    @Test func declaresLaunchScreen() {
        #expect(info["UILaunchScreen"] is [String: Any])
    }

    @Test func rootViewHasStableAccessibilityIdentifier() {
        #expect(RootView.accessibilityIdentifier == "blau.root")
    }
}
