/* Kin service worker
   - Precache the app shell (static assets) so the app opens fast and works offline.
   - Network-first for HTML pages so personal data is always fresh (never stale from cache).
   - Offline fallback to a calm "you're offline" page instead of a hard error.
   - Web Push event handling: show a gentle notification when the app is closed/background.
   The user is ALWAYS in control: notifications are opt-in and never intrusive. */
const CACHE = 'kin-shell-v16';
const SHELL = [
  '/static/css/style.css',
  '/static/js/htmx.min.js',
  '/static/js/alpine.min.js',
  '/static/fonts/atkinson-400.woff2',
  '/static/fonts/atkinson-700.woff2',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/favicon.ico',
  '/static/offline.html',
  '/manifest.webmanifest'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  // Only handle same-origin GET requests.
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  // Cache-first for static assets (bundled files, never personal data).
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return resp;
      }).catch(() => caches.match('/static/offline.html')))
    );
    return;
  }
  // Network-first for HTML pages (fresh personal data, offline fallback as a safety net).
  event.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp.ok && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return resp;
      })
      .catch(() => caches.match(req).then((cached) => cached || caches.match('/static/offline.html')))
  );
});

/* ---- Push notifications ---- */
self.addEventListener('push', (event) => {
  if (!self.registration) return;
  let data = { title: 'Kin', body: '', icon: '/static/icons/icon-192.png', tag: '', url: '/' };
  try {
    if (event.data) data = Object.assign({}, data, event.data.json());
  } catch (e) { /* fall back to defaults */ }

  // Smart behavior: if the app is open in a focused window, don't pop a push notification
  // (the page surfaces a quiet in-app toast instead). Only push when the app is closed or in the background.
  const showIfFocused = () =>
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      const focused = windows.some((w) => w.focused);
      if (focused) {
        // Tell open window(s) to render an in-app toast instead of a browser notification.
        windows.forEach((w) => w.postMessage({ kind: 'kin-toast', ...data }));
        return;
      }
      return self.registration.showNotification(data.title, {
        body: data.body,
        icon: data.icon,
        tag: data.tag,
        data: { url: data.url }
      });
    });

  event.waitUntil(showIfFocused());
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if ('focus' in client) { client.postMessage({ kind: 'kin-focus', url: target }); return client.focus(); }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    })
  );
});
