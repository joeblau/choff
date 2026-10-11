import SwiftUI
import UIKit

/// The `UIScrollView` behind a SwiftUI `ScrollView`, for the one thing
/// SwiftUI can't do in time: move the content offset in the same layout
/// pass that prepended a page of history (#57).
///
/// A lazy stack doesn't move the offset when a page is prepended
/// (FB24968838), so the rows on screen jump down by the page's height.
/// `ScrollPosition.scrollTo(y:)` puts them back only a few frames later (a
/// visible flash), and SwiftUI can re-apply its own idea of the offset
/// over it. Setting `contentOffset` on the scroll view directly, from the
/// held row's geometry callback, lands in the same frame.
///
/// This replaces the SwiftUIIntrospect dependency the issue suggested: a
/// zero-size view inside the scroll view's content finds its nearest
/// `UIScrollView` ancestor once it is in a window.
@MainActor
final class EnclosingScrollView {
    private(set) weak var scrollView: UIScrollView?

    /// Moves the content offset down by `distance`.
    ///
    /// A prepended row can report its new position before UIKit updates
    /// `contentSize`. Its correction must pass the previous end of the
    /// content; clamping to that stale end discards part of the movement.
    /// Other corrections stay within the current content bounds.
    ///
    /// - Returns: `false` when the scroll view isn't known yet.
    func shiftContent(by distance: CGFloat, clampToContent: Bool = true) -> Bool {
        guard let scrollView else { return false }
        let maxY = max(
            -scrollView.adjustedContentInset.top,
            scrollView.contentSize.height + scrollView.adjustedContentInset.bottom - scrollView.bounds.height)
        var offset = scrollView.contentOffset
        offset.y = max(offset.y + distance, -scrollView.adjustedContentInset.top)
        if clampToContent { offset.y = min(offset.y, maxY) }
        scrollView.contentOffset = offset
        return true
    }

    /// Moves the content offset to the end of the content.
    ///
    /// - Returns: `false` when the scroll view isn't known yet.
    func scrollToBottom() -> Bool {
        guard let scrollView else { return false }
        let bottom = max(
            -scrollView.adjustedContentInset.top,
            scrollView.contentSize.height + scrollView.adjustedContentInset.bottom - scrollView.bounds.height)
        scrollView.contentOffset.y = bottom
        return true
    }

    fileprivate func found(_ scrollView: UIScrollView?) {
        if let scrollView { self.scrollView = scrollView }
    }
}

extension View {
    /// Finds the `UIScrollView` this view is inside and hands it to `box`.
    /// Put it on the scroll view's content.
    func findingEnclosingScrollView(_ box: EnclosingScrollView) -> some View {
        background(EnclosingScrollViewFinder(box: box).frame(width: 0, height: 0).accessibilityHidden(true))
    }
}

private struct EnclosingScrollViewFinder: UIViewRepresentable {
    let box: EnclosingScrollView

    func makeUIView(context: Context) -> FinderView {
        let view = FinderView()
        view.box = box
        view.isUserInteractionEnabled = false
        return view
    }

    func updateUIView(_ view: FinderView, context: Context) {
        view.box = box
        view.lookUp()
    }

    final class FinderView: UIView {
        weak var box: EnclosingScrollView?

        override func didMoveToWindow() {
            super.didMoveToWindow()
            lookUp()
        }

        func lookUp() {
            guard window != nil, box?.scrollView == nil else { return }
            var ancestor = superview
            while let view = ancestor, !(view is UIScrollView) {
                ancestor = view.superview
            }
            box?.found(ancestor as? UIScrollView)
        }
    }
}
