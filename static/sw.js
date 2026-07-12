const CACHE_NAME = 'ugvcl-portal-v2';
const STATIC_CACHE = 'ugvcl-static-v2';

// Core app shell assets to pre-cache
const PRECACHE_ASSETS = [
  '/',
  '/static/manifest.json',
  '/static/css/custom.css',
  '/static/dist/img/icon-192.png',
  '/static/dist/img/icon-512.png',
  '/offline'
];

// CDN assets to cache on first use
const CDN_HOSTS = [
  'cdn.jsdelivr.net',
  'cdnjs.cloudflare.com',
  'fonts.googleapis.com',
  'fonts.gstatic.com',
  'code.jquery.com'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(PRECACHE_ASSETS).catch(err => {
        console.log('SW precache error (non-fatal):', err);
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME && key !== STATIC_CACHE) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  // Strategy 1: Cache-First for static assets and CDN resources
  if (isStaticAsset(url) || isCDNAsset(url)) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((response) => {
          if (response.status === 200) {
            const resClone = response.clone();
            caches.open(STATIC_CACHE).then((cache) => {
              cache.put(event.request, resClone);
            });
          }
          return response;
        }).catch(() => caches.match(event.request));
      })
    );
    return;
  }

  // Strategy 2: Network-First for HTML pages and API calls
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.status === 200 && event.request.headers.get('accept')?.includes('text/html')) {
          const resClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, resClone);
          });
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then((cached) => {
          if (cached) return cached;
          // If it's a navigation request, show offline page
          if (event.request.mode === 'navigate') {
            return caches.match('/offline');
          }
        });
      })
  );
});

function isStaticAsset(url) {
  return url.pathname.startsWith('/static/') ||
         /\.(css|js|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$/i.test(url.pathname);
}

function isCDNAsset(url) {
  return CDN_HOSTS.some(host => url.hostname.includes(host));
}
