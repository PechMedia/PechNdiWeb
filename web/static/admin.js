/**
 * Admin Panel & Stream Controller Script
 */

let player = null;
let currentSettings = {};

document.addEventListener('DOMContentLoaded', async () => {
  initPlayer();
  await loadSettings();
  await refreshSources();
  startStatusPolling();
  setupEventListeners();
});

function initPlayer() {
  const videoEl = document.getElementById('remoteVideo');
  if (!videoEl) return;

  player = new NDIWebRTCPlayer(videoEl, {
    onStatusChange: (status, message) => {
      const dot = document.getElementById('statusDot');
      const text = document.getElementById('statusText');
      if (dot) {
        dot.className = 'status-dot ' + status;
      }
      if (text) {
        text.innerText = message;
      }
    },
    onStatsUpdate: (stats) => {
      const fpsEl = document.getElementById('statFps');
      const resEl = document.getElementById('statRes');
      const bitEl = document.getElementById('statBitrate');
      if (fpsEl && stats.fps) fpsEl.innerText = `${stats.fps} FPS`;
      if (resEl && stats.width) resEl.innerText = `${stats.width}x${stats.height}`;
      if (bitEl && stats.bitrate) bitEl.innerText = `${stats.bitrate} kbps`;
    }
  });

  player.start();
}

async function loadSettings() {
  try {
    const res = await fetch('/api/settings');
    currentSettings = await res.json();
    populateForm(currentSettings);
  } catch (e) {
    console.error('Failed to load settings:', e);
  }
}

function populateForm(settings) {
  if (settings.ndi) {
    const sourceSelect = document.getElementById('ndiSourceSelect');
    if (sourceSelect && settings.ndi.source_name) {
      ensureOption(sourceSelect, settings.ndi.source_name, settings.ndi.source_name);
      sourceSelect.value = settings.ndi.source_name;
    }
    const lowBw = document.getElementById('lowBandwidthCheck');
    if (lowBw) lowBw.checked = !!settings.ndi.low_bandwidth;
  }

  if (settings.video) {
    const resSelect = document.getElementById('resolutionSelect');
    if (resSelect) {
      resSelect.value = `${settings.video.target_width}x${settings.video.target_height}`;
    }
    const fpsSelect = document.getElementById('fpsSelect');
    if (fpsSelect) fpsSelect.value = String(settings.video.target_fps || 0);
    const bitInput = document.getElementById('bitrateInput');
    if (bitInput) bitInput.value = settings.video.bitrate_kbps || 6000;
  }

  if (settings.audio) {
    const srSelect = document.getElementById('audioSampleRate');
    if (srSelect) srSelect.value = String(settings.audio.sample_rate || 48000);
  }

  if (settings.server) {
    const portInput = document.getElementById('httpPortInput');
    if (portInput) portInput.value = settings.server.http_port || 8025;
  }
}

function ensureOption(select, value, text) {
  for (let opt of select.options) {
    if (opt.value === value) return;
  }
  const opt = document.createElement('option');
  opt.value = value;
  opt.innerText = text;
  select.appendChild(opt);
}

async function refreshSources() {
  const select = document.getElementById('ndiSourceSelect');
  const btn = document.getElementById('btnRefreshSources');
  if (!select) return;

  if (btn) btn.disabled = true;
  select.disabled = true;

  try {
    const res = await fetch('/api/sources');
    const data = await res.json();
    const currentVal = select.value || (currentSettings.ndi && currentSettings.ndi.source_name) || '';

    select.innerHTML = '<option value="">-- Select NDI Stream --</option>';
    if (data.sources && data.sources.length > 0) {
      data.sources.forEach(src => {
        const opt = document.createElement('option');
        opt.value = src.name;
        opt.innerText = `${src.name} (${src.url || 'LAN'})`;
        select.appendChild(opt);
      });
      if (currentVal) select.value = currentVal;
    } else {
      const opt = document.createElement('option');
      opt.value = '';
      opt.innerText = 'No active NDI sources found';
      opt.disabled = true;
      select.appendChild(opt);
    }
  } catch (e) {
    console.error('Failed to discover sources:', e);
  } finally {
    select.disabled = false;
    if (btn) btn.disabled = false;
  }
}

async function saveSettings(e) {
  if (e) e.preventDefault();

  const sourceName = document.getElementById('ndiSourceSelect')?.value || '';
  const lowBandwidth = !!document.getElementById('lowBandwidthCheck')?.checked;
  const resVal = document.getElementById('resolutionSelect')?.value || '0x0';
  const [w, h] = resVal.split('x').map(Number);
  const targetFps = Number(document.getElementById('fpsSelect')?.value || 0);
  const bitrate = Number(document.getElementById('bitrateInput')?.value || 6000);
  const sampleRate = Number(document.getElementById('audioSampleRate')?.value || 48000);
  const port = Number(document.getElementById('httpPortInput')?.value || 8025);

  const payload = {
    ndi: {
      source_name: sourceName,
      low_bandwidth: lowBandwidth,
    },
    video: {
      target_width: w,
      target_height: h,
      target_fps: targetFps,
      bitrate_kbps: bitrate,
    },
    audio: {
      sample_rate: sampleRate,
    },
    server: {
      http_port: port,
    },
  };

  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast('Settings saved to settings.json successfully!');
      currentSettings = payload;
    } else {
      showToast('Failed to save settings', true);
    }
  } catch (e) {
    showToast('Error: ' + e.message, true);
  }
}

async function startStream() {
  const sourceName = document.getElementById('ndiSourceSelect')?.value;
  try {
    const res = await fetch('/api/stream/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_name: sourceName }),
    });
    if (res.ok) {
      showToast('NDI Stream Started');
      if (player) player.start();
    }
  } catch (e) {
    showToast('Error starting stream: ' + e.message, true);
  }
}

async function stopStream() {
  try {
    const res = await fetch('/api/stream/stop', { method: 'POST' });
    if (res.ok) {
      showToast('NDI Stream Stopped');
      if (player) player.stop();
    }
  } catch (e) {
    showToast('Error stopping stream: ' + e.message, true);
  }
}

function startStatusPolling() {
  setInterval(async () => {
    try {
      const res = await fetch('/api/status');
      if (!res.ok) return;
      const status = await res.json();

      const viewersEl = document.getElementById('activeViewersCount');
      if (viewersEl) viewersEl.innerText = status.active_viewers;

      const lanUrlEl = document.getElementById('lanUrlText');
      if (lanUrlEl) lanUrlEl.innerText = status.lan_url;

      const lanInput = document.getElementById('modalLanUrlInput');
      if (lanInput) lanInput.value = status.lan_url;

      const activeSrcEl = document.getElementById('activeSourceLabel');
      if (activeSrcEl) activeSrcEl.innerText = status.ndi_source || 'None';
    } catch (e) {}
  }, 2000);
}

function setupEventListeners() {
  document.getElementById('btnRefreshSources')?.addEventListener('click', refreshSources);
  document.getElementById('settingsForm')?.addEventListener('submit', saveSettings);
  document.getElementById('btnStartStream')?.addEventListener('click', startStream);
  document.getElementById('btnStopStream')?.addEventListener('click', stopStream);

  // Unmute Banner
  const banner = document.getElementById('unmuteBanner');
  if (banner) {
    banner.addEventListener('click', () => {
      const video = document.getElementById('remoteVideo');
      if (video) {
        video.muted = false;
        video.play();
      }
      banner.style.display = 'none';
    });
  }

  // Fullscreen
  document.getElementById('btnFullscreen')?.addEventListener('click', () => {
    const stage = document.getElementById('videoStage');
    if (!stage) return;
    if (!document.fullscreenElement) {
      stage.requestFullscreen().catch(err => alert(err.message));
    } else {
      document.exitFullscreen();
    }
  });

  // Share Modal
  const modal = document.getElementById('shareModal');
  document.getElementById('btnShare')?.addEventListener('click', () => {
    if (modal) {
      modal.classList.add('active');
      renderQrCode();
    }
  });
  document.getElementById('btnCloseModal')?.addEventListener('click', () => {
    if (modal) modal.classList.remove('active');
  });

  // Copy Link
  document.getElementById('btnCopyUrl')?.addEventListener('click', () => {
    const input = document.getElementById('modalLanUrlInput');
    if (input) {
      navigator.clipboard.writeText(input.value);
      showToast('LAN Stream URL copied to clipboard!');
    }
  });
}

function renderQrCode() {
  const container = document.getElementById('qrCodeContainer');
  const lanInput = document.getElementById('modalLanUrlInput');
  if (!container || !lanInput) return;
  const url = lanInput.value || window.location.href;
  container.innerHTML = `<img src="https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(url)}" alt="QR Code" width="180" height="180" style="border-radius: 8px;" />`;
}

function showToast(msg, isError = false) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.innerText = msg;
  toast.style.borderColor = isError ? 'var(--accent-red)' : 'var(--accent-cyan)';
  toast.style.display = 'block';
  setTimeout(() => {
    toast.style.display = 'none';
  }, 3000);
}
