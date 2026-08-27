const APP_VERSION = '1.0.10';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
  // Direct pass-through for WebRTC signaling and real-time media
  event.respondWith(fetch(event.request));
});
