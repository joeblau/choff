import XCTest

extension XCUIElementQuery {
    /// Matches an assigned accessibility ID without fetching label or placeholder aliases.
    @MainActor
    func matchingAccessibilityIdentifier(_ identifier: String) -> XCUIElementQuery {
        matching(NSPredicate(format: "identifier == %@", identifier))
    }
}
