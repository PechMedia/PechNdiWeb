/**
 * PECH NDI-to-WebRTC Near-Zero Latency Player Client
 * Optimized for Kiosk Android Tablets:
 * - Strictly video-only (no audio transceiver / muted) for zero-click mobile autoplay
 * - Real-time state listener via WebSocket (/ws) with automatic WHEP fallback
 * - Resilient auto-reconnect logic
 */

class NDIWebRTCPlayer {
  constructor(videoElement, options = {}) {
    this.video = videoElement;
    this.options = {
      signalingUrl: options.signalingUrl || (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws',
      whepUrl: options.whepUrl || '/api/whep',
      autoReconnect: options.autoReconnect !== false,
      reconnectInterval: 2000,
      onStatusChange: options.onStatusChange || (() => {}),
      onStateUpdate: options.onStateUpdate || (() => {}),
      onStatsUpdate: options.onStatsUpdate || (() => {}),
    };

    this.pc = null;
    this.ws = null;
    this.statsInterval = null;
    this.reconnectTimer = null;
    this.isConnected = false;
    this.isReconnecting = false;
  }

  async start() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.isReconnecting = false;
    this.options.onStatusChange('connecting', 'Waiting for Slides...');
    try {
      await this._connectWebSocket();
    } catch (e) {
      console.warn('WebSocket signaling failed, falling back to WHEP HTTP...', e);
      await this._connectWHEP();
    }
  }

  async _connectWebSocket() {
    this._cleanup();
    const pc = new RTCPeerConnection({
      iceServers: [],
      bundlePolicy: 'max-bundle',
    });
    this.pc = pc;

    // Strictly video-only to guarantee zero-interaction autoplay on Android tablets
    pc.addTransceiver('video', { direction: 'recvonly' });

    pc.ontrack = (evt) => {
      if (this.pc !== pc) return;
      if (evt.track && evt.track.kind === 'video' && 'playoutDelayHint' in evt.receiver) {
        try { evt.receiver.playoutDelayHint = 0; } catch (e) {}
      }
      if (this.video.srcObject !== evt.streams[0]) {
        this.video.srcObject = evt.streams[0];
        this.video.muted = true;
        this.video.playsInline = true;
        this.video.play().catch(e => console.log('Autoplay error:', e));
      }
    };

    pc.onconnectionstatechange = () => {
      if (this.pc !== pc) return;
      const state = pc.connectionState;
      if (state === 'connected') {
        this.isConnected = true;
        this.options.onStatusChange('live', 'LIVE');
        this._startStats();
      } else if (state === 'disconnected' || state === 'failed') {
        this.isConnected = false;
        this.options.onStatusChange('offline', 'Waiting for Slides...');
        this._scheduleReconnect();
      }
    };

    const offer = await pc.createOffer({
      offerToReceiveVideo: true,
      offerToReceiveAudio: false,
    });
    await pc.setLocalDescription(offer);

    const ws = new WebSocket(this.options.signalingUrl);
    this.ws = ws;

    ws.onopen = () => {
      if (this.ws !== ws) return;
      ws.send(JSON.stringify({
        type: 'offer',
        sdp: pc.localDescription.sdp,
      }));
    };

    ws.onmessage = async (evt) => {
      if (this.ws !== ws) return;
      try {
        const data = JSON.parse(evt.data);
        if (data.type === 'answer' && this.pc === pc) {
          await pc.setRemoteDescription(new RTCSessionDescription({
            type: 'answer',
            sdp: data.sdp,
          }));
        } else if (data.type === 'status') {
          // Stream state update (pause / resume / message)
          this.options.onStateUpdate(data);
        }
      } catch (e) {
        console.error('Error handling signaling message:', e);
      }
    };

    ws.onerror = () => {
      if (this.ws !== ws) return;
      this._scheduleReconnect();
    };

    ws.onclose = () => {
      if (this.ws !== ws) return;
      if (this.isConnected) {
        this.isConnected = false;
        this.options.onStatusChange('offline', 'Waiting for Slides...');
        this._scheduleReconnect();
      }
    };
  }

  async _connectWHEP() {
    this._cleanup();
    const pc = new RTCPeerConnection({ iceServers: [] });
    this.pc = pc;

    // Strictly video-only
    pc.addTransceiver('video', { direction: 'recvonly' });

    pc.ontrack = (evt) => {
      if (this.pc !== pc) return;
      if (evt.track && evt.track.kind === 'video' && 'playoutDelayHint' in evt.receiver) {
        try { evt.receiver.playoutDelayHint = 0; } catch (e) {}
      }
      if (this.video.srcObject !== evt.streams[0]) {
        this.video.srcObject = evt.streams[0];
        this.video.muted = true;
        this.video.playsInline = true;
        this.video.play().catch(e => console.log('WHEP Autoplay:', e));
      }
    };

    pc.onconnectionstatechange = () => {
      if (this.pc !== pc) return;
      const state = pc.connectionState;
      if (state === 'connected') {
        this.isConnected = true;
        this.options.onStatusChange('live', 'LIVE');
        this._startStats();
      } else if (state === 'disconnected' || state === 'failed') {
        this.isConnected = false;
        this.options.onStatusChange('offline', 'Waiting for Slides...');
        this._scheduleReconnect();
      }
    };

    const offer = await pc.createOffer({
      offerToReceiveVideo: true,
      offerToReceiveAudio: false,
    });
    await pc.setLocalDescription(offer);

    const res = await fetch(this.options.whepUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/sdp' },
      body: pc.localDescription.sdp,
    });

    if (!res.ok) throw new Error('WHEP offer failed: ' + res.statusText);

    const answerSdp = await res.text();
    await pc.setRemoteDescription(new RTCSessionDescription({
      type: 'answer',
      sdp: answerSdp,
    }));
  }

  _startStats() {
    if (this.statsInterval) clearInterval(this.statsInterval);
    let lastBytes = 0;
    let lastTime = performance.now();

    this.statsInterval = setInterval(async () => {
      if (!this.pc) return;
      try {
        const stats = await this.pc.getStats();
        let fps = 0;
        let width = this.video.videoWidth || 0;
        let height = this.video.videoHeight || 0;
        let bitrate = 0;

        stats.forEach(report => {
          if (report.type === 'inbound-rtp' && report.kind === 'video') {
            if (report.framesPerSecond) fps = Math.round(report.framesPerSecond);
            if (report.bytesReceived) {
              const now = performance.now();
              const bytesDiff = report.bytesReceived - lastBytes;
              const timeDiff = (now - lastTime) / 1000;
              if (lastBytes > 0 && timeDiff > 0) {
                bitrate = Math.round((bytesDiff * 8) / timeDiff / 1000);
              }
              lastBytes = report.bytesReceived;
              lastTime = now;
            }
          }
        });

        this.options.onStatsUpdate({
          fps: fps,
          width: width,
          height: height,
          bitrate: bitrate,
        });
      } catch (e) {
        // Ignore stats errors
      }
    }, 1000);
  }

  _scheduleReconnect() {
    if (!this.options.autoReconnect || this.isReconnecting) return;
    this.isReconnecting = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = setTimeout(() => {
      this.isReconnecting = false;
      this.reconnectTimer = null;
      this.start();
    }, this.options.reconnectInterval);
  }

  _cleanup() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.isReconnecting = false;
    this.isConnected = false;

    if (this.statsInterval) {
      clearInterval(this.statsInterval);
      this.statsInterval = null;
    }
    if (this.ws) {
      const oldWs = this.ws;
      this.ws = null;
      oldWs.onopen = null;
      oldWs.onmessage = null;
      oldWs.onerror = null;
      oldWs.onclose = null;
      try { oldWs.close(); } catch (e) {}
    }
    if (this.pc) {
      const oldPc = this.pc;
      this.pc = null;
      oldPc.ontrack = null;
      oldPc.onconnectionstatechange = null;
      try { oldPc.close(); } catch (e) {}
    }
  }

  stop() {
    this._cleanup();
    if (this.video) {
      this.video.srcObject = null;
    }
  }
}
