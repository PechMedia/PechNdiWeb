# PECH NDI-to-WebRTC Bridge — Application Specification

**Version:** 1.0.15 · **Platform:** Windows 10/11 x64 · **Language:** Python 3.12 · **Packaging:** single-file PyInstaller exe (`PECH_NDI_WebRTC.exe`)

## 1. Purpose

A LAN streaming bridge that ingests a live **NDI / NDI|HX** source (via the official NDI 6 SDK), and re-serves it as a **WebRTC** stream with a design target of **<50 ms glass-to-glass latency**. Any browser on the local network (phone, tablet, PC, smart TV) can view the stream with no plugins or app installs. Distributed as one standalone `.exe` — no Python runtime required on the target machine.

## 2. System Architecture

```
NDI source (LAN)
     │  NDI 6 SDK (Processing.NDI.Lib.x64.dll via ctypes)
     ▼
┌─ NDI_Capture_Thread (ndi_core.py) ─────────────────────┐
│ NDIlib_recv_capture_v2 loop (50ms timeout)             │
│  video → 1-frame "latest slot" (numpy copy, lock)      │
│  audio → float32 planar → s16 stereo interleaved       │
│          → bytearray ring, capped ~200ms               │
└────────────────────────────────────────────────────────┘
     │ shared memory (latest-frame slot + PCM buffer)
     ▼
┌─ asyncio event loop (aiohttp + aiortc) ────────────────┐
│ NDIVideoTrack.recv()  → av.VideoFrame (uyvy422/bgr0)   │
│ NDIAudioTrack.recv()  → av.AudioFrame s16, 20ms        │
│ aiortc RTCPeerConnection → RTP/SRTP over UDP           │
└────────────────────────────────────────────────────────┘
     ▲ signaling: WHEP (POST /api/whep) or WebSocket (/ws)
     │
Browser clients (player.js) + WebView2 desktop shell (/admin)
```

**Thread/process model** (`main.py`):
- **Headless mode** (`--headless`): asyncio loop runs on the main thread; SIGINT/SIGTERM handlers where supported (Windows falls back to `KeyboardInterrupt`).
- **UI mode** (default): server runs in a daemon thread (`AsyncServerThread`, main.py:64) with its own event loop; main thread runs a **pywebview** window (Edge WebView2) pointing at `http://localhost:<port>/admin`. Closing the window stops the loop and joins the thread (2 s timeout).
- **NDI capture** always runs on its own daemon thread (`NDI_Capture_Thread`).

**Latency design** (documented in `latency_optimization_spec.md`, v1.0.8):
1. NDI receiver requests `NDILIB_RECV_COLOR_FORMAT_FASTEST` (usually native UYVY) instead of forced BGRA.
2. Video track holds a **1-frame fresh buffer**: `recv()` polls up to 100 ms (5 ms steps) for a frame with `receive_time` strictly newer than the last processed one (webrtc_server.py:143-156), which prevents the earlier busy-loop CPU saturation.
3. Audio uses **monotonic sample-count PTS** (960 samples = 20 ms @ 48 kHz) and waits up to 100 ms for real data instead of instantly emitting silence; the PCM buffer is capped at 38,400 bytes (~200 ms) by dropping oldest data (ndi_core.py:404-407).
4. No ICE servers — host candidates only, pure-LAN connectivity.

## 3. Module Specifications

### 3.1 `main.py` — Entry point (175 lines)
CLI (argparse, defaults shown by `ArgumentDefaultsHelpFormatter`):

| Flag | Effect |
|---|---|
| `--headless` | No GUI; server on main thread |
| `--port N` | Overrides `server.http_port` |
| `--source NAME` | Overrides `ndi.source_name` |
| `--config PATH` | Config file (default `settings.json` next to exe) |
| `--bind IP` | Overrides `server.bind_address` |

CLI overrides are written back into `settings.json` via `config.update()`. PyInstaller-aware path resolution: web assets come from `sys._MEIPASS/web`, config from the exe directory.

### 3.2 `config_manager.py` — Configuration (99 lines)
Loads/creates/merges `settings.json` against `DEFAULT_SETTINGS`; deep-merges user data over defaults; `update()` persists immediately. Full schema in §6.

### 3.3 `ndi_core.py` — NDI 6 SDK bindings (433 lines)
Pure-ctypes wrapper, no third-party NDI package.
- **`NDISDK`** (singleton): locates `Processing.NDI.Lib.x64.dll` in fixed paths (NDI 6 Runtime → NDI 6 SDK → NDI 5 Runtime → CWD) or `NDI_RUNTIME_DIR_V6` env var; sets argtypes/restypes for Find/Recv v2/v3 APIs; calls `NDIlib_initialize`.
- **`NDIFinder`**: wraps `NDIlib_find_create_v2`; `get_sources(timeout_ms)` returns `[{"name", "url"}]`.
- **`NDIReceiver`**: wraps `NDIlib_recv_create_v3` (recv name `PECH_NDI_WebRTC_Bridge`, `allow_video_fields=False`). `connect()` can hot-switch sources. The capture loop copies raw video via `np.frombuffer(...).copy()` into a dict (`width/height/stride/fourcc/fps/timestamp/data/receive_time`) stored in a single latest-frame slot under `_lock`. Audio: planar float32 → clip → ×32767 → int16 → stereo interleave → `audio_pcm_buffer` under `_audio_lock`. Stats (fps, resolution, frames, connected) recomputed every second; `connected` drops false after 2.5 s without video.

### 3.4 `webrtc_server.py` — Server & media engine (578 lines)
- **`NDIVideoTrack`**: converts the latest NDI frame per FOURCC — UYVY → `uyvy422` (stride-aware), BGRX/BGRA → `bgr0`, RGBA/RGBX → `rgb24`, fallback `bgr24`. Applies `video.target_width/height` via `frame.reformat()` when both are >0. PTS = wall-clock since track start × 90000 (monotonic guard). When no source: dark 1280×720 standby frame.
- **`NDIAudioTrack`**: fixed 48 kHz / stereo / s16 / 960-sample frames; silence inserted if buffer starves after 100 ms wait.
- **`WebRTCStreamServer`**: aiohttp app with CORS + Private-Network-Access middleware (`Access-Control-Allow-*: *`, `Allow-Private-Network: true`). Creates one `RTCPeerConnection` per viewer with fresh video+audio tracks; connections self-remove on `failed/closed/disconnected`. On `start()`, auto-connects and starts the receiver if `app.auto_start` and a source name is set.
- **TLS**: auto-generates a self-signed RSA-2048 cert (10-year, SAN = localhost + 127.0.0.1 + LAN IP) and serves **HTTPS on `http_port + 1`** (default 8026) in addition to HTTP.
- **Encoder tuning** (v1.0.12+): `video.bitrate_kbps` seeds the aiortc H.264/VP8 encoder start and ceiling bitrate (module globals, applied at server start and on settings save). **v1.0.14**: additionally advertises H.264 Constrained-High/High at level 4.2, prefers them in negotiation, and encodes High profile (CABAC + 8×8 transforms) for sharper text/detail — with automatic Baseline fallback for browsers that offer only Baseline. **v1.0.15**: High encoding uses x264 `preset=veryfast` (the stock `medium` preset made 1080p High slower than the 60 fps frame budget, stalling the event loop and degrading latency/audio — measured 25.7→14.6 ms/frame).
- `get_local_ip()`: UDP-connect trick to find the egress IPv4.

### 3.5 `ui_app.py` — Desktop shell (29 lines)
pywebview window: 1280×820 (min 900×600), loads `http://localhost:<port>/admin`, dark background `#0a0e17`. Requires WebView2 runtime (bundled with Win11).

### 3.6 Web frontend (`web/`)
- **`index.html`** — pure full-screen player ("display" surface): edge-to-edge `<video>`, auto-hiding cursor (2.5 s idle), custom right-click context menu (settings, fullscreen, mute, stats overlay, share/QR, link to admin), inline settings modal, share modal with QR (rendered by external `api.qrserver.com`), toast notifications, unmute banner.
- **`admin.html`** — dashboard: settings form (source select with live discovery, resolution, fps, bitrate, sample rate, HTTP port, low-bandwidth checkbox), Save/Start/Stop buttons, LAN URL box, embedded live monitor with FPS/res/bitrate/viewer overlays, share modal.
- **`static/player.js`** — `NDIWebRTCPlayer` class: signaling tries **WebSocket `/ws` first, falls back to WHEP**; recvonly transceivers; on Chrome/Edge sets `receiver.playoutDelayHint = 0` on the **video** receiver only to collapse the receive jitter buffer toward zero (v1.0.13; restricted to video in v1.0.15 because hinting 0 on audio receivers can starve neteq and drop audio); autoplay-policy handling (try unmuted → fall back to muted + banner, the v1.0.10 fix); `getStats()` polling every 1 s (fps/res/bitrate/jitter); auto-reconnect every 2.5 s on disconnect/failure.
- **`static/admin.js`** — settings load/save, source discovery, stream start/stop, `/api/status` polling every 2 s, QR share, fullscreen.
- **`static/style.css`** — dark dashboard theme (560 lines).
- **Root-level legacy files**: `receiver.html` (minimal player page, **not served by any route** — only `web/` is bundled/routed), `sw.js` (pass-through service worker, not registered by any page) and `config.js` (`APP_VERSION = '1.0.15'`, not imported) — kept only because the versioning rule in `CLAUDE.md` references them. Cache-busting is done via `?v=1.0.15` query strings in the HTML.

## 4. HTTP / Signaling API

All responses CORS-`*`. Base: `http://<ip>:8025` (HTTP) and `:8026` (HTTPS, self-signed).

| Method & Path | Function |
|---|---|
| `GET /` | Player page (`index.html`) |
| `GET /admin` | Dashboard (`admin.html`) |
| `GET /static/...` | CSS/JS assets |
| `GET /api/status` | `{ndi_source, connected, fps, width, height, frames_received, active_viewers, lan_ip, lan_url, settings}` |
| `GET /api/sources` | `{sources: [{name, url}]}` (1 s discovery wait; 500 + error on SDK failure) |
| `GET /api/settings` | Full `settings.json` object |
| `POST /api/settings` | Deep-merge update + save; hot-reconnects receiver if `ndi.source_name` changed |
| `POST /api/stream/start` | Body `{source_name?}` — persists source, connects, starts capture thread |
| `POST /api/stream/stop` | Stops capture thread |
| `POST /api/whep` | **WHEP**: body = SDP offer → `201` with SDP answer (`application/sdp`). Also mounted at `POST /`. |
| `GET /ws` | WebSocket signaling: `{"type":"offer","sdp"}` → `{"type":"answer","sdp"}`. (`{"type":"ice"}` is accepted but ignored — a no-op, webrtc_server.py:506-510.) |

Peer connections use `iceServers=[]` (LAN host candidates only).

## 5. Frontend behavior contract

- Player tries WS signaling, falls back to WHEP; reconnects automatically (2.5 s).
- Audio: attempts unmuted autoplay; on browser policy block falls back to muted playback and shows a "click to unmute" banner (v1.0.10 mobile fix).
- Admin polls `/api/status` every 2 s for viewer count, LAN URL, active source.
- Settings saved from either UI write to `settings.json` immediately; changing `http_port`, `low_bandwidth`, or audio params **requires a process restart to take effect** (only `source_name` is hot-applied).

## 6. Configuration reference (`settings.json`)

| Key | Default | Actually enforced? |
|---|---|---|
| `server.http_port` | `8025` | Yes (at startup) |
| `server.bind_address` | `0.0.0.0` | Yes (at startup) |
| `ndi.source_name` | `""` | Yes (hot-switchable) |
| `ndi.color_format` | `"BGRX"` | **No** — receiver always uses `FASTEST` |
| `ndi.low_bandwidth` | `false` | Yes, but only at receiver creation (restart) |
| `video.target_width/height` | `0` (= native) | Yes (live `reformat`) |
| `video.target_fps` | `0` | Yes — track paces output to this rate (0 = native source pacing) |
| `video.bitrate_kbps` | `6000` | Yes — sets the aiortc H.264/VP8 encoder start and ceiling bitrate (module globals; REMB still adapts within range) |
| `video.codec` | `"H264"` | **No** (key ignored) — but the server now advertises H.264 High@4.2 and prefers it when the viewer offers it (v1.0.14); falls back to Baseline for browsers that don't |
| `audio.sample_rate/channels/bitrates` | 48000 / 2 / 128 | **No** — audio track hardcodes 48 kHz stereo s16; Opus via aiortc |
| `app.auto_start` | `true` | Yes |
| `app.title` | window title | Yes (UI mode) |

## 7. Build & deployment

- **`python build_exe.py`** → PyInstaller `--onefile --clean` (`PECH_NDI_WebRTC.spec`): bundles `web/` as data, hidden imports `aiortc, aiohttp, av, numpy, websockets, webview, clr_loader`; UPX enabled; **`console=True`** (a console window appears even in UI mode). Outputs `dist/PECH_NDI_WebRTC.exe` + `dist/start_headless.bat` (launcher that pauses on error exit).
- **Runtime dependencies on target machine**: Windows x64, NDI 6 Runtime (`Processing.NDI.Lib.x64.dll`), WebView2 (for UI mode).
- **Python dependencies**: `aiohttp`, `aiortc`, `av` (PyAV), `numpy`, `cryptography`, `pywebview`, `websockets`, `PyInstaller` (dev).
- Repo docs: `README.md`, `INSTALLATION_AND_USAGE_GUIDE.md`, `latency_optimization_spec.md`. `CLAUDE.md`/`GEMINI.md` carry a version-bump rule (all `?v=` query strings + `sw.js`/`config.js` must match on every change); their Electron/Supabase sections belong to a different project and don't apply here.

## 8. Security & operational notes

- **No authentication** on any endpoint; binds `0.0.0.0` with CORS `*` — trust model is "private LAN only."
- HTTPS uses a **self-signed** cert (browsers show a warning); its main value is secure-context features on mobile clients.
- QR codes are rendered by the **external service `api.qrserver.com`**, which receives the LAN URL (minor leak to a third party; also fails offline).
- Version history shows a tight fix cadence (1.0.1 → 1.0.10) centered on latency, CPU pacing, UYVY correctness, CORS/PNA, and mobile autoplay.

## 9. Observed gaps (factual, from code)

1. Several settings are stored and exposed in the UI but never enforced (audio params, `color_format`; the `codec` key is still ignored even though the server now prefers H.264 High profile when offered); audio runs at fixed 48 kHz stereo regardless of config.
2. `dist/settings.json` contains a stale `network` section (`playout_delay`, `opus_fec`, `half_fps`) read by nothing.
3. `receiver.html`/`sw.js`/`config.js` at repo root are vestigial (not served/registered).
4. WS ICE-candidate handling is a no-op (works on LAN since answers carry host candidates, but would break STUN/TURN scenarios).
5. `.gitignore` lists `*.spec`, yet `PECH_NDI_WebRTC.spec` is tracked.
6. Python-based encoding (aiortc) is CPU-bound at high resolutions/framerates — the practical ceiling for the "<50 ms at 1080p60" goal.

---

*Derived directly from source at v1.0.15, 2026-08-28.*
