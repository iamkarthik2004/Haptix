let installPrompt;
const pwaKind = window.HAPTIX_PWA_KIND || 'camera';
const serviceWorkerUrl = pwaKind === 'haptic' ? '/haptic-service-worker.js' : '/service-worker.js';
const recommendation = document.getElementById('install-recommendation');
const installBtn = document.getElementById('install-btn');
const dismissBtn = document.getElementById('dismiss-install');
const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
const isAndroidPhone = /Android/i.test(navigator.userAgent) && /Mobile/i.test(navigator.userAgent);

function showRecommendation() {
  if (!recommendation || isStandalone || localStorage.getItem('haptix-install-dismissed')) return;
  recommendation.classList.remove('is-hidden');
}

function hideRecommendation() {
  recommendation?.classList.add('is-hidden');
}

window.addEventListener('beforeinstallprompt', (event) => {
  if (!isAndroidPhone) return;
  event.preventDefault();
  installPrompt = event;
  showRecommendation();
});

window.addEventListener('appinstalled', () => {
  installPrompt = undefined;
  hideRecommendation();
});

installBtn?.addEventListener('click', async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  const result = await installPrompt.userChoice;
  installPrompt = undefined;
  if (result.outcome === 'accepted') hideRecommendation();
});

dismissBtn?.addEventListener('click', () => {
  localStorage.setItem('haptix-install-dismissed', '1');
  hideRecommendation();
});

if ('serviceWorker' in navigator) {
  window.addEventListener('load', async () => {
    if (isAndroidPhone) {
      await navigator.serviceWorker.register(serviceWorkerUrl);
      return;
    }
    const registrations = await navigator.serviceWorker.getRegistrations();
    await Promise.all(registrations.map((registration) => registration.unregister()));
  });
}
