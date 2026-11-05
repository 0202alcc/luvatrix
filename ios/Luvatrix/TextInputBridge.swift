import UIKit

// Text-input boundary for Python's `luvatrix_core.platform.ios.text_input`.
// A hidden (offscreen) UITextView becomes first responder when the app asks
// for focus, so tapping the composer summons the real iOS keyboard with native
// editing, autocorrect, and dictation. The delegate forwards text, selection,
// and editing-end into Python, and keyboard frame notifications carry the
// keyboard height and animation duration so the app can lift its composer in
// sync with the keyboard. rubicon-objc resolves the exported class name and
// calls the static methods; the ObjC selectors surface to Python as
// focusComposer() / resignComposer() / setComposerText_ /
// setComposerPlaceholder_ / isComposerFocused().
@objc(LuvatrixTextInput)
final class TextInputBridge: NSObject, UITextViewDelegate {
    private static let shared = TextInputBridge()

    private var field: UITextView?
    private var placeholder: String = ""
    private var observersInstalled = false

    // MARK: - Python -> Swift (called from a Python thread; hop to main)

    @objc static func focusComposer() -> Bool {
        DispatchQueue.main.async { shared.focusOnMain() }
        return true
    }

    @objc static func resignComposer() -> Bool {
        DispatchQueue.main.async { shared.resignOnMain() }
        return true
    }

    @objc static func setComposerText(_ text: String) {
        DispatchQueue.main.async { shared.setTextOnMain(text) }
    }

    @objc static func setComposerPlaceholder(_ text: String) {
        DispatchQueue.main.async { shared.placeholder = text }
    }

    @objc static func isComposerFocused() -> Bool {
        if Thread.isMainThread {
            return shared.field?.isFirstResponder ?? false
        }
        return DispatchQueue.main.sync { shared.field?.isFirstResponder ?? false }
    }

    // MARK: - main-thread field management

    private func ensureField() -> UITextView? {
        if let field {
            return field
        }
        guard let window = Self.keyWindow() else {
            print("[ios-text-input] no key window; cannot attach hidden text field")
            return nil
        }
        // Offscreen but in the window hierarchy so it can own first responder.
        let view = UITextView(frame: CGRect(x: 0, y: -80, width: 4, height: 4))
        view.font = .systemFont(ofSize: 17)
        view.textColor = .clear
        view.backgroundColor = .clear
        view.autocorrectionType = .default
        view.autocapitalizationType = .sentences
        view.returnKeyType = .default
        view.delegate = self
        window.addSubview(view)
        field = view
        installKeyboardObservers()
        return view
    }

    private static func keyWindow() -> UIWindow? {
        return UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap { $0.windows }
            .first { $0.isKeyWindow }
    }

    private func focusOnMain() {
        guard let view = ensureField() else {
            return
        }
        if !view.isFirstResponder {
            view.becomeFirstResponder()
        }
    }

    private func resignOnMain() {
        guard let view = field, view.isFirstResponder else {
            return
        }
        view.resignFirstResponder()
    }

    private func setTextOnMain(_ text: String) {
        guard let view = ensureField() else {
            return
        }
        if view.text != text {
            view.text = text
            view.selectedRange = NSRange(location: (text as NSString).length, length: 0)
        }
    }

    // MARK: - UITextViewDelegate

    func textViewDidChange(_ textView: UITextView) {
        emitText(textView)
    }

    func textViewDidChangeSelection(_ textView: UITextView) {
        emitText(textView)
    }

    func textViewDidEndEditing(_ textView: UITextView) {
        emitEvents([["type": "editing_end"]])
    }

    private func emitText(_ textView: UITextView) {
        let text = textView.text ?? ""
        // UITextView ranges are UTF-16 based; Python indexes Unicode scalars.
        let caret16 = max(0, min(textView.selectedRange.location, (text as NSString).length))
        let caret = String(decoding: text.utf16.prefix(caret16), as: UTF16.self).unicodeScalars.count
        emitEvents([["type": "text", "text": text, "selection": caret]])
    }

    // MARK: - keyboard notifications

    private func installKeyboardObservers() {
        guard !observersInstalled else {
            return
        }
        observersInstalled = true
        let center = NotificationCenter.default
        center.addObserver(
            self,
            selector: #selector(keyboardWillChangeFrame(_:)),
            name: UIResponder.keyboardWillChangeFrameNotification,
            object: nil
        )
        center.addObserver(
            self,
            selector: #selector(keyboardWillHide(_:)),
            name: UIResponder.keyboardWillHideNotification,
            object: nil
        )
    }

    @objc private func keyboardWillChangeFrame(_ note: Notification) {
        guard let info = note.userInfo,
              let frame = info[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else {
            return
        }
        let duration = (info[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double) ?? 0.25
        let screenH = Self.keyWindow()?.bounds.height ?? UIScreen.main.bounds.height
        let height = max(0.0, screenH - frame.minY)
        emitEvents([["type": "keyboard", "height": height, "duration": duration]])
    }

    @objc private func keyboardWillHide(_ note: Notification) {
        let duration = (note.userInfo?[UIResponder.keyboardAnimationDurationUserInfoKey] as? Double) ?? 0.25
        emitEvents([["type": "keyboard", "height": 0.0, "duration": duration]])
    }

    // MARK: - Swift -> Python

    private func emitEvents(_ events: [[String: Any]]) {
        guard let data = try? JSONSerialization.data(withJSONObject: events, options: []),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        let gstate = LuvatrixPyGILStateEnsure()
        defer { LuvatrixPyGILStateRelease(gstate) }
        let script = """
        try:
            from luvatrix_core.platform.ios.text_input import enqueue_native_text_input_events
            enqueue_native_text_input_events(\(json))
        except BaseException as e:
            import sys, traceback
            print("PYTHON ERROR in text input bridge (" + type(e).__name__ + "):", flush=True)
            traceback.print_exc(file=sys.stdout)
        """
        if LuvatrixPyRunSimpleString(script) != 0 {
            LuvatrixPyErrPrint()
        }
    }
}
