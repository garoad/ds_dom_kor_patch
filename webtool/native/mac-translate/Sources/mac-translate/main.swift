import Foundation
import Translation

// stdin: JSON array of Japanese strings. stdout: JSON array of Korean strings
// (final result only, written once at the end). stderr: human-readable
// progress lines, one per line - the Node wrapper relays these via onProgress.
//
// Uses Apple's system Translation framework (the on-device NMT engine behind
// macOS/Safari's built-in "번역" feature), NOT the FoundationModels LLM -
// FoundationModels was tried first but it frequently just echoed/reorganized
// the Japanese source instead of translating it, and had no reliable way to
// keep array items aligned. TranslationSession is a dedicated translator, is
// far more reliable at actually translating, and passes <HEX>/<이름> control
// tags through untouched without any tag-preservation prompting needed.

func eprint(_ s: String) {
    FileHandle.standardError.write((s + "\n").data(using: .utf8)!)
}

let inputData = FileHandle.standardInput.readDataToEndOfFile()
guard let allItems = try? JSONDecoder().decode([String].self, from: inputData) else {
    eprint("입력 JSON 파싱 실패")
    exit(1)
}

let sourceLang = Locale.Language(identifier: "ja")
let targetLang = Locale.Language(identifier: "ko")

let availability = LanguageAvailability()
let status = await availability.status(from: sourceLang, to: targetLang)
guard status == .installed else {
    eprint("일본어->한국어 번역 언어팩이 준비되지 않았습니다 (상태: \(status)). macOS 설정 > 일반 > 언어 및 지역에서 번역 언어를 설치하세요.")
    exit(1)
}

let session = TranslationSession(installedSource: sourceLang, target: targetLang)

// Empty/whitespace-only items are passed through untouched - no need to
// spend a translation call on them.
var indexed: [(offset: Int, text: String)] = []
for (i, s) in allItems.enumerated() where !s.trimmingCharacters(in: .whitespaces).isEmpty {
    indexed.append((i, s))
}

var results = allItems
let CHUNK_SIZE = 50
let total = indexed.count
var done = 0

var idx = 0
while idx < indexed.count {
    let end = min(idx + CHUNK_SIZE, indexed.count)
    let slice = Array(indexed[idx..<end])
    let requests = slice.enumerated().map { (i, item) in
        TranslationSession.Request(sourceText: item.text, clientIdentifier: "\(i)")
    }

    var succeeded = false
    for attempt in 1...3 {
        do {
            let responses = try await session.translations(from: requests)
            for r in responses {
                guard let cid = r.clientIdentifier, let i = Int(cid) else { continue }
                results[slice[i].offset] = r.targetText
            }
            succeeded = true
            break
        } catch {
            eprint("번역 호출 실패 (시도 \(attempt)/3): \(error.localizedDescription)")
        }
    }

    if !succeeded {
        eprint("청크 번역 실패 - 원문을 그대로 유지합니다.")
    }

    done += slice.count
    eprint("macOS 번역기로 번역 진행 중... (\(done)/\(total))")
    idx = end
}

let outData = try! JSONEncoder().encode(results)
FileHandle.standardOutput.write(outData)
