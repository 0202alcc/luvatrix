// The probe page: EME key-system probes + Spotify Web Playback SDK init.
// Rendered into the WKWebView as an HTML string. Every step reports through
// window.webkit.messageHandlers.probe.postMessage({...}).

func probePageHTML(token: String?, eventWindowSeconds: Int) -> String {
    let tokenJS = token.map { "\"\($0)\"" } ?? "null"
    return """
    <!doctype html>
    <html><head><meta charset="utf-8"><title>EME Probe</title></head>
    <body style="background:#111;color:#ddd;font:12px monospace">
    <pre id="log">eme-probe running…</pre>
    <script>
    const TOKEN = \(tokenJS);
    const EVENT_WINDOW_MS = \(eventWindowSeconds * 1000);
    const results = [];

    function report(obj) {
      results.push(obj);
      try {
        window.webkit.messageHandlers.probe.postMessage(obj);
      } catch (e) {
        document.getElementById("log").textContent += "\\n[local] " + JSON.stringify(obj);
      }
    }

    window.onSpotifyWebPlaybackSDKReady = () => {
      report({type: "sdk_ready", spotifyGlobal: typeof window.Spotify});
      maybeRunPlayer();
    };

    const KEY_SYSTEMS = [
      "com.widevine.alpha",
      "com.apple.fps",
      "com.apple.fps.1_0",
      "com.apple.fps.2_0",
      "com.apple.fps.3_0",
      "org.w3.clearkey"
    ];

    const CONFIGS = {
      aac_mp4: [{
        initDataTypes: ["cenc", "sinf", "skd", "keyids"],
        audioCapabilities: [{contentType: 'audio/mp4; codecs="mp4a.40.2"'}],
        distinctiveIdentifier: "optional",
        persistentState: "optional",
        sessionTypes: ["temporary"]
      }],
      opus_webm: [{
        initDataTypes: ["cenc", "webm", "keyids"],
        audioCapabilities: [{contentType: 'audio/webm; codecs="opus"'}],
        distinctiveIdentifier: "optional",
        persistentState: "optional",
        sessionTypes: ["temporary"]
      }]
    };

    async function probeKeySystem(name) {
      const out = {type: "key_system", keySystem: name, configs: {}};
      if (!("requestMediaKeySystemAccess" in navigator)) {
        out.configs.error = "navigator.requestMediaKeySystemAccess is undefined";
        report(out);
        return;
      }
      for (const [label, config] of Object.entries(CONFIGS)) {
        try {
          const access = await navigator.requestMediaKeySystemAccess(name, config);
          const entry = {access: "granted", configuration: access.getConfiguration().audioCapabilities
            ? "audioCapabilities present" : "no audioCapabilities echoed"};
          try {
            const keys = await access.createMediaKeys();
            entry.createMediaKeys = "ok";
            try {
              const session = keys.createSession("temporary");
              entry.createSession = session ? "ok" : "null";
              try { await session.close(); } catch (e) { /* session had no request; fine */ }
            } catch (e) {
              entry.createSession = e.name + ": " + e.message;
            }
          } catch (e) {
            entry.createMediaKeys = e.name + ": " + e.message;
          }
          out.configs[label] = entry;
        } catch (e) {
          out.configs[label] = {access: "rejected", error: e.name, message: String(e.message).slice(0, 160)};
        }
      }
      report(out);
    }

    function loadSdkScript() {
      const s = document.createElement("script");
      s.src = "https://sdk.scdn.co/spotify-player.js";
      s.onload = () => report({type: "sdk_script_loaded"});
      s.onerror = (e) => {
        report({type: "fatal", stage: "sdk_script", error: "script load failed (network?)"});
        report({type: "done"});
      };
      document.head.appendChild(s);
      // If the ready callback never fires, the script loaded but didn't init.
      setTimeout(() => {
        if (typeof window.Spotify === "undefined") {
          report({type: "sdk_ready_timeout", note: "script present but onSpotifyWebPlaybackSDKReady never fired"});
          report({type: "done"});
        }
      }, 10000);
    }

    function maybeRunPlayer() {
      if (!TOKEN) {
        report({type: "note", text: "no --token given; skipping Spotify.Player connect(). Re-run with a streaming-scoped token for the full answer."});
        report({type: "done"});
        return;
      }
      try {
        const player = new Spotify.Player({
          name: "luvatrix-eme-probe",
          getOAuthToken: (cb) => cb(TOKEN),
          volume: 0.3
        });
        player.addListener("ready", (d) => report({type: "player_ready", device_id: d.device_id}));
        player.addListener("not_ready", (d) => report({type: "player_not_ready", device_id: d.device_id}));
        player.addListener("initialization_error", (e) => report({type: "initialization_error", message: e.message}));
        player.addListener("authentication_error", (e) => report({type: "authentication_error", message: e.message}));
        player.addListener("account_error", (e) => report({type: "account_error", message: e.message}));
        player.addListener("playback_error", (e) => report({type: "playback_error", message: e.message}));
        player.addListener("player_state_changed", (s) => report({type: "player_state_changed", paused: s && s.paused, track: s && s.track_window && s.track_window.current_track && s.track_window.current_track.name}));
        player.connect().then((ok) => report({type: "connect_result", ok: ok}));
        setTimeout(() => report({type: "done"}), EVENT_WINDOW_MS);
      } catch (e) {
        report({type: "fatal", stage: "player_construct", error: e.name + ": " + e.message});
        report({type: "done"});
      }
    }

    (async () => {
      report({type: "meta", ua: navigator.userAgent, platform: navigator.platform,
              hasEME: ("requestMediaKeySystemAccess" in navigator),
              tokenProvided: !!TOKEN});
      for (const ks of KEY_SYSTEMS) { await probeKeySystem(ks); }
      loadSdkScript();
    })().catch((e) => {
      report({type: "fatal", stage: "top", error: e.name + ": " + e.message});
      report({type: "done"});
    });
    </script></body></html>
    """
}
