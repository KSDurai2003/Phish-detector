// ═══════════════════════════════════════════════════════════════════════════════
//  content.js  —  Injected into every page
//  • Scans all <a href> links on the page
//  • Watches dynamically added links (MutationObserver)
//  • Provides in-page alert banner API used by background.js
// ═══════════════════════════════════════════════════════════════════════════════

(function () {
  'use strict';

  if (window.__silentguardInjected) return;
  window.__silentguardInjected = true;

  // ─── Styles ─────────────────────────────────────────────────────────────────
  const STYLE = `
  #silentguard-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.55);
    z-index: 2147483646;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    animation: hg-fade-in 0.25s ease;
  }
  @keyframes hg-fade-in {
    from { opacity: 0; } to { opacity: 1; }
  }
  #silentguard-card {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
    border: 1.5px solid rgba(255, 59, 48, 0.7);
    border-radius: 18px;
    padding: 36px 40px 28px;
    max-width: 520px;
    width: calc(100% - 40px);
    box-shadow: 0 0 60px rgba(255,59,48,0.3), 0 20px 60px rgba(0,0,0,0.7);
    text-align: center;
    animation: hg-scale-in 0.3s cubic-bezier(.17,.67,.35,1.3);
  }
  @keyframes hg-scale-in {
    from { transform: scale(0.85); opacity: 0; }
    to   { transform: scale(1);    opacity: 1; }
  }
  #silentguard-card .hg-icon { font-size: 64px; margin-bottom: 12px; line-height: 1; }
  #silentguard-card h2 {
    color: #FF3B30;
    font-size: 22px;
    font-weight: 700;
    margin: 0 0 6px;
    letter-spacing: -0.3px;
  }
  #silentguard-card .hg-sub {
    color: #a0aec0;
    font-size: 13px;
    margin-bottom: 20px;
  }
  #silentguard-card .hg-url-box {
    background: rgba(255,59,48,0.12);
    border: 1px solid rgba(255,59,48,0.3);
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 12px;
    color: #ff8a80;
    word-break: break-all;
    text-align: left;
    margin-bottom: 18px;
    font-family: 'Courier New', monospace;
  }
  #silentguard-card .hg-conf {
    color: #ffd666;
    font-size: 14px;
    margin-bottom: 24px;
    font-weight: 600;
  }
  #silentguard-card .hg-buttons {
    display: flex;
    gap: 12px;
    justify-content: center;
    flex-wrap: wrap;
  }
  #silentguard-card button {
    border: none;
    border-radius: 10px;
    padding: 12px 28px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.15s, box-shadow 0.15s;
  }
  #silentguard-card button:hover { transform: translateY(-1px); box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
  #hg-btn-back  { background: #FF3B30; color: #fff; }
  #hg-btn-proceed { background: rgba(255,255,255,0.1); color: #a0aec0; }

  /* ── Link highlight badges ── */
  .hg-link-badge {
    display: inline-block;
    font-size: 10px;
    font-weight: 700;
    padding: 1px 5px;
    border-radius: 4px;
    margin-left: 4px;
    vertical-align: middle;
    cursor: default;
    white-space: nowrap;
  }
  .hg-link-badge.phishing {
    background: #FF3B30;
    color: #fff;
  }
  .hg-link-badge.scanning {
    background: #FF9500;
    color: #fff;
    animation: hg-pulse 1s infinite;
  }
  @keyframes hg-pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }

  /* ── Toast notification ── */
  #silentguard-toast-container {
    position: fixed;
    bottom: 24px;
    right: 24px;
    z-index: 2147483645;
    display: flex;
    flex-direction: column;
    gap: 10px;
    pointer-events: none;
  }
  .hg-toast {
    background: linear-gradient(135deg,#1a1a2e,#16213e);
    border: 1.5px solid rgba(255,59,48,0.6);
    border-radius: 12px;
    padding: 14px 18px;
    color: #fff;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 13px;
    max-width: 340px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    animation: hg-slide-in 0.3s ease;
    pointer-events: auto;
  }
  @keyframes hg-slide-in {
    from { transform: translateX(120%); opacity: 0; }
    to   { transform: translateX(0);    opacity: 1; }
  }
  .hg-toast .hg-toast-title { font-weight: 700; color: #FF3B30; margin-bottom: 4px; }
  .hg-toast .hg-toast-url   { font-size: 11px; color: #a0aec0; word-break: break-all; font-family: monospace; }
  .hg-toast .hg-toast-conf  { font-size: 12px; color: #ffd666; margin-top: 4px; }
  `;

  function injectStyle() {
    if (document.getElementById('silentguard-style')) return;
    const s = document.createElement('style');
    s.id = 'silentguard-style';
    s.textContent = STYLE;
    document.head.appendChild(s);
  }

  // ─── Toast container ────────────────────────────────────────────────────────
  function getToastContainer() {
    let c = document.getElementById('silentguard-toast-container');
    if (!c) {
      c = document.createElement('div');
      c.id = 'silentguard-toast-container';
      document.body.appendChild(c);
    }
    return c;
  }

  function showToast(result) {
    injectStyle();
    const container = getToastContainer();
    const toast = document.createElement('div');
    toast.className = 'hg-toast';
    toast.innerHTML = `
      <div class="hg-toast-title">⚠️ Phishing URL Detected!</div>
      <div class="hg-toast-url">${escHtml(result.url)}</div>
      <div class="hg-toast-conf">Confidence: ${result.confidence.toFixed(1)}%</div>
    `;
    container.appendChild(toast);
    setTimeout(() => {
      toast.style.animation = 'none';
      toast.style.opacity   = '0';
      toast.style.transition = 'opacity 0.4s';
      setTimeout(() => toast.remove(), 400);
    }, 6000);
  }

  // ─── Full-page overlay (address-bar threat) ──────────────────────────────────
  window.__silentguardBanner = function (result, source) {
    injectStyle();
    if (document.getElementById('silentguard-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'silentguard-overlay';
    overlay.innerHTML = `
      <div id="silentguard-card">
        <div class="hg-icon">🛡️</div>
        <h2>Phishing URL Detected!</h2>
        <p class="hg-sub">Silent Guard — Homograph Phishing Detector</p>
        <div class="hg-url-box">${escHtml(result.url)}</div>
        <div class="hg-conf">AI Confidence: ${result.confidence.toFixed(1)}%</div>
        <div class="hg-buttons">
          <button id="hg-btn-back">🔙 Go Back to Safety</button>
          <button id="hg-btn-proceed">Proceed Anyway</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    document.getElementById('hg-btn-back').onclick = () => {
      history.back();
      overlay.remove();
    };
    document.getElementById('hg-btn-proceed').onclick = () => overlay.remove();
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
  };

  // ─── Helpers ────────────────────────────────────────────────────────────────
  function escHtml(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function extractPageLinks() {
    const links = new Set();
    document.querySelectorAll('a[href]').forEach(a => {
      const href = a.href;
      if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
        links.add(href);
      }
    });
    return [...links];
  }

  const scannedUrls    = new Set();
  const phishingUrls   = new Set();
  const linkBadgeMap   = new Map(); // url → badge element

  // ─── Scan page links ─────────────────────────────────────────────────────────
  async function scanPageLinks() {
    injectStyle();
    const allLinks = extractPageLinks();
    const newLinks = allLinks.filter(u => !scannedUrls.has(u));
    if (!newLinks.length) return;

    newLinks.forEach(u => scannedUrls.add(u));

    // Mark as scanning
    newLinks.forEach(url => addBadge(url, 'scanning', '⟳'));

    chrome.runtime.sendMessage({ type: 'SCAN_URLS', urls: newLinks }, response => {
      if (chrome.runtime.lastError || !response) return;
      (response.results || []).forEach(r => {
        removeBadge(r.url);
        if (r.label === 'phishing') {
          phishingUrls.add(r.url);
          addBadge(r.url, 'phishing', `⚠ PHISHING ${r.confidence.toFixed(0)}%`);
          showToast(r);
        }
      });
    });
  }

  function addBadge(url, cls, text) {
    document.querySelectorAll(`a[href="${url}"]`).forEach(a => {
      // avoid duplicates
      if (a.querySelector('.hg-link-badge')) return;
      const badge = document.createElement('span');
      badge.className  = `hg-link-badge ${cls}`;
      badge.textContent = text;
      a.appendChild(badge);
      linkBadgeMap.set(url, badge);
    });
  }

  function removeBadge(url) {
    document.querySelectorAll(`a[href="${url}"] .hg-link-badge`).forEach(b => b.remove());
  }

  // ─── MutationObserver for dynamic links ─────────────────────────────────────
  let scanTimer = null;
  function scheduleScan() {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scanPageLinks, 600);
  }

  const observer = new MutationObserver(muts => {
    const hasNewLinks = muts.some(m =>
      [...m.addedNodes].some(n =>
        n.nodeType === 1 && (n.tagName === 'A' || n.querySelector?.('a'))
      )
    );
    if (hasNewLinks) scheduleScan();
  });

  observer.observe(document.documentElement, { childList: true, subtree: true });

  // Initial scan after page load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scanPageLinks);
  } else {
    scanPageLinks();
  }

  // ─── Listen for messages from background / popup ──────────────────────────────
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'ADDRESS_BAR_PHISHING') {
      window.__silentguardBanner(msg.result, 'addressbar');
    }
    if (msg.type === 'GET_PAGE_LINKS') {
      const links = [];
      document.querySelectorAll('a[href]').forEach(a => {
        const href = a.href;
        if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
          links.push(href);
        }
      });
      sendResponse({ links: [...new Set(links)] });
      return true;
    }
  });

})();
