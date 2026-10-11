import BlauAudio
import BlauCore
import BlauPersistence
import BlauRealtime
import SwiftData
import SwiftUI
import UIKit

/// The accessibility identifiers UI tests use for live captions.
enum LiveCaptionAccessibility {
    /// The caption card above the Now pill.
    static let caption = "blau.caption"
}

/// Live captions (#81): what Grok is saying while its row in the transcript
/// is out of view, for example while the user reads the topic history.
///
/// Grok's words are always on screen while it speaks: at the latest line
/// they are the streaming row itself; scrolled away, this card floats above
/// the Now pill with the reply's latest words, revealed in step with the
/// audio like the row (`ChatTranscript.revealedText`). The words are cut to
/// whole words with a leading ellipsis (`ChatCaption.tail`), never truncated
/// by the layout, so the card grows with Dynamic Type instead of clipping,
/// and nothing in it moves.
///
/// It takes no touches: at the largest text sizes it covers a good part of
/// the screen, and the history has to keep scrolling under it. The Now pill
/// below it returns to the latest line.
struct LiveCaption: View {
    let model: ChatTranscriptModel
    /// Only the running conversation on screen has a caption.
    let conversationID: UUID?
    /// Space available to the floating caption, below the pinned title.
    let availableSize: CGSize

    var body: some View {
        if let conversationID, model.conversationID?.rawValue == conversationID,
            let row = ChatCaption.speakingRow(in: model.liveRows)
        {
            if case .streaming(let item) = row.kind, let progress = model.progress {
                // As often as the streaming row: a few times a second.
                TimelineView(.periodic(from: .now, by: 0.05)) { _ in
                    LiveCaptionCard(
                        text: ChatTranscript.revealedText(of: row.text, played: progress(item)),
                        availableSize: availableSize)
                }
            } else {
                LiveCaptionCard(text: row.text, availableSize: availableSize)
            }
        }
    }
}

/// The caption's card: "Grok" and the reply's latest words on a material,
/// read by VoiceOver as one element.
struct LiveCaptionCard: View {
    /// Everything heard of the reply so far.
    let text: String
    let availableSize: CGSize

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        let caption = LiveCaptionSizing.tail(of: text, availableSize: availableSize, size: dynamicTypeSize)
        if !caption.isEmpty {
            VStack(alignment: .leading, spacing: 2) {
                Text("Grok")
                    .brandTextStyle(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.brand(.secondaryText))
                Text(verbatim: caption)
                    .brandTextStyle(.transcript)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(.regularMaterial, in: .rect(cornerRadius: 16))
            .padding(.horizontal)
            // Swipes and taps reach the timeline underneath.
            .allowsHitTesting(false)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text("Grok"))
            .accessibilityValue(Text(verbatim: caption))
            .accessibilityAddTraits([.isStaticText, .updatesFrequently])
            .accessibilityIdentifier(LiveCaptionAccessibility.caption)
        }
    }
}

/// Measure the caption at its actual width and Dynamic Type size. Keep the
/// latest whole words while leaving history visible above the floating card.
/// The full reply remains in the transcript; no font size or line is clipped.
@MainActor
enum LiveCaptionSizing {
    static func tail(of text: String, availableSize: CGSize, size: DynamicTypeSize) -> String {
        let traits = UITraitCollection(preferredContentSizeCategory: contentSizeCategory(size))
        let body = UIFont.preferredFont(forTextStyle: .body, compatibleWith: traits)
        let heading = UIFont.preferredFont(forTextStyle: .footnote, compatibleWith: traits)
        // Match the card's horizontal margins and padding, and its heading,
        // spacing and vertical padding. The card uses at most 60% of history.
        let width = max(1, availableSize.width - 60)
        let height = max(body.lineHeight, availableSize.height * 0.6 - heading.lineHeight - 22)
        let limit = ChatCaption.maxCharacters(isAccessibilitySize: size.isAccessibilitySize)
        var caption = ChatCaption.tail(of: text, maxCharacters: limit)
        var previous: String?
        for count in stride(from: limit, through: 1, by: -1) {
            let candidate = ChatCaption.tail(of: text, maxCharacters: count)
            if candidate == previous { continue }
            caption = candidate
            previous = candidate
            let bounds = (caption as NSString).boundingRect(
                with: CGSize(width: width, height: .greatestFiniteMagnitude),
                options: [.usesLineFragmentOrigin, .usesFontLeading],
                attributes: [.font: body], context: nil)
            if ceil(bounds.height) <= height { break }
        }
        return caption
    }

    private static func contentSizeCategory(_ size: DynamicTypeSize) -> UIContentSizeCategory {
        switch size {
        case .xSmall: .extraSmall
        case .small: .small
        case .medium: .medium
        case .large: .large
        case .xLarge: .extraLarge
        case .xxLarge: .extraExtraLarge
        case .xxxLarge: .extraExtraExtraLarge
        case .accessibility1: .accessibilityMedium
        case .accessibility2: .accessibilityLarge
        case .accessibility3: .accessibilityExtraLarge
        case .accessibility4: .accessibilityExtraExtraLarge
        case .accessibility5: .accessibilityExtraExtraExtraLarge
        default: .large
        }
    }
}

/// UI tests only: Grok "speaking" in the latest conversation, so the live
/// caption shows when the test scrolls into the history
/// (`-BlauCaptionFixture 1` on a `ui-test` launch, after a chat or timeline
/// fixture). The live app never does this.
///
/// It starts once the speech models are ready, as a real reply can only
/// come after them. (At AX5, the model card's animated exit under a reply
/// taller than the screen can send the timeline's lazy stack into an endless
/// layout loop while UI automation reads the screen; see
/// docs/accessibility.md.)
enum LiveCaptionFixture {
    /// The launch argument (`UserDefaults` key) that asks for it.
    static let launchArgument = "BlauCaptionFixture"

    /// What Grok is "saying": long enough that the caption shows its end.
    static let reply =
        "First, how fast are you growing week over week, and is it organic? Second, who are your best users and"
        + " what do they do every day? Third, what would make them stop using it?"

    @MainActor
    static func applyIfRequested(in environment: AppEnvironment, defaults: UserDefaults = .standard) async {
        guard environment.kind != .live, defaults.bool(forKey: launchArgument) else { return }
        for _ in 0..<600 where !environment.speechModels.isReady {
            try? await Task.sleep(for: .milliseconds(100))
        }
        // Let the model card finish leaving.
        try? await Task.sleep(for: .seconds(1))
        guard let container = environment.modelContainer,
            let conversation = try? ModelContext(container).fetch(ChatTranscript.latestConversation).first
        else { return }
        environment.chat.apply(
            TurnSnapshot(
                state: .agentSpeaking, conversationID: ConversationID(rawValue: conversation.id),
                agentSpeech: [
                    TurnSnapshot.AgentSpeech(
                        utteranceID: UUID(), playbackID: PlaybackItemID(itemID: "caption_fixture"), transcript: reply,
                        startedAt: Date())
                ]))
    }
}

#Preview("Caption") {
    GeometryReader { geometry in
        VStack {
            Spacer()
            LiveCaptionCard(text: LiveCaptionFixture.reply, availableSize: geometry.size)
        }
    }
}

#Preview("Caption, largest text") {
    GeometryReader { geometry in
        VStack {
            Spacer()
            LiveCaptionCard(text: LiveCaptionFixture.reply, availableSize: geometry.size)
        }
    }
    .dynamicTypeSize(.accessibility5)
}
