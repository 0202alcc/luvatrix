import AppKit
import WebKit
import Foundation

// EME probe harness (SL-30): opens a WKWebView, probes
// navigator.requestMediaKeySystemAccess for Widevine / FairPlay / ClearKey
// with audio configs, loads the Spotify Web Playback SDK, and — when a
// streaming-scoped OAuth token is passed — connects a Spotify.Player and
// reports its events. Results stream to stdout and are written to JSON.

struct Options {
    var token: String? = ProcessInfo.processInfo.environment["SPOTIFY_ACCESS_TOKEN"]
    var chromeUA = false
    var outPath = "eme-probe-results.json"
    var timeoutSeconds: Double = 45
    var eventWindowSeconds = 25
}

func parseArgs() -> Options {
    var opts = Options()
    var it = CommandLine.arguments.dropFirst().makeIterator()
    while let arg = it.next() {
        switch arg {
        case "--token": opts.token = it.next()
        case "--chrome-ua": opts.chromeUA = true
        case "--out": if let p = it.next() { opts.outPath = p }
        case "--timeout": if let t = it.next(), let v = Double(t) { opts.timeoutSeconds = v }
        case "--event-window": if let t = it.next(), let v = Int(t) { opts.eventWindowSeconds = v }
        case "--help", "-h":
            print("""
            eme-probe [--token <oauth access token>] [--chrome-ua] \
            [--out <path>] [--timeout <secs>] [--event-window <secs>]
            Token may also come from SPOTIFY_ACCESS_TOKEN.
            """)
            exit(0)
        default:
            FileHandle.standardError.write("unknown argument: \(arg)\n".data(using: .utf8)!)
            exit(2)
        }
    }
    return opts
}

final class ProbeHandler: NSObject, WKScriptMessageHandler {
    var messages: [[String: Any]] = []
    var onDone: (() -> Void)?

    func userContentController(_ controller: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard let dict = message.body as? [String: Any], let type = dict["type"] as? String else {
            return
        }
        messages.append(dict)
        if let data = try? JSONSerialization.data(withJSONObject: dict),
           let line = String(data: data, encoding: .utf8) {
            print("[probe] \(line)")
            fflush(stdout)
        }
        if type == "done" || type == "fatal" && (dict["stage"] as? String) == "sdk_script" {
            onDone?()
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let opts: Options
    let handler = ProbeHandler()
    var window: NSWindow?
    var finished = false

    init(opts: Options) { self.opts = opts }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let config = WKWebViewConfiguration()
        config.userContentController.add(handler, name: "probe")
        if #available(macOS 10.13, *) {
            config.mediaTypesRequiringUserActionForPlayback = []
        }
        let webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 520, height: 360),
                                configuration: config)
        if opts.chromeUA {
            webView.customUserAgent =
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 360),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered, defer: false)
        window.title = "EME Probe"
        window.contentView = webView
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window

        handler.onDone = { [weak self] in self?.finish() }
        DispatchQueue.main.asyncAfter(deadline: .now() + opts.timeoutSeconds) { [weak self] in
            self?.finish()
        }

        let html = probePageHTML(token: opts.token,
                                 eventWindowSeconds: opts.eventWindowSeconds)
        webView.loadHTMLString(html, baseURL: URL(string: "https://localhost/"))
    }

    func finish() {
        guard !finished else { return }
        finished = true
        let payload: [String: Any] = [
            "harness": "eme-probe",
            "date": ISO8601DateFormatter().string(from: Date()),
            "chromeUA": opts.chromeUA,
            "tokenProvided": opts.token != nil,
            "results": handler.messages,
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: payload,
                                                  options: [.prettyPrinted, .sortedKeys])
            try data.write(to: URL(fileURLWithPath: opts.outPath), options: .atomic)
            print("[probe] wrote \(handler.messages.count) events to \(opts.outPath)")
        } catch {
            FileHandle.standardError.write("[probe] failed writing \(opts.outPath): \(error)\n"
                .data(using: .utf8)!)
        }
        NSApp.terminate(nil)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
}

let opts = parseArgs()
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = AppDelegate(opts: opts)
app.delegate = delegate
app.run()
