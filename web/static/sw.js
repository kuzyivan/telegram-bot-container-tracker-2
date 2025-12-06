const CACHE_NAME = 'logistrail-v1';

// Когда приложение устанавливается
self.addEventListener('install', (event) => {
    // Просто говорим браузеру, что SW установлен
    self.skipWaiting();
});

// Когда приложение делает запрос (за картинкой, стилем или страницей)
self.addEventListener('fetch', (event) => {
    event.respondWith(
        // 1. Сначала пробуем пойти в интернет за свежими данными
        fetch(event.request).catch(() => {
            // 2. Если интернета нет, пытаемся найти в кэше (если там что-то есть)
            return caches.match(event.request);
        })
    );
});