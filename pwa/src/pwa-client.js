/*
 * PWA client script. Injected into the portal's index.html by the build, so the portal code itself is untouched.
 * It registers the service worker, offers to install the app, and offers a reload when a new version is ready.
 */
(function () {
  'use strict';

  var waiting = null;
  var installEvent = null;
  var card = null;

  function removeCard() {
    if (card && card.parentNode) card.parentNode.removeChild(card);
    card = null;
  }

  function showCard(message, actionLabel, onAction) {
    removeCard();
    card = document.createElement('div');
    card.setAttribute('role', 'status');
    card.setAttribute('aria-live', 'polite');
    card.style.cssText = [
      'position:fixed', 'right:16px', 'bottom:16px', 'z-index:2147483000', 'display:flex', 'align-items:center',
      'gap:12px', 'max-width:360px', 'padding:12px 14px', 'border-radius:10px', 'border:1px solid #32363e',
      'background:#131417', 'color:#ededef', 'font:13px/1.4 Inter,system-ui,sans-serif', 'box-shadow:0 8px 24px rgba(0,0,0,.4)',
    ].join(';');

    var text = document.createElement('span');
    text.textContent = message;

    var action = document.createElement('button');
    action.type = 'button';
    action.textContent = actionLabel;
    action.style.cssText = 'cursor:pointer;border:0;border-radius:6px;padding:6px 12px;font:500 12px Inter,system-ui,sans-serif;background:#f2f2f4;color:#0c0d0f';
    action.addEventListener('click', onAction);

    var close = document.createElement('button');
    close.type = 'button';
    close.setAttribute('aria-label', 'Dismiss');
    close.textContent = '×';
    close.style.cssText = 'cursor:pointer;border:0;background:transparent;color:#a0a4ad;font-size:18px;line-height:1;padding:0 2px';
    close.addEventListener('click', removeCard);

    card.appendChild(text);
    card.appendChild(action);
    card.appendChild(close);
    document.body.appendChild(card);
  }

  function offerUpdate(worker) {
    // A controller exists only on a later visit, so a first install is not reported as an update.
    if (!worker || !navigator.serviceWorker.controller) return;
    waiting = worker;
    showCard('A new version of Sceptic is ready.', 'Reload', function () {
      waiting.postMessage({ type: 'SKIP_WAITING' });
    });
  }

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').then(function (registration) {
        offerUpdate(registration.waiting);
        registration.addEventListener('updatefound', function () {
          var incoming = registration.installing;
          if (!incoming) return;
          incoming.addEventListener('statechange', function () {
            if (incoming.state === 'installed') offerUpdate(incoming);
          });
        });
      }).catch(function () {
        // The portal works without a service worker, so a registration failure is not shown to the user.
      });

      var reloading = false;
      navigator.serviceWorker.addEventListener('controllerchange', function () {
        if (reloading) return;
        reloading = true;
        window.location.reload();
      });
    });
  }

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    installEvent = event;
    showCard('Install Sceptic as an app.', 'Install', function () {
      installEvent.prompt();
      installEvent.userChoice.then(function () {
        installEvent = null;
        removeCard();
      });
    });
  });

  window.addEventListener('appinstalled', function () {
    installEvent = null;
    removeCard();
  });
})();
