import Foundation
import Synchronization

/// Temporary diagnostic branch only; records phases without changing the measurement.
enum ExpansionDiagnostic {
    private struct Storage: Sendable {
        var start: ContinuousClock.Instant?
        var events: [String] = []
    }

    private static let storage = Mutex(Storage())

    static func begin() {
        storage.withLock {
            $0.start = .now
            $0.events = []
        }
        mark("tap")
    }

    static func mark(_ name: String) {
        let now = ContinuousClock.now
        storage.withLock {
            guard let start = $0.start, $0.events.count < 100 else { return }
            let milliseconds = start.duration(to: now) / .milliseconds(1)
            $0.events.append(String(format: "%.2f", milliseconds) + " " + name)
        }
    }

    static var report: String { storage.withLock { $0.events.joined(separator: "; ") } }
}
