import SwiftUI
import UIKit

@main
struct BlauBenchmarkHostApp: App {
    var body: some Scene {
        WindowGroup {
            VStack(spacing: 12) {
                Text("Choff Benchmarks")
                    .font(.title)
                Text("Keep this iPhone unlocked while benchmarks run.")
                    .multilineTextAlignment(.center)
            }
            .padding()
            .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
            .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
        }
    }
}
