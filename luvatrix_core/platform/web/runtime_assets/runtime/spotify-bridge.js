const SDK_URL = "https://sdk.scdn.co/spotify-player.js";
const API_BASE = "https://api.spotify.com/v1";

const state = {
  status: "unauthenticated",
  message: "Connect Spotify",
  ready: false,
  authenticated: false,
  isPlaying: false,
  track: "",
  artist: "",
  deviceId: "",
  error: "",
  diagnostic: "",
};

let sdkPromise = null;
let player = null;
let readyPromise = null;
let readyResolve = null;
let readyReject = null;
let readyTimeout = null;
let tokenPayload = null;
let playlistUri = "";
let startedContext = false;

function snapshot() {
  return { ...state };
}

function setState(update) {
  Object.assign(state, update);
}

async function updateDiagnostics() {
  const secure = globalThis.isSecureContext ? "secure" : "not secure";
  const eme = globalThis.navigator?.requestMediaKeySystemAccess ? "EME yes" : "EME no";
  const ua = globalThis.navigator?.userAgent || "unknown browser";
  setState({ diagnostic: `${secure}; ${eme}; ${ua}` });
}

async function fetchToken() {
  if (tokenPayload && Number(tokenPayload.expires_at || 0) * 1000 - Date.now() > 60000) {
    return tokenPayload;
  }
  const response = await fetch("/api/spotify/token", { cache: "no-store" });
  if (response.status === 401) {
    setState({ status: "unauthenticated", authenticated: false, ready: false, message: "Connect Spotify" });
    throw new Error("spotify not authenticated");
  }
  if (!response.ok) {
    const payload = await safeJson(response);
    throw new Error(payload.error || `spotify token failed: ${response.status}`);
  }
  tokenPayload = await response.json();
  playlistUri = String(tokenPayload.playlist_uri || "");
  setState({ authenticated: true });
  return tokenPayload;
}

function loadSdk() {
  if (globalThis.Spotify?.Player) {
    return Promise.resolve();
  }
  if (sdkPromise) {
    return sdkPromise;
  }
  sdkPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = SDK_URL;
    script.async = true;
    script.onerror = () => reject(new Error("Spotify SDK failed to load"));
    globalThis.onSpotifyWebPlaybackSDKReady = () => resolve();
    document.head.appendChild(script);
  });
  return sdkPromise;
}

async function connect({ activate = false } = {}) {
  if (player && state.ready) {
    return snapshot();
  }
  if (player && readyPromise) {
    if (activate) {
      await activatePlayer();
    }
    await waitForReady();
    return snapshot();
  }
  setState({ status: "loading", message: "Connecting Spotify...", error: "" });
  try {
    await fetchToken();
    await loadSdk();
    readyPromise = new Promise((resolve, reject) => {
      readyResolve = resolve;
      readyReject = reject;
      readyTimeout = setTimeout(() => reject(new Error("Spotify device did not become ready")), 30000);
    });
    player = new globalThis.Spotify.Player({
      name: "Alec Candidato",
      getOAuthToken: async (callback) => {
        const token = await fetchToken();
        callback(token.access_token);
      },
      volume: 0.55,
    });
    player.addListener("ready", async ({ device_id }) => {
      setState({ status: "ready", ready: true, deviceId: device_id, message: "Ready" });
      try {
        await transferPlayback(device_id, false);
        clearReadyTimeout();
        readyResolve?.(device_id);
      } catch (error) {
        readyReject?.(error);
      }
    });
    player.addListener("not_ready", () => setState({ ready: false, status: "loading", message: "Spotify device offline" }));
    player.addListener("player_state_changed", (playback) => {
      if (!playback) {
        return;
      }
      const current = playback.track_window?.current_track;
      setState({
        status: playback.paused ? "paused" : "playing",
        isPlaying: !playback.paused,
        track: current?.name || "",
        artist: (current?.artists || []).map((artist) => artist.name).join(", "),
        message: current?.name || "Ready",
      });
    });
    player.addListener("account_error", ({ message }) => failReady(message || "Premium required", "Premium required"));
    player.addListener("authentication_error", ({ message }) => failReady(message || "Spotify auth error", "Auth error"));
    player.addListener("initialization_error", async ({ message }) => {
      await updateDiagnostics();
      failReady(`Open in Firefox or Chrome. ${message || "Spotify SDK initialization error"} (${state.diagnostic})`, "Browser not supported");
    });
    player.addListener("autoplay_failed", () => setState({ status: "error", error: "Browser blocked Spotify autoplay. Click play again.", message: "Click play again" }));
    player.addListener("playback_error", ({ message }) => setState({ status: "error", error: message || "Spotify playback error", message: "Playback error" }));
    if (activate) {
      await activatePlayer();
    }
    const connected = await player.connect();
    if (!connected) {
      throw new Error("Spotify player failed to connect");
    }
    await waitForReady();
  } catch (error) {
    setState({ status: "error", error: error.message || String(error), message: error.message || "Spotify error" });
    if (!state.ready) {
      clearReadyTimeout();
      player = null;
      readyPromise = null;
      readyResolve = null;
      readyReject = null;
    }
  }
  return snapshot();
}

async function activatePlayer() {
  if (!player || typeof player.activateElement !== "function") {
    return;
  }
  try {
    await player.activateElement();
  } catch {
    // Some browsers only allow activation after the SDK has connected. Playback will
    // surface a real error if activation is still required later.
  }
}

async function waitForReady() {
  if (state.ready && state.deviceId) {
    return state.deviceId;
  }
  if (!readyPromise) {
    throw new Error("Spotify player is not connected");
  }
  return readyPromise;
}

function failReady(error, message) {
  setState({ status: "error", error, message });
  clearReadyTimeout();
  readyReject?.(new Error(error));
}

function clearReadyTimeout() {
  if (readyTimeout) {
    clearTimeout(readyTimeout);
    readyTimeout = null;
  }
}

async function transferPlayback(deviceId, play) {
  const token = await fetchToken();
  const response = await fetch(`${API_BASE}/me/player`, {
    method: "PUT",
    headers: authHeaders(token.access_token),
    body: JSON.stringify({ device_ids: [deviceId], play }),
  });
  await requireOk(response, "Spotify transfer failed");
}

async function startPlaylistIfNeeded() {
  if (startedContext || !playlistUri || !state.deviceId) {
    return false;
  }
  const token = await fetchToken();
  await setShuffle(true, state.deviceId, token.access_token);
  const response = await fetch(`${API_BASE}/me/player/play?device_id=${encodeURIComponent(state.deviceId)}`, {
    method: "PUT",
    headers: authHeaders(token.access_token),
    body: JSON.stringify({ context_uri: playlistUri }),
  });
  await requireOk(response, "Spotify play failed");
  startedContext = true;
  setState({ status: "playing", isPlaying: true });
  return true;
}

async function setShuffle(enabled, deviceId, accessToken) {
  const params = new URLSearchParams({ state: enabled ? "true" : "false" });
  if (deviceId) {
    params.set("device_id", deviceId);
  }
  const response = await fetch(`${API_BASE}/me/player/shuffle?${params.toString()}`, {
    method: "PUT",
    headers: authHeaders(accessToken),
  });
  await requireOk(response, "Spotify shuffle failed");
}

async function togglePlay() {
  if (!state.authenticated && state.status === "unauthenticated") {
    login();
    return snapshot();
  }
  await connect({ activate: true });
  if (!state.ready || !player) {
    return snapshot();
  }
  try {
    await waitForReady();
    await activatePlayer();
    const started = await startPlaylistIfNeeded();
    if (!started) {
      await player.togglePlay();
    }
  } catch (error) {
    setState({ status: "error", error: error.message || String(error), message: "Playback error" });
  }
  return snapshot();
}

async function next() {
  await connect({ activate: true });
  if (!state.ready || !player) {
    return snapshot();
  }
  try {
    await waitForReady();
    await player.nextTrack();
  } catch (error) {
    setState({ status: "error", error: error.message || String(error), message: "Next failed" });
  }
  return snapshot();
}

async function previous() {
  await connect({ activate: true });
  if (!state.ready || !player) {
    return snapshot();
  }
  try {
    await waitForReady();
    await player.previousTrack();
  } catch (error) {
    setState({ status: "error", error: error.message || String(error), message: "Previous failed" });
  }
  return snapshot();
}

function login() {
  globalThis.location.href = "/api/spotify/login";
}

function authHeaders(accessToken) {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  };
}

async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

async function requireOk(response, fallback) {
  if (response.ok) {
    return;
  }
  const payload = await safeJson(response);
  const details = payload.error?.message || payload.error || response.statusText || fallback;
  throw new Error(`${fallback}: ${details}`);
}

globalThis.luvatrixSpotify = {
  connect,
  togglePlay,
  next,
  previous,
  getState: snapshot,
  login,
};

updateDiagnostics();
fetchToken()
  .then(() => setState({ status: "paused", message: "Spotify ready", authenticated: true }))
  .catch(() => {});
