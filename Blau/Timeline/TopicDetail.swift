import BlauTopics
import SwiftUI

/// The accessibility identifiers of an expanded topic's detail (#58).
enum TopicDetailAccessibility {
    /// The detail under an expanded bullet: summary, span and actions.
    static let detail = "blau.timeline.topic.detail"
    /// When the topic ran and how long.
    static let span = "blau.timeline.topic.span"
    static let continueTopic = "blau.timeline.topic.continue"
    static let share = "blau.timeline.topic.share"
    static let more = "blau.timeline.topic.more"
    /// UI tests only: the latest tap-to-expand latency in milliseconds, as
    /// the element's value.
    static let expandLatency = "blau.timeline.expandLatency"
}

/// What an expanded older topic shows above its transcript (#58): its
/// summary, when it ran and for how long, and what can be done with it:
/// continue it in a conversation, share it as Markdown, rename it or merge
/// it with the previous topic. (Split is on each line of the transcript
/// below, "Split Topic Here".)
///
/// On iOS 27, its controls stay mounted for visible lazy sections while
/// collapsed, avoiding initial construction during a tap's transaction.
/// The visible overlay's `onAppear` ends the tap-to-expand measurement only
/// after the expanded header is laid out (`TopicExpansionTimer`).
struct TopicDetailHeader: View {
    let topic: TimelineTopic
    let placement: TopicTimeline.Placement
    let editor: TopicEditor
    let isExpanded: Bool
    /// Continues the topic; `nil` hides Continue.
    let onContinue: (() -> Void)?
    /// Called once the header is laid out.
    let onAppear: () -> Void

    @Environment(AppEnvironment.self) private var environment
    @State private var showsActions = false

    var body: some View {
        if #available(iOS 27, *) {
            content
                .frame(height: isExpanded ? nil : 0)
                .clipped()
                .allowsHitTesting(isExpanded)
                .accessibilityHidden(!isExpanded)
                .overlay {
                    if isExpanded {
                        Color.clear
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                            .onAppear(perform: onAppear)
                    }
                }
                .onChange(of: isExpanded) {
                    if !isExpanded { showsActions = false }
                }
        } else {
            content.onAppear(perform: onAppear)
        }
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let summary = topic.summary?.trimmingCharacters(in: .whitespacesAndNewlines), !summary.isEmpty {
                Text(verbatim: summary)
                    .brandTextStyle(.caption)
                    .foregroundStyle(Color.brand(.secondaryText))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityLabel(Text("Summary"))
                    .accessibilityValue(Text(verbatim: summary))
                    .accessibilityIdentifier(isExpanded ? TopicTimelineAccessibility.summary : "")
                    .accessibilityHidden(!isExpanded)
            }
            Text(verbatim: TopicDetailDescription.span(of: topic))
                .brandTextStyle(.timestamp)
                .foregroundStyle(Color.brand(.secondaryText))
                .accessibilityLabel(Text(verbatim: TopicDetailDescription.span(of: topic, spelledOut: true)))
                .accessibilityIdentifier(isExpanded ? TopicDetailAccessibility.span : "")
                .accessibilityHidden(!isExpanded)
            actions
        }
        .padding(.leading, TopicTimelineLayout.textInset)
        .padding(.trailing)
        .padding(.top, 2)
        .padding(.bottom, 12)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(isExpanded ? TopicDetailAccessibility.detail : "")
        .timelineRail(placement.railBelow)
    }

    /// Side by side when they fit, stacked at large text sizes (#81).
    private var actions: some View {
        TopicActionsLayout { actionButtons }
            .font(.subheadline.weight(.medium))
    }

    @ViewBuilder
    private var actionButtons: some View {
        Group {
            if let onContinue {
                Button(action: onContinue) {
                    Label("Continue", systemImage: "arrow.uturn.forward")
                }
                .buttonStyle(TopicActionButtonStyle(prominent: true))
                .accessibilityHint("Starts a conversation that picks up this topic")
                .accessibilityIdentifier(isExpanded ? TopicDetailAccessibility.continueTopic : "")
                .accessibilityHidden(!isExpanded)
            }
            if let container = environment.modelContainer {
                ShareLink(
                    item: TopicMarkdownDocument(topic: topic, container: container),
                    preview: SharePreview(Text(verbatim: topic.title))
                ) {
                    Label("Share", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(TopicActionButtonStyle())
                .accessibilityHint("Shares the topic as Markdown")
                .accessibilityIdentifier(isExpanded ? TopicDetailAccessibility.share : "")
                .accessibilityHidden(!isExpanded)
            }
            if !topic.isSynthetic {
                Button {
                    showsActions = true
                } label: {
                    Label("More", systemImage: "ellipsis")
                        .labelStyle(.iconOnly)
                        .frame(minWidth: 20, minHeight: 20)
                }
                .buttonStyle(TopicActionButtonStyle())
                .accessibilityLabel("More Actions")
                .accessibilityIdentifier(isExpanded ? TopicDetailAccessibility.more : "")
                .accessibilityHidden(!isExpanded)
                // Build the edit presentation when requested rather than
                // inserting a menu control into the expansion's layout.
                .confirmationDialog("Topic Actions", isPresented: $showsActions, titleVisibility: .hidden) {
                    TopicEditMenuItems(
                        topicID: topic.id, title: topic.title, canMerge: placement.canMerge, editor: editor)
                }
            }
        }
    }
}

/// Keep the controls' sizing pass simple while preserving the native
/// button, sharing and edit actions.
private struct TopicActionButtonStyle: ButtonStyle {
    var prominent = false
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, 12)
            .frame(minHeight: 44)
            .foregroundStyle(prominent ? Color.white : Color.brand(.accent))
            .background(
                prominent ? Color.brand(.accentFill) : Color(uiColor: .secondarySystemFill),
                in: Capsule()
            )
            .contentShape(Capsule())
            .opacity(isEnabled ? (configuration.isPressed ? 0.72 : 1) : 0.4)
    }
}

/// The text of a topic's detail.
enum TopicDetailDescription {
    /// When the topic ran and for how long: "6:00 PM – 6:08 PM · 8 min", or
    /// "6:00 PM – now" while it is open. `spelledOut` is VoiceOver's
    /// "From 6:00 PM to 6:08 PM, 8 minutes".
    static func span(of topic: TimelineTopic, spelledOut: Bool = false, format: TopicTimelineFormat = .init())
        -> String
    {
        let start = format.time(topic.startedAt)
        guard let endedAt = topic.endedAt, let duration = topic.duration else {
            return spelledOut
                ? String(localized: "Started \(start), still open") : "\(start) – " + String(localized: "now")
        }
        let end = format.time(endedAt)
        if spelledOut {
            return String(localized: "From \(start) to \(end), \(format.duration(duration, spelledOut: true))")
        }
        return "\(start) – \(end) · \(format.duration(duration))"
    }
}
