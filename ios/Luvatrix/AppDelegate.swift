import UIKit
import QuartzCore

// MARK: - Python bootstrap helpers

private func setupPython() {
    // Locate the bundled Python standard library and site-packages
    guard let resourcePath = Bundle.main.resourcePath else {
        fatalError("Cannot locate bundle resource path")
    }
    let pythonHome = "\(resourcePath)/python"
    let pyPackages = "\(resourcePath)/PyPackages"

    // Set PYTHONHOME so the interpreter finds its stdlib
    setenv("PYTHONHOME", pythonHome, 1)
    // Prevent .pyc writes to read-only bundle
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1)

    LuvatrixPyInitialize()

    // Extend sys.path with our bundled packages directory
    let sysPathUpdate = """
import sys
sys.path.insert(0, '\(pyPackages)')
"""
    LuvatrixPyRunSimpleString(sysPathUpdate)
}

private func loadBundledLaunchConfig() -> [String: String] {
    guard let resourcePath = Bundle.main.resourcePath else {
        return [:]
    }
    let path = "\(resourcePath)/PyPackages/luvatrix_ios_launch_config.json"
    guard let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
          let raw = try? JSONSerialization.jsonObject(with: data, options: []),
          let dict = raw as? [String: Any] else {
        return [:]
    }
    var out: [String: String] = [:]
    for (key, value) in dict {
        out[key] = "\(value)"
    }
    return out
}

private func applyBundledLaunchConfig() -> [String: String] {
    let config = loadBundledLaunchConfig()
    for (key, value) in config {
        if ProcessInfo.processInfo.environment[key] == nil {
            setenv(key, value, 1)
        }
    }
    return config
}

private func envOrConfig(_ key: String, _ config: [String: String], default defaultValue: String) -> String {
    return ProcessInfo.processInfo.environment[key] ?? config[key] ?? defaultValue
}

private func callPythonSetupUI(width: Int, height: Int) {
    let script = """
import sys, traceback, time
try:
    from luvatrix_core.platform.ios.runner import setup_ui
    setup_ui(\(width), \(height))
    print("setup_ui: OK", flush=True)
except BaseException as e:
    print("PYTHON ERROR in setup_ui (" + type(e).__name__ + "):", flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()
    time.sleep(5)
    # Do not re-raise: prevents PyRun_SimpleString from calling exit() on SystemExit
"""
    if LuvatrixPyRunSimpleString(script) != 0 {
        LuvatrixPyErrPrint()
        fatalError("runner.setup_ui() failed — see Python output above")
    }
}

private func callPythonRunLoop(appDir: String) {
    // Acquire the GIL for this background thread before calling any Python API.
    let gstate = LuvatrixPyGILStateEnsure()
    defer { LuvatrixPyGILStateRelease(gstate) }

    let script = """
import sys, traceback, time
print("run_loop: starting", flush=True)
try:
    from luvatrix_core.platform.ios.runner import run_loop
    run_loop('\(appDir)')
    print("run_loop: returned normally", flush=True)
except BaseException as e:
    print("PYTHON ERROR in run_loop (" + type(e).__name__ + "):", flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()
    time.sleep(5)
    # Do not re-raise: prevents PyRun_SimpleString from calling exit() on SystemExit
"""
    if LuvatrixPyRunSimpleString(script) != 0 {
        LuvatrixPyErrPrint()
    }
}

private func callPythonImportProbe() {
    let script = """
import importlib, importlib.util, os, sys, traceback

def log(value=""):
    print(value, flush=True)

def inspect_module(name):
    log("")
    log("=== PROBE " + name + " ===")
    try:
        spec = importlib.util.find_spec(name)
        log("spec=" + repr(spec))
        if spec is not None:
            log("origin=" + repr(getattr(spec, "origin", None)))
            log("loader=" + type(getattr(spec, "loader", None)).__name__)
            origin = getattr(spec, "origin", None)
            if isinstance(origin, str) and origin.endswith(".fwork"):
                try:
                    with open(origin, "r", encoding="utf-8") as fh:
                        target = fh.read().strip()
                    bundle = os.path.dirname(sys.executable)
                    log("fwork_target=" + target)
                    log("framework_exists=" + str(os.path.exists(os.path.join(bundle, target))))
                except BaseException:
                    traceback.print_exc(file=sys.stdout)
    except BaseException:
        log("find_spec failed")
        traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()

    log("importing " + name)
    sys.stdout.flush()
    try:
        module = importlib.import_module(name)
        log("imported " + name + " file=" + repr(getattr(module, "__file__", None)))
    except BaseException:
        log("import failed " + name)
        traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()

log("=== LUVATRIX IOS IMPORT PROBE ===")
log("sys.version=" + sys.version.replace("\\n", " "))
log("sys.platform=" + sys.platform)
log("sys.executable=" + sys.executable)
log("sys.path=" + repr(sys.path))
try:
    import importlib.machinery
    log("EXTENSION_SUFFIXES=" + repr(importlib.machinery.EXTENSION_SUFFIXES))
except BaseException:
    traceback.print_exc(file=sys.stdout)

bundle = os.path.dirname(sys.executable)
for rel in [
    "PyPackages/numpy/core/_multiarray_umath.cpython-312-iphoneos.fwork",
    "PyPackages/numpy/core/_multiarray_umath.cpython-312-ios.fwork",
    "PyPackages/numpy/_core/_multiarray_umath.cpython-312-iphoneos.fwork",
    "Frameworks/numpy.core._multiarray_umath.framework/numpy.core._multiarray_umath",
]:
    path = os.path.join(bundle, rel)
    log("path " + rel + " exists=" + str(os.path.exists(path)))
    if path.endswith(".fwork") and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                log("  content=" + fh.read().strip())
        except BaseException:
            traceback.print_exc(file=sys.stdout)

inspect_module("numpy.core._multiarray_umath")
inspect_module("numpy.core.multiarray")
inspect_module("numpy")
inspect_module("PIL._imaging")
inspect_module("PIL.Image")
log("=== PROBE COMPLETE ===")
sys.stdout.flush()
os._exit(0)
"""
    if LuvatrixPyRunSimpleString(script) != 0 {
        LuvatrixPyErrPrint()
    }
}

private func callPythonTouchEvents(_ events: [[String: Any]]) {
    guard !events.isEmpty else {
        return
    }
    let gstate = LuvatrixPyGILStateEnsure()
    defer { LuvatrixPyGILStateRelease(gstate) }

    guard let data = try? JSONSerialization.data(withJSONObject: events, options: []),
          let json = String(data: data, encoding: .utf8) else {
        print("[ios-hdi] failed to encode touch events")
        return
    }

    let script = """
try:
    from luvatrix_core.platform.ios.hdi_source import enqueue_native_touch_events
    enqueue_native_touch_events(\(json))
except BaseException as e:
    import sys, traceback
    print("PYTHON ERROR in touch HDI (" + type(e).__name__ + "):", flush=True)
    traceback.print_exc(file=sys.stdout)
"""
    if LuvatrixPyRunSimpleString(script) != 0 {
        LuvatrixPyErrPrint()
    }
}

private func callPythonSetAppActive(_ active: Bool) {
    let gstate = LuvatrixPyGILStateEnsure()
    defer { LuvatrixPyGILStateRelease(gstate) }

    let value = active ? "True" : "False"
    let script = """
try:
    from luvatrix_core.platform.ios.lifecycle import set_app_active
    set_app_active(\(value))
except BaseException as e:
    import sys, traceback
    print("PYTHON ERROR in iOS lifecycle (" + type(e).__name__ + "):", flush=True)
    traceback.print_exc(file=sys.stdout)
"""
    if LuvatrixPyRunSimpleString(script) != 0 {
        LuvatrixPyErrPrint()
    }
}

private func callPythonRestoreMetalLayerAfterForeground() {
    let gstate = LuvatrixPyGILStateEnsure()
    defer { LuvatrixPyGILStateRelease(gstate) }

    let script = """
try:
    from luvatrix_core.platform.ios.runner import restore_metal_layer_after_foreground
    restore_metal_layer_after_foreground()
except BaseException as e:
    import sys, traceback
    print("PYTHON ERROR in iOS layer restore (" + type(e).__name__ + "):", flush=True)
    traceback.print_exc(file=sys.stdout)
"""
    if LuvatrixPyRunSimpleString(script) != 0 {
        LuvatrixPyErrPrint()
    }
}

private func currentKeyWindow() -> UIWindow? {
    return UIApplication.shared.connectedScenes
        .compactMap { $0 as? UIWindowScene }
        .flatMap { $0.windows }
        .first { $0.isKeyWindow }
}

final class LuvatrixDisplayLinkTelemetry: NSObject {
    private var displayLink: CADisplayLink?
    private var callbackCount: Int = 0
    private var lastReportTimestamp: CFTimeInterval = 0
    private var reportWindowCount: Int = 0
    private var measuredFPS: Double = 0.0
    private let telemetryPath: String
    private let requestedFPS: Int

    init(requestedFPS: Int) {
        self.requestedFPS = requestedFPS
        let documents = NSSearchPathForDirectoriesInDomains(.documentDirectory, .userDomainMask, true).first
            ?? NSTemporaryDirectory()
        telemetryPath = (documents as NSString).appendingPathComponent("luvatrix_display_link.json")
        super.init()
        setenv("LUVATRIX_IOS_DISPLAY_LINK_TELEMETRY_PATH", telemetryPath, 1)
        setenv("LUVATRIX_IOS_SCREEN_MAX_FPS", "\(UIScreen.main.maximumFramesPerSecond)", 1)
        setenv("LUVATRIX_IOS_LOW_POWER_MODE", ProcessInfo.processInfo.isLowPowerModeEnabled ? "1" : "0", 1)
    }

    func start() {
        guard displayLink == nil else {
            return
        }
        let link = CADisplayLink(target: self, selector: #selector(tick(_:)))
        if #available(iOS 15.0, *) {
            link.preferredFrameRateRange = CAFrameRateRange(
                minimum: Float(min(60, requestedFPS)),
                maximum: Float(requestedFPS),
                preferred: Float(requestedFPS)
            )
        } else {
            link.preferredFramesPerSecond = requestedFPS
        }
        link.add(to: .main, forMode: .common)
        displayLink = link
        print("[ios-displaylink] requested=\(requestedFPS) screen_max=\(UIScreen.main.maximumFramesPerSecond) low_power=\(ProcessInfo.processInfo.isLowPowerModeEnabled ? 1 : 0) path=\(telemetryPath)")
        writeTelemetry(timestamp: CACurrentMediaTime())
    }

    func stop() {
        displayLink?.invalidate()
        displayLink = nil
    }

    @objc private func tick(_ link: CADisplayLink) {
        callbackCount += 1
        reportWindowCount += 1
        let now = link.timestamp
        if lastReportTimestamp == 0 {
            lastReportTimestamp = now
            return
        }
        let elapsed = now - lastReportTimestamp
        if elapsed >= 0.5 {
            measuredFPS = Double(reportWindowCount) / max(0.001, elapsed)
            reportWindowCount = 0
            lastReportTimestamp = now
            writeTelemetry(timestamp: now)
        }
    }

    private func writeTelemetry(timestamp: CFTimeInterval) {
        let payload: [String: Any] = [
            "callback_count": callbackCount,
            "measured_fps": measuredFPS,
            "requested_fps": requestedFPS,
            "screen_max_fps": UIScreen.main.maximumFramesPerSecond,
            "low_power_mode": ProcessInfo.processInfo.isLowPowerModeEnabled,
            "timestamp": timestamp,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: []) else {
            return
        }
        try? data.write(to: URL(fileURLWithPath: telemetryPath), options: [.atomic])
    }
}

final class LuvatrixTouchCaptureView: UIView {
    private var touchIDs: [ObjectIdentifier: Int] = [:]
    private var nextTouchID: Int = 1

    override init(frame: CGRect) {
        super.init(frame: frame)
        isOpaque = false
        backgroundColor = .clear
        isMultipleTouchEnabled = true
        isUserInteractionEnabled = true
        autoresizingMask = [.flexibleWidth, .flexibleHeight]
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    private func touchID(for touch: UITouch) -> Int {
        let key = ObjectIdentifier(touch)
        if let existing = touchIDs[key] {
            return existing
        }
        let assigned = nextTouchID
        nextTouchID += 1
        touchIDs[key] = assigned
        return assigned
    }

    private func emit(_ touches: Set<UITouch>, phase: String) {
        var events: [[String: Any]] = []
        for touch in touches {
            let p = touch.location(in: self)
            events.append([
                "touch_id": touchID(for: touch),
                "phase": phase,
                "x": Double(p.x),
                "y": Double(p.y),
                "force": Double(touch.force),
                "major_radius": Double(touch.majorRadius),
                "tap_count": touch.tapCount,
            ])
        }
        callPythonTouchEvents(events)
        if phase == "up" || phase == "cancel" {
            for touch in touches {
                touchIDs.removeValue(forKey: ObjectIdentifier(touch))
            }
        }
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        emit(touches, phase: "down")
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        emit(touches, phase: "move")
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        emit(touches, phase: "up")
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        emit(touches, phase: "cancel")
    }
}

// MARK: - AppDelegate

@objc class AppDelegate: UIResponder, UIApplicationDelegate {
    // Owned strongly so UIWindow is not deallocated after applicationDidFinishLaunching.
    // (Python also holds a reference via rubicon-objc, but keeping one here is defensive.)
    @objc var window: UIWindow?
    private var displayLinkTelemetry: LuvatrixDisplayLinkTelemetry?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        let screen = UIScreen.main
        let w = Int(screen.bounds.width)
        let h = Int(screen.bounds.height)

        if ProcessInfo.processInfo.arguments.contains("--luvatrix-import-probe")
            || Bundle.main.path(forResource: "LuvatrixImportProbe", ofType: nil) != nil {
            setenv("LUVATRIX_IMPORT_PROBE", "1", 1)
        }

        setupPython()

        let launchConfig = applyBundledLaunchConfig()
        let renderMode = envOrConfig("LUVATRIX_RENDER_MODE", launchConfig, default: "auto")
        let requestedFPS = Int(envOrConfig("LUVATRIX_IOS_PRESENT_FPS", launchConfig, default: "120")) ?? 120
        if renderMode == "scene" || renderMode == "auto" {
            displayLinkTelemetry = LuvatrixDisplayLinkTelemetry(requestedFPS: requestedFPS)
            displayLinkTelemetry?.start()
        }

        // setup_ui must run on the main thread — we are on the main thread here.
        callPythonSetupUI(width: w, height: h)

        if let keyWindow = currentKeyWindow() {
            let capture = LuvatrixTouchCaptureView(frame: keyWindow.bounds)
            keyWindow.addSubview(capture)
            print("[ios-hdi] native touch capture installed frame=\(keyWindow.bounds)")
        } else {
            print("[ios-hdi] native touch capture could not find keyWindow")
        }

        // Release the GIL on the main thread. After LuvatrixPyInitialize() the calling
        // thread owns the GIL. UIKit doesn't need it, and if we don't release it
        // the background thread's LuvatrixPyGILStateEnsure() will deadlock.
        LuvatrixPyEvalSaveThread()

        // Locate the bundled app directory (synced by the run-app CLI before xcodebuild)
        let appDir: String
        if let bundledPath = Bundle.main.path(forResource: "luvatrix_app", ofType: nil, inDirectory: "PyPackages") {
            appDir = bundledPath
        } else {
            fatalError("luvatrix_app not found in bundle — run: uv run main.py run-app <app_dir> --render ios-simulator")
        }

        // run_loop blocks; run it on a high-priority background thread.
        DispatchQueue.global(qos: .userInteractive).async {
            callPythonRunLoop(appDir: appDir)
        }

        return true
    }

    func applicationWillResignActive(_ application: UIApplication) {
        setenv("LUVATRIX_IOS_APP_ACTIVE", "0", 1)
        callPythonSetAppActive(false)
        displayLinkTelemetry?.stop()
    }

    func applicationDidBecomeActive(_ application: UIApplication) {
        setenv("LUVATRIX_IOS_APP_ACTIVE", "1", 1)
        callPythonRestoreMetalLayerAfterForeground()
        callPythonSetAppActive(true)
        // Reset the display link so measured_fps reflects post-foreground rate
        displayLinkTelemetry?.stop()
        displayLinkTelemetry?.start()
    }
}
