# Latency Optimization Specification (v1.0.8)

This document outlines the architectural changes made in version 1.0.8 of the PECH NDI WebRTC bridge to achieve ultra-low latency and resolve CPU exhaustion / desynchronization issues in the WebRTC track loops.

## 1. NDI Receiver Format Change (`ndi_core.py`)
- **Previous state**: `NDIReceiver` requested `NDILIB_RECV_COLOR_FORMAT_BGRX_BGRA`.
- **Issue**: Forcing the NDI SDK to decode to BGRA uses significantly more CPU and introduces decoding latency compared to planar or 4:2:2 formats, which are closer to the raw NDI stream.
- **Change**: Changed the default color format in `NDIReceiver` to `NDILIB_RECV_COLOR_FORMAT_FASTEST`. This permits the NDI SDK to yield native UYVY or the most performant uncompressed format available.

## 2. WebRTC Video Track Native UYVY Support (`webrtc_server.py`)
- **Previous state**: The video frame processing in `NDIVideoTrack.recv` only supported BGRA/BGRX properly, or performed an inefficient manual reshape that could crash on UYVY data.
- **Change**: Added explicit handling for `FOURCC_UYVY`. It now passes the uncompressed UYVY byte array directly into PyAV using `av.VideoFrame.from_ndarray(..., format="uyvy422")`. PyAV processes this highly efficiently without costly manual array slicing.

## 3. WebRTC Video Track Polling Loop Fix (`webrtc_server.py`)
- **Previous state**: `NDIVideoTrack.recv` checked if the latest frame was less than 500ms old and, if so, immediately returned it. It did not track whether the frame had already been sent. This caused `aiortc` to rapidly poll `recv()` and transmit identical frames as fast as possible, maxing out CPU and bandwidth.
- **Change**: Introduced `_last_processed_receive_time` state in `NDIVideoTrack`. The `recv()` loop now polls (up to 100ms) for a frame with a timestamp strictly greater than `_last_processed_receive_time`. This ensures WebRTC waits for a genuinely fresh frame, restoring the natural pacing of the NDI source (e.g. 60fps) and drastically lowering CPU overhead.

## 4. WebRTC Audio Track Synchronization (`webrtc_server.py`)
- **Previous state**: `NDIAudioTrack.recv` checked if a 20ms chunk (3840 bytes) was available. If not, it immediately returned a 20ms silence frame. Since `aiortc` transmission pacing is tied to `recv()` yielding frames, immediately returning silence caused rapid desynchronization and CPU spikes.
- **Change**: Added an asynchronous wait loop (`await asyncio.sleep(0.01)`) inside `NDIAudioTrack.recv` to wait up to 100ms for audio data to buffer. 
- **Change**: Replaced wall-clock based PTS (`time.perf_counter()`) with strict monotonic sample-counting for audio PTS. Even if silence is inserted, the monotonic sample counter increments smoothly. This allows `aiortc`'s internal `RTCRtpSender` pacing algorithm to perfectly sync the audio transmission to real-time.

## Summary
These changes convert a "busy-wait" WebRTC bridging system into a properly paced, block-and-yield pipeline, significantly reducing CPU load and delivering stable, sub-100ms latency.
