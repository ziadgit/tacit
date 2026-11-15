// tacit service worker. The shell is cache-first; /api/* is network-only and never cached.
const CACHE = 'tacit-shell-v13'; // bump on every release, or phones keep the old shell
const SHELL = [
  '/app/',
  '/app/index.html',
  '/app/app.js',
  '/app/api.js',
  '/app/style.css',
  '/app/vendor/bundle.css',
  '/app/vendor/bundle.js',
  '/app/vendor/face.js',
  '/app/icons/icon.svg',
  '/app/icons/icon-192.png',
  '/app/icons/icon-512.png',
  '/app/icons/maskable-512.png',
  '/app/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  // cache: 'reload' skips the browser's HTTP cache, so a new release caches the new files
  event.waitUntil(caches.open(CACHE)
    .then((c) => c.addAll(SHELL.map((url) => new Request(url, { cache: 'reload' }))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isApi(url) {
  return url.origin === self.location.origin && url.pathname.startsWith('/api/');
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || isApi(url) || url.origin !== self.location.origin) {
    return; // network only: the browser handles it, nothing is stored
  }
  if (req.mode === 'navigate') {
    event.respondWith(fetch(req).catch(() => caches.match('/app/index.html')));
    return;
  }
  if (!url.pathname.startsWith('/app/')) return;
  event.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
});
