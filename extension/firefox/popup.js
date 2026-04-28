// popup.js — drives popup.html

const API_BASE = 'http://127.0.0.1:5000';

// ─── Helpers ─────────────────────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function setApiStatus(ok) {
  const el   = $('api-status');
  const dot  = el.querySelector('.status-dot');
  const text = $('api-status-text');
  el.className   = `${ok ? 'ok' : 'error'}`;
  dot.className  = `status-dot ${ok ? 'ok' : 'error'}`;
  text.textContent = ok
    ? '✓ AI backend connected — model ready'
    : '✗ Backend offline — start api_server.py';
}

function renderCurrentUrl(url, result) {
  $('current-url').textContent = url || '—';
  const badge = $('current-badge');

  if (!result) {
    badge.textContent = 'Unknown';
    badge.className   = 'result-badge unknown';
    return;
  }

  const isPh = result.label === 'phishing';
  badge.textContent = isPh ? '⚠ PHISHING' : '✓ Safe';
  badge.className   = `result-badge ${isPh ? 'phishing' : 'legitimate'}`;

  $('conf-wrap').style.display = 'block';
  $('conf-label').textContent  = `AI Confidence: ${result.confidence.toFixed(1)}%`;
  const fill = $('conf-fill');
  fill.style.width  = `${result.confidence}%`;
  fill.className    = `conf-bar-fill ${isPh ? 'phishing' : 'legitimate'}`;
}

function renderLinksList(results) {
  const container = $('links-list');
  const phishing  = results.filter(r => r.label === 'phishing');
  const rest      = results.filter(r => r.label !== 'phishing');
  const sorted    = [...phishing, ...rest];

  $('link-count').textContent = `(${results.length} found, ${phishing.length} flagged)`;

  if (!results.length) {
    container.innerHTML = '<div class="empty-state">No links found on this page.</div>';
    return;
  }

  container.innerHTML = sorted.map(r => {
    const isPh = r.label === 'phishing';
    const badgeClass = isPh ? 'phishing' : 'legitimate';
    const badgeText  = isPh ? `⚠ ${r.confidence.toFixed(0)}%` : '✓ Safe';
    const shortUrl   = r.url.replace(/^https?:\/\//, '').slice(0, 55);
    return `
      <div class="link-item">
        <div class="link-item-url" title="${escHtml(r.url)}">${escHtml(shortUrl)}</div>
        <div class="link-item-badge ${badgeClass}">${badgeText}</div>
      </div>
    `;
  }).join('');
}

function escHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── API calls ────────────────────────────────────────────────────────────────
async function pingApi() {
  try {
    const r = await fetch(`${API_BASE}/ping`, { signal: AbortSignal.timeout(3000) });
    const d = await r.json();
    setApiStatus(d.status === 'ok');
    return d.status === 'ok';
  } catch (_) {
    setApiStatus(false);
    return false;
  }
}

async function scanUrl(url) {
  const r = await fetch(`${API_BASE}/predict`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ urls: [url] }),
    signal:  AbortSignal.timeout(8000)
  });
  const d = await r.json();
  return d.results?.[0] || null;
}

async function scanUrls(urls) {
  const r = await fetch(`${API_BASE}/predict`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ urls }),
    signal:  AbortSignal.timeout(15000)
  });
  const d = await r.json();
  return d.results || [];
}

// ─── Main init ────────────────────────────────────────────────────────────────
async function init() {
  // 1. Ping API
  const apiOk = await pingApi();

  // 2. Get current tab info
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url) return;

  $('current-url').textContent = tab.url.replace(/^https?:\/\//, '').slice(0, 60);

  if (apiOk) {
    // Scan current tab URL
    try {
      const result = await scanUrl(tab.url);
      renderCurrentUrl(tab.url, result);
    } catch (_) {
      renderCurrentUrl(tab.url, null);
    }

    // Ask content script for page links
    chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_LINKS' }, async resp => {
      if (chrome.runtime.lastError || !resp?.links) {
        $('links-list').innerHTML = '<div class="empty-state">Cannot access this page.</div>';
        return;
      }

      const links = resp.links.slice(0, 60); // limit to 60 for speed
      if (!links.length) {
        $('links-list').innerHTML = '<div class="empty-state">No external links found.</div>';
        $('link-count').textContent = '(0 found)';
        return;
      }

      $('links-list').innerHTML = '<div class="empty-state">Scanning links…</div>';
      $('link-count').textContent = `(scanning ${links.length}…)`;

      try {
        const results = await scanUrls(links);
        renderLinksList(results);
      } catch (_) {
        $('links-list').innerHTML = '<div class="empty-state">Scan failed. Check backend.</div>';
      }
    });
  }
}

// ─── Manual scan ─────────────────────────────────────────────────────────────
$('btn-scan').addEventListener('click', async () => {
  const input = $('manual-url').value.trim();
  if (!input) return;

  const url = input.startsWith('http') ? input : 'https://' + input;
  const res = $('manual-result');
  res.style.display = 'block';
  res.className = 'error';
  res.textContent = 'Scanning…';

  try {
    const result = await scanUrl(url);
    if (!result) throw new Error('No result');
    const isPh = result.label === 'phishing';
    res.className  = isPh ? 'phishing' : 'legitimate';
    res.innerHTML  = isPh
      ? `⚠️ <strong>PHISHING</strong> — Confidence: ${result.confidence.toFixed(1)}%`
      : `✅ <strong>Legitimate</strong> — Confidence: ${result.confidence.toFixed(1)}%`;
  } catch (e) {
    res.className  = 'error';
    res.textContent = '⚠ Backend unreachable. Is api_server.py running?';
  }
});

$('manual-url').addEventListener('keydown', e => {
  if (e.key === 'Enter') $('btn-scan').click();
});

// ─── Re-scan page links ───────────────────────────────────────────────────────
$('btn-scan-page').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_LINKS' }, async resp => {
    if (!resp?.links?.length) return;
    const results = await scanUrls(resp.links.slice(0, 60));
    renderLinksList(results);
  });
});

// ─── Content script message handler addition ──────────────────────────────────
// Extend content.js to respond to GET_PAGE_LINKS
// (handled via chrome.tabs.sendMessage in init above)

init();
