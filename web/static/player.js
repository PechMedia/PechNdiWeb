/**
 * PECH NDI-to-WebRTC Near-Zero Latency Player Client
 * Automatically connects to local WebRTC signaling endpoint (WHEP / WebSocket)
 */

class NDIWebRTCPlayer {
  constructor(videoElement, options = {}) {
    this.video = videoElement;
    this.options = {
      signalingUrl: options.signalingUrl || (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws',
      whepUrl: options.whepUrl || '/api/whep',
      autoReconnect: options.autoReconnect !== false,
      reconnectInterval: 2500,
      onStatusChange: options.onStatusChange || (() => {}),
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
    this.options.onStatusChange('connecting', 'Negotiating WebRTC stream...');
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

    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('audio', { direction: 'recvonly' });

    pc.ontrack = (evt) => {
      if (this.pc !== pc) return;
      if (this.video.srcObject !== evt.streams[0]) {
        this.video.srcObject = evt.streams[0];
        this.video.play().catch(e => {
          console.log('Autoplay blocked, user gesture needed for audio:', e);
          const banner = document.getElementById('unmuteBanner');
          if (banner) banner.style.display = 'flex';
        });
      }
    };

    pc.onconnectionstatechange = () => {
      if (this.pc !== pc) return;
      const state = pc.connectionState;
      console.log('WebRTC Connection State:', state);
      if (state === 'connected') {
        this.isConnected = true;
        this.options.onStatusChange('live', 'LIVE (Zero Latency)');
        this._startStats();
      } else if (state === 'disconnected' || state === 'failed') {
        this.isConnected = false;
        this.options.onStatusChange('offline', 'Disconnected');
        this._scheduleReconnect();
      }
    };

    const offer = await pc.createOffer({
      offerToReceiveVideo: true,
      offerToReceiveAudio: true,
    });
    await pc.setLocalDescription(offer);

    // Connect WS
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
      if (this.ws !== ws || this.pc !== pc) return;
      try {
        const data = JSON.parse(evt.data);
        if (data.type === 'answer') {
          await pc.setRemoteDescription(new RTCSessionDescription({
            type: 'answer',
            sdp: data.sdp,
          }));
        }
      } catch (e) {
        console.error('Error handling signaling message:', e);
      }
    };

    ws.onerror = (err) => {
      if (this.ws !== ws) return;
      console.error('Signaling WebSocket error:', err);
      this._scheduleReconnect();
    };

    ws.onclose = () => {
      if (this.ws !== ws) return;
      if (this.isConnected) {
        this.isConnected = false;
        this.options.onStatusChange('offline', 'Stream Closed');
        this._scheduleReconnect();
      }
    };
  }

  async _connectWHEP() {
    this._cleanup();
    const pc = new RTCPeerConnection({ iceServers: [] });
    this.pc = pc;

    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('audio', { direction: 'recvonly' });

    pc.ontrack = (evt) => {
      if (this.pc !== pc) return;
      if (this.video.srcObject !== evt.streams[0]) {
        this.video.srcObject = evt.streams[0];
        this.video.play().catch(e => console.log('Autoplay audio interaction needed:', e));
      }
    };

    pc.onconnectionstatechange = () => {
      if (this.pc !== pc) return;
      const state = pc.connectionState;
      if (state === 'connected') {
        this.isConnected = true;
        this.options.onStatusChange('live', 'LIVE (WHEP)');
        this._startStats();
      } else if (state === 'disconnected' || state === 'failed') {
        this.isConnected = false;
        this.options.onStatusChange('offline', 'Disconnected');
        this._scheduleReconnect();
      }
    };

    const offer = await pc.createOffer();
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
        let jitter = 0;

        stats.forEach(report => {
          if (report.type === 'inbound-rtp' && report.kind === 'video') {
            if (report.framesPerSecond) fps = Math.round(report.framesPerSecond);
            if (report.jitter) jitter = Math.round(report.jitter * 1000);
            if (report.bytesReceived) {
              const now = performance.now();
              const bytesDiff = report.bytesReceived - lastBytes;
              const timeDiff = (now - lastTime) / 1000;
              if (lastBytes > 0 && timeDiff > 0) {
                bitrate = Math.round((bytesDiff * 8) / timeDiff / 1000); // kbps
              }
              lastBytes = report.bytesReceived;
              lastTime = now;
            }
          }
        });

        this.options.onStatsUpdate({
          fps: fps || (this.video.videoWidth ? 60 : 0),
          width: width,
          height: height,
          bitrate: bitrate,
          jitter: jitter,
        });
      } catch (e) {
        // Ignore stats polling errors
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
      try {
        oldWs.close();
      } catch (e) {}
    }
    if (this.pc) {
      const oldPc = this.pc;
      this.pc = null;
      oldPc.ontrack = null;
      oldPc.onconnectionstatechange = null;
      try {
        oldPc.close();
      } catch (e) {}
    }
  }

  stop() {
    this._cleanup();
    if (this.video) {
      this.video.srcObject = null;
    }
  }
}
