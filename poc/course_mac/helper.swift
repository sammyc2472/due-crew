// Course on a Mac (PoC): Apple's on-device model, for the add-on.
//
// Built on the Mac that runs it (the add-on calls swiftc once), then kept
// running: one JSON request a line on stdin, one JSON answer a line on
// stdout.
//   {"id": 1, "op": "probe"}
//   {"id": 2, "op": "ask", "instructions": "…", "prompt": "…", "schema": {…}, "max_tokens": 400}
//   {"id": 3, "op": "pdf", "path": "/…/calendar.pdf"}
// A schema is the add-on's small subset (object with props, array with
// items and max, string with enum, integer, boolean); the answer is guided
// to it, so it always has that shape.
//
// On-device only: this uses SystemLanguageModel, never Private Cloud Compute.
// Nothing here touches the network.
import Foundation
import PDFKit
#if canImport(FoundationModels)
import FoundationModels
#endif

func reply(_ obj: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: obj, options: []),
       let line = String(data: data, encoding: .utf8) {
        FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
    }
}

func millis(_ since: Date) -> Int {
    return Int(Date().timeIntervalSince(since) * 1000)
}

func pdfText(_ path: String) -> [String: Any] {
    guard let doc = PDFDocument(url: URL(fileURLWithPath: path)) else {
        return ["ok": false, "error": "couldn't open the PDF"]
    }
    return ["ok": true, "text": doc.string ?? "", "pages": doc.pageCount]
}

#if canImport(FoundationModels)
@available(macOS 26.0, *)
func modelToUse() -> SystemLanguageModel {
    return __MODEL__
}

@available(macOS 26.0, *)
func dyn(_ s: [String: Any], _ path: String) -> DynamicGenerationSchema {
    let type = s["type"] as? String ?? "string"
    let desc = s["description"] as? String
    switch type {
    case "object":
        var props: [DynamicGenerationSchema.Property] = []
        for p in s["props"] as? [[String: Any]] ?? [] {
            let name = p["name"] as? String ?? "x"
            let sub = p["schema"] as? [String: Any] ?? [:]
            props.append(DynamicGenerationSchema.Property(
                name: name,
                description: p["description"] as? String,
                schema: dyn(sub, path + "_" + name),
                isOptional: p["optional"] as? Bool ?? false))
        }
        return DynamicGenerationSchema(name: path, description: desc, properties: props)
    case "array":
        let item = dyn(s["items"] as? [String: Any] ?? [:], path + "_item")
        return DynamicGenerationSchema(arrayOf: item, minimumElements: nil, maximumElements: s["max"] as? Int)
    case "integer":
        return DynamicGenerationSchema(type: Int.self)
    case "boolean":
        return DynamicGenerationSchema(type: Bool.self)
    default:
        if let choices = s["enum"] as? [String], !choices.isEmpty {
            return DynamicGenerationSchema(name: path, description: desc, anyOf: choices)
        }
        return DynamicGenerationSchema(type: String.self)
    }
}

@available(macOS 26.0, *)
func probe() -> [String: Any] {
    let model = modelToUse()
    if case .available = model.availability {
        return ["ok": true, "available": true, "context": __CONTEXT__]
    }
    return ["ok": true, "available": false, "reason": String(describing: model.availability)]
}

@available(macOS 26.0, *)
func ask(_ req: [String: Any]) async -> [String: Any] {
    let started = Date()
    do {
        let session = LanguageModelSession(model: modelToUse(), instructions: req["instructions"] as? String ?? "")
        let prompt = req["prompt"] as? String ?? ""
        let options = GenerationOptions(sampling: .greedy, temperature: nil,
                                        maximumResponseTokens: req["max_tokens"] as? Int)
        if let s = req["schema"] as? [String: Any] {
            let schema = try GenerationSchema(root: dyn(s, "Answer"), dependencies: [])
            let r = try await session.respond(to: prompt, schema: schema, options: options)
            return ["ok": true, "json": r.content.jsonString, "ms": millis(started)]
        }
        let r = try await session.respond(to: prompt, options: options)
        return ["ok": true, "text": r.content, "ms": millis(started)]
    } catch {
        return ["ok": false, "error": String(describing: error), "ms": millis(started)]
    }
}
#endif

while let line = readLine() {
    guard let data = line.data(using: .utf8),
          let req = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
        reply(["ok": false, "error": "bad request"])
        continue
    }
    let op = req["op"] as? String ?? ""
    var out: [String: Any] = ["ok": false, "error": "unknown op"]
    if op == "pdf" {
        out = pdfText(req["path"] as? String ?? "")
    } else if op == "probe" || op == "ask" {
        #if canImport(FoundationModels)
        if #available(macOS 26.0, *) {
            out = op == "probe" ? probe() : await ask(req)
        } else {
            out = ["ok": false, "error": "needs macOS 26 or later"]
        }
        #else
        out = ["ok": false, "error": "this Mac's Swift has no FoundationModels: update Xcode or its Command Line Tools"]
        #endif
    }
    out["id"] = req["id"] ?? 0
    reply(out)
}
