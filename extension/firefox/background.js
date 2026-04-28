// ═══════════════════════════════════════════════════════════════════════════════
//  background.js  —  Service Worker (Manifest V3)
//  Handles: tab URL scanning, address-bar detection, communication with API
// ═══════════════════════════════════════════════════════════════════════════════

const API_BASE    = 'http://127.0.0.1:5000';
const CACHE_TTL   = 10 * 60 * 1000; // 10 minutes
const cache       = new Map();       // url → {result, ts}

// ─── Utility ──────────────────────────────────────────────────────────────────

function getCached(url) {
  const hit = cache.get(url);
  if (hit && Date.now() - hit.ts < CACHE_TTL) return hit.result;
  return null;
}
function setCache(url, result) {
  cache.set(url, { result, ts: Date.now() });
}

async function classifyUrls(urls) {
  const unique     = [...new Set(urls)];
  const toFetch    = unique.filter(u => !getCached(u));
  const cached     = unique.filter(u => getCached(u)).map(u => getCached(u));

  let fresh = [];
  if (toFetch.length > 0) {
    try {
      const resp = await fetch(`${API_BASE}/predict`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ urls: toFetch }),
        signal:  AbortSignal.timeout(8000)
      });
      const data = await resp.json();
      fresh = data.results || [];
      fresh.forEach(r => setCache(r.url, r));
    } catch (e) {
      console.warn('[Silent Guard] API error:', e.message);
    }
  }

  return [...cached, ...fresh];
}

// ─── Address-bar / navigation scanning ───────────────────────────────────────

async function scanTabUrl(tab) {
  if (!tab?.url || !tab.url.startsWith('http')) return;

  const results = await classifyUrls([tab.url]);
  if (!results.length) return;
  const r = results[0];
  if (!r || r.label === 'legitimate') return;

  // Store for popup
  await chrome.storage.session.set({ [`tab_${tab.id}`]: r });

  // Update badge
  chrome.action.setBadgeText({ text: '⚠', tabId: tab.id });
  chrome.action.setBadgeBackgroundColor({ color: '#FF3B30', tabId: tab.id });

  // Push desktop notification
  chrome.notifications.create(`nav_${tab.id}_${Date.now()}`, {
    type:    'basic',
    iconUrl: 'icons/icon48.png',
    title:   '⚠️ Silent Guard — Phishing URL Detected!',
    message: `The address bar URL was flagged as PHISHING.\n${tab.url.slice(0, 80)}\nConfidence: ${r.confidence}%`,
    priority: 2
  });

  // Inject in-page alert banner
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func:   injectAddressBarBanner,
      args:   [r]
    });
  } catch (_) { /* tab might not be injectable */ }
}

function injectAddressBarBanner(result) {
  // defined in content.js via window.__homogardBanner
  if (typeof window.__silentguardBanner === 'function') {
    window.__silentguardBanner(result, 'addressbar');
  }
}

// ─── Tab events ───────────────────────────────────────────────────────────────

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;
  // Clear old badge
  chrome.action.setBadgeText({ text: '', tabId });
  await scanTabUrl(tab);
});

chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) await scanTabUrl(tab);
});

// ─── Message from content.js ──────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'SCAN_URLS') {
    classifyUrls(msg.urls).then(results => {
      const phishing = results.filter(r => r.label === 'phishing');
      // Update badge
      if (phishing.length > 0) {
        chrome.action.setBadgeText({ text: String(phishing.length), tabId: sender.tab.id });
        chrome.action.setBadgeBackgroundColor({ color: '#FF3B30', tabId: sender.tab.id });
      } else {
        chrome.action.setBadgeText({ text: '✓', tabId: sender.tab.id });
        chrome.action.setBadgeBackgroundColor({ color: '#34C759', tabId: sender.tab.id });
      }
      sendResponse({ results });
    });
    return true; // async
  }

  if (msg.type === 'GET_TAB_RESULT') {
    chrome.storage.session.get([`tab_${sender.tab.id}`]).then(data => {
      sendResponse(data[`tab_${sender.tab.id}`] || null);
    });
    return true;
  }

  if (msg.type === 'API_PING') {
    fetch(`${API_BASE}/ping`, { signal: AbortSignal.timeout(3000) })
      .then(r => r.json())
      .then(d => sendResponse({ ok: true, ...d }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
});
