self.addEventListener('push', function(event) {
  if (event.data) {
    let payload = {};
    try {
      payload = event.data.json();
    } catch (e) {
      payload = {
        title: 'Stilo',
        body: event.data.text()
      };
    }

    const title = payload.title || 'Stilo';
    const options = {
      body: payload.body || '',
      icon: payload.icon || '/static/img/default.jpg',
      badge: payload.badge || '/static/img/default.jpg',
      data: {
        url: payload.url || '/my-appointments/'
      }
    };

    event.waitUntil(
      self.registration.showNotification(title, options)
    );
  }
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  // Al hacer clic, redirigir a la URL correspondiente
  const urlToOpen = new URL(event.notification.data && event.notification.data.url ? event.notification.data.url : '/my-appointments/', self.location.origin).href;
  
  event.waitUntil(
    clients.matchAll({
      type: 'window',
      includeUncontrolled: true
    }).then(function(windowClients) {
      // Si la pestaña ya está abierta, hacerle foco
      for (var i = 0; i < windowClients.length; i++) {
        var client = windowClients[i];
        if (client.url === urlToOpen && 'focus' in client) {
          return client.focus();
        }
      }
      // Si no, abrir una nueva pestaña
      if (clients.openWindow) {
        return clients.openWindow(urlToOpen);
      }
    })
  );
});
