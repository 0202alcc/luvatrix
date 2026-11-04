import AuthenticationServices
import UIKit

// ASWebAuthenticationSession boundary for Python's
// `luvatrix_core.platform.ios.auth_session`. Python drives the exported class
// through rubicon-objc (startSession:callbackScheme: / cancelSession); the
// completion handler reports back into Python through the PyRunSimpleString
// bridge. The ainomic:// callback may also arrive through the scene delegate's
// openURLContexts — both delivery paths converge in Python's url_router.

// JSON-encode a Swift string into a literal that parses as both JSON and a
// Python string literal (JSON string escapes are a subset of Python's), so it
// can be embedded safely in a PyRunSimpleString script.
func luvatrixPythonStringLiteral(_ value: String) -> String {
    guard let data = try? JSONSerialization.data(withJSONObject: [value], options: []),
          var json = String(data: data, encoding: .utf8),
          json.count >= 2 else {
        return "\"\""
    }
    json.removeFirst()
    json.removeLast()
    return json
}

// Delivers the web-auth result to the waiting Python sign-in flow:
// the callback URL on success, nil when the user cancelled. The completion
// handler fires on the main queue and the Python side performs the token
// exchange over the network, so the hop into Python runs in the background.
func callPythonAuthSessionCallback(_ callbackURL: String?) {
    DispatchQueue.global(qos: .userInitiated).async {
        callPythonAuthSessionCallbackSync(callbackURL)
    }
}

private func callPythonAuthSessionCallbackSync(_ callbackURL: String?) {
    let gstate = LuvatrixPyGILStateEnsure()
    defer { LuvatrixPyGILStateRelease(gstate) }

    let argument = callbackURL.map { luvatrixPythonStringLiteral($0) } ?? "None"
    let script = """
try:
    from luvatrix_core.platform.ios.auth_session import complete_auth_session
    handled = complete_auth_session(\(argument))
    print("[ios-auth] auth session callback handled=" + str(handled), flush=True)
except BaseException as e:
    import sys, traceback
    print("PYTHON ERROR in auth session callback (" + type(e).__name__ + "):", flush=True)
    traceback.print_exc(file=sys.stdout)
"""
    if LuvatrixPyRunSimpleString(script) != 0 {
        LuvatrixPyErrPrint()
    }
}

@objc(LuvatrixAuthSession)
final class AuthSessionBridge: NSObject {
    private static var active: AuthSessionBridge?

    private var session: ASWebAuthenticationSession?

    @objc static func startSession(_ urlString: String, callbackScheme: String) -> Bool {
        guard let url = URL(string: urlString) else {
            print("[ios-auth] invalid authorize URL")
            return false
        }
        let bridge = AuthSessionBridge()
        let session = ASWebAuthenticationSession(
            url: url,
            callbackURLScheme: callbackScheme
        ) { callbackURL, error in
            AuthSessionBridge.active = nil
            if let callbackURL = callbackURL {
                callPythonAuthSessionCallback(callbackURL.absoluteString)
            } else {
                if let nsError = error as NSError?,
                   nsError.code != ASWebAuthenticationSessionError.canceledLogin.rawValue {
                    print("[ios-auth] session failed: \(nsError.localizedDescription)")
                }
                callPythonAuthSessionCallback(nil)
            }
        }
        session.presentationContextProvider = bridge
        session.prefersEphemeralWebBrowserSession = false
        guard session.start() else {
            print("[ios-auth] could not start ASWebAuthenticationSession")
            return false
        }
        bridge.session = session
        AuthSessionBridge.active = bridge
        return true
    }

    @objc static func cancelSession() {
        active?.session?.cancel()
        active = nil
    }
}

extension AuthSessionBridge: ASWebAuthenticationPresentationContextProviding {
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        let keyWindow = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap { $0.windows }
            .first { $0.isKeyWindow }
        return keyWindow ?? ASPresentationAnchor()
    }
}
