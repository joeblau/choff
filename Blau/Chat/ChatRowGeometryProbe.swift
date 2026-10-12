#if DEBUG
    import SwiftUI

    extension EnvironmentValues {
        @Entry var reportsChatRowFrames = false
    }

    /// UIKit's accessibility frame for selectable text can include the
    /// scroll container rather than the rendered text's margins on iOS 27.
    /// UI tests read SwiftUI's actual layout, as they already do for the
    /// timeline's expansion latency. Live launches never enable this probe.
    struct ChatRowGeometryProbe: ViewModifier {
        let identifier: String
        @Environment(\.reportsChatRowFrames) private var reportsFrames

        func body(content: Content) -> some View {
            if reportsFrames {
                content
                    .overlay(alignment: .topLeading) {
                        // Read this layout pass directly. Publishing a stored
                        // rectangle schedules another pass and can expose the
                        // previous text size while the viewport is settling.
                        GeometryReader { geometry in
                            Text("")
                                .frame(width: 1, height: 1)
                                .accessibilityElement(children: .ignore)
                                .accessibilityLabel("Transcript row layout")
                                .accessibilityValue(Text(verbatim: geometryValue(geometry.frame(in: .global))))
                                .accessibilityIdentifier("\(identifier).geometry")
                        }
                        .allowsHitTesting(false)
                    }
            } else {
                content
            }
        }

        private func geometryValue(_ rectangle: CGRect) -> String {
            "\(rectangle.minX),\(rectangle.minY),\(rectangle.width),\(rectangle.height)"
        }
    }
#endif
