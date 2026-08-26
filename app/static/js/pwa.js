/* Kin PWA bootstrap
   - Registers the service worker (install/offline).
   - Captures beforeinstallprompt for a gentle, opt-in install affordance.
   - Subscribes to Web Push only when the user has enabled it in Settings, and
     never shows an aggressive permission prompt. Notifications are quiet, opt-in,
     and respect the app's calm design principles. */
(function () {
  const API_BASE = '/api/push';

  /* ---- Service worker registration ---- */
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
  }

  /* ---- Gentle install prompt ---- */
  let deferredInstall = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstall = e;
    const el = document.getElementById('install-app');
    if (el) el.style.display = '';
  });
  window.addEventListener('appinstalled', () => {
    const el = document.getElementById('install-app');
    if (el) el.style.display = 'none';
  });
  window.installKin = function () {
    if (deferredInstall) {
      deferredInstall.prompt();
      deferredInstall.userChoice.then(() => { deferredInstall = null; });
    }
  };

  /* ---- Push subscription (opt-in) ---- */
  const ASYNC = {
    async urlBase64ToUint8Array(base64) {
      const padding = '='.repeat((4 - (base64.length % 4)) % 4);
      const base64str = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
      const raw = atob(base64str);
      const arr = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
      return arr;
    }
  };

  async function getVapidKey() {
    try {
      const resp = await fetch(API_BASE + '/vapid-key', { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      const data = await resp.json();
      return data.public_key;
    } catch (e) { return null; }
  }

  async function requestPermission() {
    if (!('Notification' in window)) return false;
    if (Notification.permission === 'granted') return true;
    if (Notification.permission === 'denied') return false;
    const granted = await Notification.requestPermission();
    return granted === 'granted';
  }

  async function subscribePush() {
    try {
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        return 'Push isn\'t available in this browser/context.';
      }
      if (!('Notification' in window) || Notification.permission !== 'granted') {
        return 'Notifications aren\'t allowed yet.';
      }
      const key = await getVapidKey();
      if (!key) return 'Couldn\'t load the push key.';
      const registration = await navigator.serviceWorker.ready;
      let sub = await registration.pushManager.getSubscription();
      if (!sub) {
        sub = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: await ASYNC.urlBase64ToUint8Array(key)
        });
      }
      const resp = await fetch(API_BASE + '/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify(sub)
      });
      if (!resp.ok) return 'The server rejected the subscription (HTTP ' + resp.status + ').';
      return null; // success
    } catch (e) {
      return 'Subscribe error: ' + (e && e.message ? e.message : e);
    }
  }

  async function disablePush() {
    const registration = await navigator.serviceWorker.ready;
    const sub = await registration.pushManager.getSubscription();
    if (sub) {
      await fetch(API_BASE + '/unsubscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify({ endpoint: sub.endpoint })
      });
      await sub.unsubscribe();
    }
  }

  window.KinPush = {
    requestPermission,
    subscribe: subscribePush,
    disable: disablePush,
    async sendTest() {
      try {
        // Request permission inside this same user gesture (Firefox requires a gesture).
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
          alert('Push notifications aren\'t available here — this needs HTTPS and a modern browser.');
          return;
        }
        if (!('Notification' in window)) {
          alert('This browser doesn\'t support notifications.');
          return;
        }
        if (Notification.permission === 'denied') {
          alert('Notifications are blocked for this site. Allow them via the browser\'s site settings (the padlock/lock icon), then try again.');
          return;
        }
        if (Notification.permission !== 'granted') {
          const perm = await Notification.requestPermission();
          if (perm !== 'granted') {
            alert('Notifications need to be allowed for a test to send. Try again and choose "Allow".');
            return;
          }
        }
        const err = await subscribePush();
        if (err) {
          alert(err);
          return;
        }
        const resp = await fetch(API_BASE + '/test', { method: 'POST', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const data = await resp.json();
        if (resp.ok) { alert('Test notification sent! Check your device.'); }
        else { alert(data.error || 'Test failed.'); }
      } catch (e) {
        alert('Could not send a test notification right now: ' + (e && e.message ? e.message : e));
      }
    }
  };

  // Wire the Settings "enable notifications" checkbox to request permission only.
  // The actual push subscription happens when the user clicks "Send test notification"
  // because Firefox requires subscribe() to be called during a direct user gesture.
  document.addEventListener('DOMContentLoaded', () => {
    const box = document.getElementById('push-enabled-check');
    if (!box) return;
    box.addEventListener('change', async () => {
      if (box.checked) {
        const perm = await requestPermission();
        if (!perm) {
          box.checked = false;
          alert('Notifications couldn\'t be enabled on this device (permission denied or unsupported).');
        }
      } else {
        await disablePush();
      }
    });
  });

  // Listen for the service worker telling an open, focused window to show a gentle in-app toast
  // instead of a browser push notification (smart behavior: no double-notifying when open).
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('message', (event) => {
      if (event.data && event.data.kind === 'kin-toast') {
        showToast(event.data);
      }
    });
  }

  function showToast(data) {
    let toast = document.getElementById('kin-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'kin-toast';
      toast.className = 'kin-toast';
      document.body.appendChild(toast);
    }
    toast.textContent = data.body || 'Kin';
    toast.classList.add('show');
    clearTimeout(window.__kinToastTimer);
    window.__kinToastTimer = setTimeout(() => toast.classList.remove('show'), 6000);
    toast.onclick = () => { if (data.url) location.href = data.url; };
  }
})();
