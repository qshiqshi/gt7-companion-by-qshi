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
// Answers: {"id": …, "ok": true, …} or {"id": …, "ok": false, "code": "guardrail", "error": "…"}.
// Audio is mono, 16 bit, little endian, base64: questions as recorded (16 kHz), the voice at 24 kHz.
//
// Nothing leaves the computer: recognition (SpeechAnalyzer), the language model (FoundationModels)
// and the voice (AVSpeechSynthesizer) run on the device. The program needs macOS 26 or newer; it
// uses no microphone and asks for no permission.
//
//     python tools/build_box_helper.py        (swiftc -O -target arm64-apple-macos26.0 main.swift -o gt7c-box)
import AVFoundation
import Foundation
import FoundationModels
import Speech

let protocolVersion = 1
let voiceRate = 24_000.0          // what the program plays

struct HelperError: Error {
    let code: String
    let message: String
}

// MARK: - output

let outputLock = NSLock()

func send(_ object: [String: Any]) {
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

func buffer(fromInt16 pcm: Data, rate: Double) -> AVAudioPCMBuffer? {
    let frames = pcm.count / MemoryLayout<Int16>.size
    guard frames > 0, let buffer = AVAudioPCMBuffer(pcmFormat: int16Format(rate), frameCapacity: AVAudioFrameCount(frames)) else { return nil }
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

@MainActor
final class Voice {
    static let shared = Voice()
    private let synthesizer = AVSpeechSynthesizer()
    private let gate = Gate()

    func speak(_ text: String, voice: AVSpeechSynthesisVoice, rate: Float?, pitch: Float?) async throws -> Spoken {
        await gate.enter()
        defer { Task { await gate.leave() } }
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = voice
        if let rate { utterance.rate = rate }
        if let pitch { utterance.pitchMultiplier = pitch }
        let started = ContinuousClock.now
        let target = int16Format(voiceRate)
        let lock = NSLock()
        var spoken = Spoken()
        var resampler: Resampler?
        var done = false
        return try await withCheckedThrowingContinuation { continuation in
            // A voice that never calls back must not block every later sentence: give up after a while.
            DispatchQueue.global().asyncAfter(deadline: .now() + 30) {
                lock.lock()
                defer { lock.unlock() }
                if done { return }
                done = true
                continuation.resume(throwing: HelperError(code: "voice", message: "the voice did not finish"))
            }
            // The callback needs a free main thread (the run loop below); it never comes while the main thread blocks.
            synthesizer.write(utterance) { buffer in
                lock.lock()
                defer { lock.unlock() }
                if done { return }
                guard let pcm = buffer as? AVAudioPCMBuffer else {
                    done = true
                    continuation.resume(throwing: HelperError(code: "voice", message: "the voice delivered no PCM audio"))
                    return
                }
                if pcm.frameLength == 0 {                       // the end of the utterance
                    for out in resampler?.process(nil) ?? [] { spoken.pcm.append(bytes(of: out)) }
                    spoken.totalMs = milliseconds(since: started)
                    done = true
                    continuation.resume(returning: spoken)
                    return
                }
                if resampler == nil {                           // voices deliver 22.05 kHz or 16 kHz, 32 bit float
                    spoken.firstMs = milliseconds(since: started)
                    resampler = Resampler(from: pcm.format, to: target)
                    if resampler == nil {
                        done = true
                        continuation.resume(throwing: HelperError(code: "voice", message: "cannot convert \(pcm.format)"))
                        return
                    }
                }
                for out in resampler!.process(pcm) { spoken.pcm.append(bytes(of: out)) }
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

func handle(_ request: [String: Any]) async throws -> [String: Any] {
    let number: (String) -> Double? = { (request[$0] as? NSNumber)?.doubleValue }
    let text: (String) -> String = { request[$0] as? String ?? "" }
    switch text("op") {
    case "status":
        return await status()
    case "voices":
        return ["voices": VoiceList.shared.voices(language: request["language"] as? String ?? "en",
                                                  region: request["region"] as? String).map(voiceInfo)]
    case "prepare":
        let id = request["id"] ?? NSNull()
        return try await prepareSpeech(request["locale"] as? String ?? "en-US") { fraction in
            send(["id": id, "event": "progress", "fraction": fraction])
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
        let voice = try pickVoice(request)
        if text("text").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {      // nothing to say: no audio
            return ["audio": "", "rate": Int(voiceRate), "voice": voice.identifier, "seconds": 0]
        }
        let spoken = try await Voice.shared.speak(text("text"), voice: voice, rate: number("rate").map(Float.init),
                                                  pitch: number("pitch").map(Float.init))
        let pcm = trimmedTail(spoken.pcm, rate: voiceRate)
        return ["audio": pcm.base64EncodedString(), "rate": Int(voiceRate), "voice": voice.identifier,
                "quality": qualityName(voice.quality), "seconds": Double(pcm.count) / 2 / voiceRate,
                "first_ms": spoken.firstMs, "ms": spoken.totalMs]
    case "transcribe":
        guard let pcm = Data(base64Encoded: text("audio")) else { throw HelperError(code: "audio", message: "audio is not base64") }
        return try await transcribe(pcm, rate: number("rate") ?? 16_000, locale: request["locale"] as? String ?? "en-US",
                                    lead: (number("lead_ms") ?? 400) / 1000,
                                    alternatives: request["alternatives"] as? Bool ?? false)
    case "choose":
        return try await choose(instructions: text("instructions"), prompt: text("prompt"),
                                choices: request["choices"] as? [String] ?? [])
    case "respond":
        return try await respond(instructions: text("instructions"), prompt: text("prompt"),
                                 maxTokens: Int(number("max_tokens") ?? 100), temperature: number("temperature"))
    default:
        throw HelperError(code: "op", message: "unknown op \(text("op"))")
    }
}

func serve(_ line: String) {
    guard let data = line.data(using: .utf8),
          let request = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
        send(["ok": false, "code": "json", "error": "not a JSON object"])
        return
    }
    let id = request["id"] ?? NSNull()
    Task {                                           // requests run side by side; only the voice speaks one at a time
        do {
            var answer = try await handle(request)
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
