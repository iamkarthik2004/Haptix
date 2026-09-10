const CACHE_NAME = 'haptix-camera-v2';
const APP_SHELL = ['/', '/camera', '/static/styles.css', '/static/pwa.js', '/static/app-icon.svg', '/manifest.webmanifest'];
self.addEventListener('install', (event) => { event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))); self.skipWaiting(); });
self.addEventListener('activate', (event) => { event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))); self.clients.claim(); });
self.addEventListener('fetch', (event) => { const url = new URL(event.request.url); if (url.origin !== self.location.origin || url.pathname === '/analyze' || url.pathname === '/latest') return; event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request))); });
