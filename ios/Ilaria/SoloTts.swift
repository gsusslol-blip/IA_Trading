import AVFoundation
import Foundation

/// Local speech for iOS (PC TTS is skipped with speak:false).
enum SoloTts {
    private static let synth = AVSpeechSynthesizer()

    static func speak(_ text: String) {
        let clipped = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clipped.isEmpty else { return }
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
        let u = AVSpeechUtterance(string: String(clipped.prefix(1800)))
        u.voice = AVSpeechSynthesisVoice(language: "es-AR")
            ?? AVSpeechSynthesisVoice(language: "es-ES")
            ?? AVSpeechSynthesisVoice(language: "es-MX")
        u.rate = AVSpeechUtteranceDefaultSpeechRate * 1.02
        synth.speak(u)
    }

    static func stop() {
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
    }
}
