// gt7c-box – speech and language on this Mac for the Box.
//
// Part of Gran Turismo 7 Companion by qshi (GPL-3.0-or-later). The Python side that starts
// this program and talks to it is src/gt7companion/engineer/helper.py.
//
// One child process of the program. It reads requests as JSON lines on stdin and
// answers each with one JSON line on stdout that carries the same "id":
//
//     {"id": 1, "op": "status"}
//     {"id": 2, "op": "voices", "language": "de"}
//     {"id": 3, "op": "prepare", "locale": "de-DE"}          may send {"id": 3, "event": "progress", "fraction": 0.4}
//     {"id": 4, "op": "warm", "locale": "de-DE", "language": "de"}
//     {"id": 5, "op": "speak", "text": "Funkprobe.", "language": "de"}
//     {"id": 6, "op": "transcribe", "audio": "<base64>", "rate": 16000, "locale": "de-DE"}
//     {"id": 7, "op": "choose", "instructions": "…", "prompt": "…", "choices": ["fuel", "tyres", "none"]}
//     {"id": 8, "op": "respond", "instructions": "…", "prompt": "…"}
//
// The "id" is an integer or a string and comes back unchanged. A request without one is answered with null. Any
// other id (a fraction, true, an object, infinity) could not be matched with its answer, so the request is turned
// away with an "args" error and a null id.
//
// Optional fields (left out or null: the default). A number that is no number (a string, true) or lies outside
// its range is an "args" error, never a quiet default:
//
//     voices      region            breaks ties between the voices of one language ("GB")
//     warm        locale, language, voice, model (false: leave the language model alone), instructions
//     speak       voice (an identifier from "voices"), region, rate 0…1, pitch 0.5…2 (left out: the voice's own)
//     transcribe  rate 8000…48000 (sample rate of the audio, default 16000), lead_ms 0…5000 (silence put before
//                 the audio, default 400), alternatives (true: the other readings, too)
//     respond     max_tokens 1…2000 (default 100), temperature 0…2 (left out: the model answers greedily)
//
// Answers: {"id": …, "ok": true, …} or {"id": …, "ok": false, "code": "guardrail", "error": "…"}. The codes:
//
//     json         the line is not a JSON object, or an answer could not be written as JSON
//     op           unknown operation
//     args         a number is no number or out of range; the id is neither an integer nor a string
//     audio        the audio is not base64, not whole 16 bit samples, or cannot be converted
//     locale       speech recognition does not know that language
//     assets       the speech model (or the language model) is not on this Mac
//     voice        no voice for the language, or the voice failed or did not finish in time
//     choices      "choose" has nothing to choose from
//     unavailable  the language model cannot be used here ("error" says why: device, disabled, loading)
//     guardrail, refusal, context, rate, language, timeout, busy, model
//                  what the language model itself reported (refused, too much text, too many requests, …)
//     error        anything else
//
// A line that is not JSON, is no object or names an unknown "op" gets its error answer and the program goes on;
// empty lines are ignored. The program ends when stdin is closed (or nobody reads stdout any more), with exit code 0.
//
// Audio is mono, 16 bit, little endian, base64: questions as recorded (16 kHz), the voice at 24 kHz.
//
// Nothing leaves the computer: recognition (SpeechAnalyzer), the language model (FoundationModels)
// and the voice (AVSpeechSynthesizer) run on the device. The program needs macOS 26 or newer; it
// uses no microphone and asks for no permission.
//
//     python tools/build_box_helper.py        (swiftc -O -target arm64-apple-macos26.0 main.swift -o gt7c-box)
//
// Building needs Xcode 27 or newer (the macOS 27 SDK), although the result runs on macOS 26: a few declarations
// used below exist only in that SDK (LanguageModelError, the token usage, …), each one inside
// `if #available(macOS 27.0, *)`. They are never reached on macOS 26, but the compiler has to find them.
import AVFoundation
import Foundation
import FoundationModels
import Speech

let protocolVersion = 1
let voiceRate = 24_000.0          // what the program plays
let speakTimeout = Duration.seconds(30)     // longest a voice may take for one utterance before it counts as stuck
let endGrace = 1.0                // seconds without audio after an empty buffer that end an utterance, see SpeechCollector

struct HelperError: Error {
    let code: String
    let message: String
}

// MARK: - output

let outputLock = NSLock()

/// The id of a request as it may go back in an answer: an integer or a string, as sent; anything else becomes null.
/// A fraction, `true` or an object would not match the request it answers, and infinity cannot be written at all.
func safeID(_ value: Any?) -> Any {
    if let text = value as? String { return text }
    if let number = value as? NSNumber, CFGetTypeID(number) == CFNumberGetTypeID(), !CFNumberIsFloatType(number) { return number }
    return NSNull()
}

func send(_ object: [String: Any]) {
    var object = object
    // JSONSerialization raises an Objective-C exception for what JSON cannot hold (infinity, NaN, …). `try?` does not
    // catch that and the program would end, so ask first. A progress report that cannot be written is dropped; an
    // answer is replaced by an error, or whoever asked would wait for it for ever.
    if !JSONSerialization.isValidJSONObject(object) {
        if object["event"] != nil { return }
        object = ["id": safeID(object["id"]), "ok": false, "code": "json", "error": "the answer could not be written as JSON"]
    }
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.withoutEscapingSlashes]) else { return }
    outputLock.lock()
    defer { outputLock.unlock() }
    do {
        try FileHandle.standardOutput.write(contentsOf: data + Data([0x0A]))
    } catch {
        exit(0)                   // nobody listens any more
    }
}

func milliseconds(since start: ContinuousClock.Instant) -> Int {
    let passed = (ContinuousClock.now - start).components
    return Int((Double(passed.seconds) * 1000 + Double(passed.attoseconds) / 1e15).rounded())
}

// MARK: - audio

func int16Format(_ rate: Double) -> AVAudioFormat {
    AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: rate, channels: 1, interleaved: true)!
}

/// Converts a stream of buffers to another format; the sample rate converter keeps its state between calls.
final class Resampler {
    private let converter: AVAudioConverter
    private let output: AVAudioFormat

    init?(from input: AVAudioFormat, to output: AVAudioFormat) {
        guard let converter = AVAudioConverter(from: input, to: output) else { return nil }
        self.converter = converter
        self.output = output
    }

    /// `nil` ends the stream and returns what is still inside the converter.
    func process(_ input: AVAudioPCMBuffer?) -> [AVAudioPCMBuffer] {
        var result: [AVAudioPCMBuffer] = []
        var pending = input
        while true {
            guard let out = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: 16_384) else { break }
            var error: NSError?
            let status = converter.convert(to: out, error: &error) { _, state in
                if let buffer = pending {
                    pending = nil
                    state.pointee = .haveData
                    return buffer
                }
                state.pointee = input == nil ? .endOfStream : .noDataNow
                return nil
            }
            if out.frameLength > 0 { result.append(out) }
            if status != .haveData { break }
        }
        return result
    }
}

func bytes(of buffer: AVAudioPCMBuffer) -> Data {
    guard let channel = buffer.int16ChannelData else { return Data() }
    return Data(bytes: channel[0], count: Int(buffer.frameLength) * MemoryLayout<Int16>.size)
}

/// `nil` when there is nothing to convert (no whole sample, or a rate the system has no format for). A last odd byte is no
/// sample and is left out; `handle` turns such audio away before it gets here.
func buffer(fromInt16 pcm: Data, rate: Double) -> AVAudioPCMBuffer? {
    let frames = pcm.count / MemoryLayout<Int16>.size
    guard frames > 0, frames <= Int(AVAudioFrameCount.max),
          let format = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: rate, channels: 1, interleaved: true),
          let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)) else { return nil }
    buffer.frameLength = AVAudioFrameCount(frames)
    pcm.withUnsafeBytes { raw in
        buffer.int16ChannelData![0].update(from: raw.bindMemory(to: Int16.self).baseAddress!, count: frames)
    }
    return buffer
}

/// Cuts the silence the voices leave after the last word (about 0.2 s), keeping a short tail.
func trimmedTail(_ pcm: Data, rate: Double, keep: Double = 0.06) -> Data {
    let count = pcm.count / 2
    var last = count
    pcm.withUnsafeBytes { raw in
        let samples = raw.bindMemory(to: Int16.self)
        while last > 0 && abs(Int(samples[last - 1])) < 200 { last -= 1 }
    }
    return pcm.prefix(min(count, last + Int(rate * keep)) * 2)
}

// MARK: - voices

func qualityName(_ quality: AVSpeechSynthesisVoiceQuality) -> String {
    switch quality {
    case .premium: return "premium"
    case .enhanced: return "enhanced"
    default: return "default"
    }
}

/// Higher is better: premium before enhanced before standard; among the standard ones the natural before the robotic.
func voiceRank(_ voice: AVSpeechSynthesisVoice) -> Int {
    var rank = voice.quality.rawValue * 100
    let id = voice.identifier
    if id.contains(".voice.compact.") { rank += 30 } else if id.contains(".super-compact.") { rank += 20 }
    else if id.contains(".eloquence.") { rank += 10 }
    if voice.voiceTraits.contains(.isNoveltyVoice) || voice.voiceTraits.contains(.isPersonalVoice) { rank -= 1000 }
    return rank
}

func voiceInfo(_ voice: AVSpeechSynthesisVoice) -> [String: Any] {
    ["id": voice.identifier, "name": voice.name, "locale": voice.language, "quality": qualityName(voice.quality),
     "natural": voiceRank(voice) >= 120]
}

/// The installed voices, asked once (listing them takes some 70 ms) and again when the system reports a change.
final class VoiceList: @unchecked Sendable {
    static let shared = VoiceList()
    private let lock = NSLock()
    private var all: [AVSpeechSynthesisVoice]?

    private init() {
        NotificationCenter.default.addObserver(forName: AVSpeechSynthesizer.availableVoicesDidChangeNotification,
                                               object: nil, queue: nil) { [weak self] _ in
            self?.lock.lock()
            self?.all = nil
            self?.lock.unlock()
        }
    }

    /// The voices for a language ("de", "en" or "en-GB"), best first; a preferred region ("GB") breaks ties.
    func voices(language: String, region: String? = nil) -> [AVSpeechSynthesisVoice] {
        lock.lock()
        if all == nil { all = AVSpeechSynthesisVoice.speechVoices().filter { voiceRank($0) > 0 } }
        let known = all ?? []
        lock.unlock()
        let prefix = language.lowercased()
        let bonus: (AVSpeechSynthesisVoice) -> Int = { region != nil && $0.language.hasSuffix("-" + region!) ? 5 : 0 }
        return known.filter { $0.language.lowercased().hasPrefix(prefix) }
            .sorted { a, b in
                let (ra, rb) = (voiceRank(a) + bonus(a), voiceRank(b) + bonus(b))
                return ra != rb ? ra > rb : a.name < b.name
            }
    }
}

// MARK: - speaking

/// Lets one caller in at a time, in the order of arrival.
actor Gate {
    private var busy = false
    private var waiting: [CheckedContinuation<Void, Never>] = []

    func enter() async {
        if !busy { busy = true; return }
        await withCheckedContinuation { waiting.append($0) }
    }

    func leave() {
        if waiting.isEmpty { busy = false } else { waiting.removeFirst().resume() }
    }
}

struct Spoken {
    var pcm = Data()
    var firstMs = 0
    var totalMs = 0
}

/// What the callback of the synthesizer, its delegate and the time-out share. It gathers the audio as it comes (converted
/// to what the program plays) and answers the waiting caller exactly once: with the audio when the utterance is over,
/// with the first thing that goes wrong, or with the time-out. They run on different threads, hence the lock. Whatever
/// arrives after the answer is ignored.
///
/// When is an utterance over? Not with the first buffer without frames: a voice sends one after every stretch of about
/// thirteen seconds and goes on with the next. The delegate of the synthesizer knows (`SpeechEnd` calls `ended`). Should
/// a voice never tell its delegate, the utterance ends when nothing follows an empty buffer for `endGrace` seconds.
final class SpeechCollector: @unchecked Sendable {
    private let lock = NSLock()
    private var arrivals = 0                                         // buffers so far, the empty ones too
    private let started = ContinuousClock.now
    private let target = int16Format(voiceRate)
    private var waiting: CheckedContinuation<Spoken, Error>?         // nil as soon as the caller has its answer
    private var spoken = Spoken()
    private var resampler: Resampler?

    init(_ waiting: CheckedContinuation<Spoken, Error>) {
        self.waiting = waiting
    }

    /// A buffer with audio arrived.
    func arrived(_ pcm: AVAudioPCMBuffer) {
        lock.lock()
        defer { lock.unlock() }
        guard waiting != nil else { return }
        arrivals += 1
        if resampler == nil {                           // voices deliver 22.05 kHz or 16 kHz, 32 bit float
            spoken.firstMs = milliseconds(since: started)
            resampler = Resampler(from: pcm.format, to: target)
        }
        guard let converter = resampler else {
            return finish(.failure(HelperError(code: "voice", message: "cannot convert \(pcm.format)")))
        }
        for out in converter.process(pcm) { spoken.pcm.append(bytes(of: out)) }
    }

    /// A buffer without frames arrived: the voice is through with a stretch of the text, or with all of it.
    func paused() {
        lock.lock()
        arrivals += 1
        let seen = arrivals
        lock.unlock()
        DispatchQueue.global().asyncAfter(deadline: .now() + endGrace) {
            self.lock.lock()
            let silent = self.arrivals == seen
            self.lock.unlock()
            if silent { self.ended() }                  // the delegate never came: this must have been the end
        }
    }

    /// The utterance is over.
    func ended() {
        lock.lock()
        defer { lock.unlock() }
        guard waiting != nil else { return }
        for out in resampler?.process(nil) ?? [] { spoken.pcm.append(bytes(of: out)) }
        spoken.totalMs = milliseconds(since: started)
        finish(.success(spoken))
    }

    /// The voice delivered something that is not audio.
    func failed(_ message: String) {
        lock.lock()
        defer { lock.unlock() }
        finish(.failure(HelperError(code: "voice", message: message)))
    }

    /// The voice has not finished in time. `false`: it had finished by itself after all, nothing to do.
    func timedOut() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard waiting != nil else { return false }
        finish(.failure(HelperError(code: "voice", message: "the voice did not finish")))
        return true
    }

    /// Answers the caller (the first call only) and lets go of the audio. The caller of this holds the lock.
    private func finish(_ result: Result<Spoken, Error>) {
        waiting?.resume(with: result)
        waiting = nil
        spoken = Spoken()
        resampler = nil
    }
}

/// The delegate of the synthesizer: tells the collector of an utterance that the voice is through with it.
final class SpeechEnd: NSObject, AVSpeechSynthesizerDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var collectors: [ObjectIdentifier: SpeechCollector] = [:]

    func expect(_ utterance: AVSpeechUtterance, _ collector: SpeechCollector) {
        lock.lock()
        defer { lock.unlock() }
        collectors[ObjectIdentifier(utterance)] = collector
    }

    func forget(_ utterance: AVSpeechUtterance) {
        lock.lock()
        defer { lock.unlock() }
        collectors[ObjectIdentifier(utterance)] = nil
    }

    private func over(_ utterance: AVSpeechUtterance) {
        lock.lock()
        let collector = collectors.removeValue(forKey: ObjectIdentifier(utterance))
        lock.unlock()
        collector?.ended()
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) { over(utterance) }
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) { over(utterance) }
}

@MainActor
final class Voice {
    static let shared = Voice()
    private let synthesizer = AVSpeechSynthesizer()
    private let ends = SpeechEnd()
    private let gate = Gate()

    private init() {
        synthesizer.delegate = ends
    }

    func speak(_ text: String, voice: AVSpeechSynthesisVoice, rate: Float?, pitch: Float?) async throws -> Spoken {
        await gate.enter()
        defer { Task { await gate.leave() } }
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = voice
        if let rate { utterance.rate = rate }
        if let pitch { utterance.pitchMultiplier = pitch }
        defer { ends.forget(utterance) }
        return try await withCheckedThrowingContinuation { continuation in
            let collector = SpeechCollector(continuation)
            ends.expect(utterance, collector)
            // A voice that never calls back must not block every later sentence: give up after a while. The synthesizer
            // is shared and works through its queue one utterance after the other, so the stuck one is stopped as well,
            // or all that come after it would wait behind it. The synthesizer belongs to the main actor: the stop is
            // called there, in the same step as the answer, so the next sentence cannot start in between.
            Task { @MainActor in
                try? await Task.sleep(for: speakTimeout)
                if collector.timedOut() { self.synthesizer.stopSpeaking(at: .immediate) }
            }
            // The callback needs a free main thread (the run loop below); it never comes while the main thread blocks.
            synthesizer.write(utterance) { buffer in
                guard let pcm = buffer as? AVAudioPCMBuffer else { return collector.failed("the voice delivered no PCM audio") }
                if pcm.frameLength == 0 { collector.paused() } else { collector.arrived(pcm) }
            }
        }
    }
}

func pickVoice(_ request: [String: Any]) throws -> AVSpeechSynthesisVoice {
    let language = request["language"] as? String ?? "en"
    if let id = request["voice"] as? String, !id.isEmpty, let voice = AVSpeechSynthesisVoice(identifier: id) { return voice }
    if let voice = VoiceList.shared.voices(language: language, region: request["region"] as? String).first { return voice }
    throw HelperError(code: "voice", message: "no voice for \(language)")
}

// MARK: - recognising

let analyzerOptions = SpeechAnalyzer.Options(priority: .userInitiated, modelRetention: .processLifetime)

func speechLocale(_ identifier: String) async throws -> Locale {
    if let locale = await SpeechTranscriber.supportedLocale(equivalentTo: Locale(identifier: identifier)) { return locale }
    throw HelperError(code: "locale", message: "speech recognition does not know \(identifier)")
}

func makeTranscriber(_ locale: Locale, alternatives: Bool = false) -> SpeechTranscriber {
    SpeechTranscriber(locale: locale, transcriptionOptions: [],
                      reportingOptions: alternatives ? [.alternativeTranscriptions] : [], attributeOptions: [])
}

/// Makes sure the model for this language is on the computer (loads it if needed, about 400 MB) and stays there.
func prepareSpeech(_ identifier: String, progress: @escaping (Double) -> Void) async throws -> [String: Any] {
    let started = ContinuousClock.now
    let locale = try await speechLocale(identifier)
    let transcriber = makeTranscriber(locale)
    let before = await AssetInventory.status(forModules: [transcriber])
    var downloaded = false
    if before != .installed {
        // A program the system has not seen yet is told "supported" even when the model is on the disk; then there
        // is nothing to install (no request) and the status turns to "installed" a moment later.
        if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
            let observation = request.progress.observe(\.fractionCompleted) { value, _ in progress(value.fractionCompleted) }
            defer { observation.invalidate() }
            try await request.downloadAndInstall()
            downloaded = true
        }
    }
    var reserved = await AssetInventory.reservedLocales.contains { $0.identifier(.bcp47) == locale.identifier(.bcp47) }
    if !reserved { reserved = (try? await AssetInventory.reserve(locale: locale)) ?? false }
    var status = await AssetInventory.status(forModules: [transcriber])
    var waited = 0
    while status != .installed && waited < 40 {                     // up to ten seconds
        try await Task.sleep(for: .milliseconds(250))
        status = await AssetInventory.status(forModules: [transcriber])
        waited += 1
    }
    guard status == .installed else {
        throw HelperError(code: "assets", message: "no speech model for \(locale.identifier(.bcp47)) (\(status))")
    }
    return ["locale": locale.identifier(.bcp47), "downloaded": downloaded, "reserved": reserved,
            "status_before": "\(before)", "waited_ms": waited * 250, "ms": milliseconds(since: started)]
}

/// Loads the model into memory, so the first question is not the slow one.
func warmSpeech(_ identifier: String) async throws {
    let transcriber = makeTranscriber(try await speechLocale(identifier))
    guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]) else { return }
    let analyzer = SpeechAnalyzer(modules: [transcriber], options: analyzerOptions)
    try await analyzer.prepareToAnalyze(in: format)
    await analyzer.cancelAndFinishNow()
}

/// `lead`: seconds of silence put before the audio. Without some quiet before the first word the recogniser
/// swallows it ("Kbox" for "Hey Box", or nothing at all).
func transcribe(_ pcm: Data, rate: Double, locale identifier: String, lead: Double, alternatives: Bool) async throws -> [String: Any] {
    let started = ContinuousClock.now
    let locale = try await speechLocale(identifier)
    let transcriber = makeTranscriber(locale, alternatives: alternatives)
    guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]) else {
        let status = await AssetInventory.status(forModules: [transcriber])
        throw HelperError(code: "assets", message: "the speech model for \(locale.identifier(.bcp47)) is not installed (\(status))")
    }
    let padded = Data(count: Int(rate * lead) * 2) + pcm + Data(count: Int(rate * 0.2) * 2)
    guard let source = buffer(fromInt16: padded, rate: rate) else { return ["text": "", "ms": 0] }
    var inputs: [AVAudioPCMBuffer] = [source]
    if source.format != format {
        guard let resampler = Resampler(from: source.format, to: format) else {
            throw HelperError(code: "audio", message: "cannot convert to \(format)")
        }
        inputs = resampler.process(source) + resampler.process(nil)
    }
    let (stream, feed) = AsyncStream<AnalyzerInput>.makeStream()
    let analyzer = SpeechAnalyzer(modules: [transcriber], options: analyzerOptions)
    let collector = Task { () -> (String, [String]) in
        var text = ""
        var others: [String] = []
        for try await result in transcriber.results {
            text += String(result.text.characters)
            for alternative in result.alternatives.dropFirst() { others.append(String(alternative.characters)) }
        }
        return (text, others)
    }
    for input in inputs { feed.yield(AnalyzerInput(buffer: input)) }
    feed.finish()
    do {
        if let last = try await analyzer.analyzeSequence(stream) {
            try await analyzer.finalizeAndFinish(through: last)
        } else {
            await analyzer.cancelAndFinishNow()
        }
    } catch {
        collector.cancel()
        throw error
    }
    let (text, others) = try await collector.value
    var answer: [String: Any] = ["text": text.trimmingCharacters(in: .whitespacesAndNewlines),
                                 "locale": locale.identifier(.bcp47), "ms": milliseconds(since: started)]
    if alternatives { answer["alternatives"] = others.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) } }
    return answer
}

// MARK: - the language model

func modelStatus() -> [String: Any] {
    let model = SystemLanguageModel.default
    var status: [String: Any] = ["available": model.isAvailable,
                                 "languages": Set(model.supportedLanguages.compactMap { $0.languageCode?.identifier }).sorted()]
    switch model.availability {
    case .available: status["reason"] = ""
    case .unavailable(.deviceNotEligible): status["reason"] = "device"           // this Mac cannot run it
    case .unavailable(.appleIntelligenceNotEnabled): status["reason"] = "disabled"   // switched off in the settings
    case .unavailable(.modelNotReady): status["reason"] = "loading"              // still being downloaded
    case .unavailable(let other): status["reason"] = "\(other)"
    }
    return status
}

func describe(_ error: Error) -> HelperError {
    if let known = error as? HelperError { return known }
    if #available(macOS 27.0, *) {
        if let failure = error as? LanguageModelError {
            switch failure {
            case .guardrailViolation(let detail): return HelperError(code: "guardrail", message: detail.debugDescription)
            case .refusal(let detail): return HelperError(code: "refusal", message: detail.debugDescription)
            case .contextSizeExceeded(let detail): return HelperError(code: "context", message: detail.debugDescription)
            case .rateLimited: return HelperError(code: "rate", message: "\(failure)")
            case .unsupportedLanguageOrLocale: return HelperError(code: "language", message: "\(failure)")
            case .timeout: return HelperError(code: "timeout", message: "\(failure)")
            default: return HelperError(code: "model", message: "\(failure)")
            }
        }
        if let failure = error as? SystemLanguageModel.Error { return HelperError(code: "assets", message: "\(failure)") }
        if let failure = error as? LanguageModelSession.Error { return HelperError(code: "busy", message: "\(failure)") }
    }
    if let failure = error as? LanguageModelSession.GenerationError {            // what macOS 26 throws
        switch failure {
        case .guardrailViolation(let context): return HelperError(code: "guardrail", message: context.debugDescription)
        case .refusal(_, let context): return HelperError(code: "refusal", message: context.debugDescription)
        case .exceededContextWindowSize(let context): return HelperError(code: "context", message: context.debugDescription)
        case .assetsUnavailable(let context): return HelperError(code: "assets", message: context.debugDescription)
        case .unsupportedLanguageOrLocale(let context): return HelperError(code: "language", message: context.debugDescription)
        case .rateLimited(let context): return HelperError(code: "rate", message: context.debugDescription)
        case .concurrentRequests(let context): return HelperError(code: "busy", message: context.debugDescription)
        default: return HelperError(code: "model", message: "\(failure)")
        }
    }
    let plain = error as NSError
    return HelperError(code: "error", message: "\(type(of: error)) \(plain.domain) \(plain.code): \(plain.localizedDescription)")
}

func requireModel() throws {
    if !SystemLanguageModel.default.isAvailable {
        throw HelperError(code: "unavailable", message: modelStatus()["reason"] as? String ?? "")
    }
}

func usage<Content>(_ response: LanguageModelSession.Response<Content>, into answer: inout [String: Any]) {
    if #available(macOS 27.0, *) {
        answer["tokens_in"] = response.usage.input.totalTokenCount
        answer["tokens_out"] = response.usage.output.totalTokenCount
    }
}

/// The model picks exactly one of the given words. Its output is constrained to the list – it cannot write anything else.
func choose(instructions: String, prompt: String, choices: [String]) async throws -> [String: Any] {
    let started = ContinuousClock.now
    try requireModel()
    guard !choices.isEmpty else { throw HelperError(code: "choices", message: "nothing to choose from") }
    let schema = try GenerationSchema(root: DynamicGenerationSchema(name: "Choice", anyOf: choices), dependencies: [])
    let session = LanguageModelSession(instructions: instructions)
    let response = try await session.respond(to: prompt, schema: schema, includeSchemaInPrompt: true,
                                             options: GenerationOptions(samplingMode: .greedy))
    var answer: [String: Any] = ["choice": try response.content.value(String.self), "ms": milliseconds(since: started)]
    usage(response, into: &answer)
    return answer
}

/// The model writes a short answer of its own. Every call is a fresh conversation.
func respond(instructions: String, prompt: String, maxTokens: Int, temperature: Double?) async throws -> [String: Any] {
    let started = ContinuousClock.now
    try requireModel()
    let session = LanguageModelSession(instructions: instructions)
    let options = GenerationOptions(samplingMode: temperature == nil ? .greedy : nil, temperature: temperature,
                                    maximumResponseTokens: maxTokens)
    let response = try await session.respond(to: prompt, options: options)
    var answer: [String: Any] = ["text": response.content.trimmingCharacters(in: .whitespacesAndNewlines),
                                 "ms": milliseconds(since: started)]
    usage(response, into: &answer)
    return answer
}

// MARK: - requests

func status() async -> [String: Any] {
    let version = ProcessInfo.processInfo.operatingSystemVersion
    let installed = await SpeechTranscriber.installedLocales.map { $0.identifier(.bcp47) }.sorted()
    let supported = await SpeechTranscriber.supportedLocales.map { $0.identifier(.bcp47) }.sorted()
    let region = Locale.current.region?.identifier
    let best: (String) -> Any = { VoiceList.shared.voices(language: $0, region: region).first.map { voiceInfo($0) as Any } ?? NSNull() }
    return ["protocol": protocolVersion,
            "os": "\(version.majorVersion).\(version.minorVersion).\(version.patchVersion)",
            "model": modelStatus(),
            "speech": ["available": SpeechTranscriber.isAvailable, "installed": installed, "supported": supported],
            "voices": ["de": best("de"), "en": best("en")]]
}

/// A number from the request: `nil` when it is left out (or null), so the caller can use its default. When it is there but
/// is no number (a string, true), is not finite or lies outside `range`, it is an "args" error. Without that, a negative
/// count would reach `Data(count:)` and a value like 1e30 would reach `Int(_:)`, and both stop the program.
func number(_ request: [String: Any], _ key: String, in range: ClosedRange<Double>) throws -> Double? {
    guard let given = request[key], !(given is NSNull) else { return nil }
    guard let boxed = given as? NSNumber, CFGetTypeID(boxed) == CFNumberGetTypeID() else {     // CFBoolean is a different type
        throw HelperError(code: "args", message: "\(key) must be a number")
    }
    let value = boxed.doubleValue
    guard value.isFinite, range.contains(value) else {
        let limits = [range.lowerBound, range.upperBound].map { String(format: "%g", $0) }
        throw HelperError(code: "args", message: "\(key) must be between \(limits[0]) and \(limits[1])")
    }
    return value
}

func handle(_ request: [String: Any], id: Any) async throws -> [String: Any] {
    let text: (String) -> String = { request[$0] as? String ?? "" }
    switch text("op") {
    case "status":
        return await status()
    case "voices":
        return ["voices": VoiceList.shared.voices(language: request["language"] as? String ?? "en",
                                                  region: request["region"] as? String).map(voiceInfo)]
    case "prepare":
        return try await prepareSpeech(request["locale"] as? String ?? "en-US") { fraction in
            if fraction.isFinite { send(["id": id, "event": "progress", "fraction": min(max(fraction, 0), 1)]) }
        }
    case "warm":                                    // everything into memory: about 2 s once, saves 1–2 s per first use
        let started = ContinuousClock.now
        if let locale = request["locale"] as? String { try? await warmSpeech(locale) }
        if request["language"] != nil || request["voice"] != nil, let voice = try? pickVoice(request) {
            _ = try? await Voice.shared.speak("OK.", voice: voice, rate: nil, pitch: nil)
        }
        if request["model"] as? Bool ?? true, SystemLanguageModel.default.isAvailable {
            LanguageModelSession(instructions: text("instructions")).prewarm()
        }
        return ["ms": milliseconds(since: started)]
    case "speak":
        let rate = try number(request, "rate", in: 0...1).map(Float.init)
        let pitch = try number(request, "pitch", in: 0.5...2).map(Float.init)
        let voice = try pickVoice(request)
        if text("text").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {      // nothing to say: no audio
            return ["audio": "", "rate": Int(voiceRate), "voice": voice.identifier, "seconds": 0]
        }
        let spoken = try await Voice.shared.speak(text("text"), voice: voice, rate: rate, pitch: pitch)
        let pcm = trimmedTail(spoken.pcm, rate: voiceRate)
        return ["audio": pcm.base64EncodedString(), "rate": Int(voiceRate), "voice": voice.identifier,
                "quality": qualityName(voice.quality), "seconds": Double(pcm.count) / 2 / voiceRate,
                "first_ms": spoken.firstMs, "ms": spoken.totalMs]
    case "transcribe":
        let rate = try number(request, "rate", in: 8_000...48_000) ?? 16_000
        let leadMs = try number(request, "lead_ms", in: 0...5_000) ?? 400
        let given = request["audio"] ?? ""                           // left out: nothing, which is silence and gives no text
        guard let encoded = given as? String, let pcm = Data(base64Encoded: encoded) else {
            throw HelperError(code: "audio", message: "audio is not base64")
        }
        guard pcm.count % MemoryLayout<Int16>.size == 0 else {       // samples are 16 bit: a half one means the data is cut or not PCM
            throw HelperError(code: "audio", message: "audio is not whole 16 bit samples (\(pcm.count) bytes)")
        }
        return try await transcribe(pcm, rate: rate, locale: request["locale"] as? String ?? "en-US",
                                    lead: leadMs / 1000, alternatives: request["alternatives"] as? Bool ?? false)
    case "choose":
        return try await choose(instructions: text("instructions"), prompt: text("prompt"),
                                choices: request["choices"] as? [String] ?? [])
    case "respond":
        let maxTokens = try number(request, "max_tokens", in: 1...2_000) ?? 100
        let temperature = try number(request, "temperature", in: 0...2)
        return try await respond(instructions: text("instructions"), prompt: text("prompt"),
                                 maxTokens: Int(maxTokens), temperature: temperature)
    default:
        throw HelperError(code: "op", message: "unknown op \(text("op"))")
    }
}

func serve(_ line: String) {
    guard let data = line.data(using: .utf8),
          let request = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
        send(["id": NSNull(), "ok": false, "code": "json", "error": "not a JSON object"])
        return
    }
    let id = safeID(request["id"])
    if id is NSNull, let sent = request["id"], !(sent is NSNull) {            // an id was sent, but none that can go back
        send(["id": id, "ok": false, "code": "args", "error": "id must be an integer or a string"])
        return
    }
    Task {                                           // requests run side by side; only the voice speaks one at a time
        do {
            var answer = try await handle(request, id: id)
            answer["id"] = id
            answer["ok"] = true
            send(answer)
        } catch {
            let failure = describe(error)
            send(["id": id, "ok": false, "code": failure.code, "error": failure.message, "type": "\(type(of: error))"])
        }
    }
}

// MARK: - start

signal(SIGPIPE, SIG_IGN)
if CommandLine.arguments.dropFirst().first == "status" {          // one answer and out, for a look from the terminal
    Task {
        send(await status())
        exit(0)
    }
} else {
    let reader = Thread {
        while let line = readLine(strippingNewline: true) {
            if !line.isEmpty { serve(line) }
        }
        exit(0)                                                   // the program closed the pipe or is gone
    }
    reader.stackSize = 1 << 20
    reader.start()
}
RunLoop.main.run()                                                // the voice calls back on the main thread
