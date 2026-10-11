import BlauCore
import Testing

@Suite("RecognitionVocabulary")
struct RecognitionVocabularyTests {
    @Test func normalizingTrimsDeduplicatesAndCaps() {
        let terms = [
            "  Paul   Graham ", "paul graham", "Choff", "", "   ", "Café", "cafe", String(repeating: "x", count: 65),
            "Grok",
        ]
        #expect(RecognitionVocabulary.normalized(terms) == ["Paul Graham", "Choff", "Café", "Grok"])
        #expect(RecognitionVocabulary.normalized(terms, limit: 2) == ["Paul Graham", "Choff"])
        #expect(RecognitionVocabulary.normalized([]) == [])
    }

    @Test func aStaticVocabularyReturnsItsTerms() async {
        let vocabulary = StaticRecognitionVocabulary(["Choff", "Grok"])
        #expect(await vocabulary.recognitionVocabulary() == ["Choff", "Grok"])
    }
}
