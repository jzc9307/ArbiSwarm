const $ = (selector) => document.querySelector(selector);
const form = $('#searchForm');
const startBtn = $('#startBtn');
const runPanel = $('#runPanel');
const errorPanel = $('#errorPanel');
const sourceWarnings = $('#sourceWarnings');
const summary = $('#summary');
const resultsSection = $('#resultsSection');
const results = $('#results');
const historyDrawer = $('#historyDrawer');
const historyScrim = $('#historyScrim');
const HISTORY_KEY = 'arbiswarm.search-history.v1';
const HISTORY_LIMIT = 10;
let progressTimer;
let toastTimer;

document.querySelectorAll('input[name="sourceMode"]').forEach((input) => {
  input.addEventListener('change', updateSourceNote);
});
$('#useDemoBtn').addEventListener('click', () => {
  document.querySelector('input[name="sourceMode"][value="demo"]').checked = true;
  updateSourceNote();
  form.requestSubmit();
});
$('#historyBtn').addEventListener('click', openHistory);
$('#closeHistoryBtn').addEventListener('click', closeHistory);
historyScrim.addEventListener('click', closeHistory);
$('#clearHistoryBtn').addEventListener('click', () => {
  if (!window.confirm('Clear every saved search from this browser?')) return;
  localStorage.removeItem(HISTORY_KEY);
  renderHistory();
  showToast('Search history cleared');
});
$('#historyList').addEventListener('click', (event) => {
  const item = event.target.closest('[data-history-id]');
  if (item) restoreHistory(item.dataset.historyId);
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && historyDrawer.classList.contains('open')) closeHistory();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const request = {
    query: $('#query').value.trim(),
    resale_estimate: Number($('#resale').value),
    max_purchase_price: $('#maxPrice').value ? Number($('#maxPrice').value) : null,
    source_mode: document.querySelector('input[name="sourceMode"]:checked').value,
    marketplaces: [...document.querySelectorAll('input[name="marketplace"]:checked')].map((input) => input.value),
  };

  if (request.source_mode === 'live' && request.marketplaces.length === 0) {
    showError('Select at least one marketplace.', request.source_mode);
    return;
  }

  setLoading(true, request.source_mode);
  clearOutput();
  try {
    const response = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail;
      throw new Error(typeof detail === 'object' ? detail.message : detail || `Server error ${response.status}`);
    }
    renderResponse(payload);
    saveHistory(request, payload);
  } catch (error) {
    showError(error.message, request.source_mode);
  } finally {
    setLoading(false);
  }
});

async function loadHealth() {
  try {
    const response = await fetch('/api/health');
    const health = await response.json();
    $('#systemState').classList.add('online');
    $('#systemState span:last-child').textContent = health.ai_mode === 'gemini' ? 'AI agents online' : 'Deterministic mode';
  } catch (_) {
    $('#systemState span:last-child').textContent = 'Backend unavailable';
  }
}

function updateSourceNote() {
  const live = document.querySelector('input[name="sourceMode"]:checked').value === 'live';
  $('#marketplacePicker').hidden = !live;
  $('#sourceNote').textContent = live
    ? 'Search four Malaysian marketplaces in one run. A failed source is reported and never replaced with fake results.'
    : 'Demo mode uses a small, clearly labeled snapshot and only returns records relevant to your exact query.';
}

function setLoading(active, sourceMode = 'live') {
  clearInterval(progressTimer);
  startBtn.disabled = active;
  startBtn.querySelector('span').textContent = active ? 'Analyzing…' : 'Run analysis';
  runPanel.hidden = !active;
  if (!active) return;
  $('#runTitle').textContent = sourceMode === 'live' ? 'Searching the live market' : 'Loading the demo snapshot';
  $('#runText').textContent = 'Validating source, relevance, and pricing evidence.';
  let progress = 12;
  $('#runProgress').style.width = `${progress}%`;
  progressTimer = setInterval(() => {
    progress = Math.min(progress + Math.max(1, (88 - progress) * 0.08), 88);
    $('#runProgress').style.width = `${progress}%`;
  }, 450);
}

function clearOutput() {
  errorPanel.hidden = true;
  sourceWarnings.hidden = true;
  summary.hidden = true;
  resultsSection.hidden = true;
  results.replaceChildren();
}

function showError(message, sourceMode) {
  errorPanel.hidden = false;
  $('#errorText').textContent = message;
  $('#useDemoBtn').hidden = sourceMode === 'demo';
}

function renderResponse(data, options = {}) {
  summary.hidden = false;
  resultsSection.hidden = false;
  const buys = data.decisions.filter((item) => item.is_profitable);
  const bestProfit = buys.length ? Math.max(...buys.map((item) => item.estimated_profit_myr)) : null;
  $('#totalMetric').textContent = data.total_scraped;
  $('#keptMetric').textContent = data.decisions.length;
  $('#buyMetric').textContent = buys.length;
  $('#profitMetric').textContent = bestProfit === null ? '—' : formatMoney(bestProfit);
  $('#resultsTitle').textContent = data.decisions.length ? `Decision queue · ${data.query}` : 'No verified candidates';
  const countText = Object.entries(data.source_counts || {})
    .map(([name, count]) => `${marketplaceName(name)} ${count}`)
    .join(' · ');
  $('#resultsMeta').textContent = `${countText || providerLabel(data.provider)} · ${data.ai_mode === 'gemini' ? 'AI enhanced' : 'rule-based fallback'}`;

  if (!data.decisions.length) {
    results.appendChild(emptyState(data.total_scraped));
  } else {
    data.decisions.forEach((decision, index) => results.appendChild(renderCard(decision, index)));
  }
  renderDiscarded(data.discarded);
  renderSourceWarnings(data.source_errors || []);
  summary.scrollIntoView({ behavior: options.instant ? 'auto' : 'smooth', block: 'start' });
}

function renderCard(item, index) {
  const card = document.createElement('article');
  card.className = `deal-card market-${item.marketplace} ${item.is_profitable ? 'buy' : 'pass'}`;
  card.style.setProperty('--delay', `${Math.min(index * 65, 325)}ms`);
  const image = item.image_url
    ? `<img src="${escapeAttr(item.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : '<div class="image-placeholder" aria-hidden="true"><span>AS</span></div>';
  const evidence = [...item.flaws_found, ...item.red_flags].slice(0, 3);
  const seller = item.seller_rating !== null
    ? `★ ${item.seller_rating.toFixed(1)}${item.seller_name ? ` · ${escapeHtml(item.seller_name)}` : ''}`
    : item.listing_rating !== null
      ? `★ ${item.listing_rating.toFixed(1)} product rating${item.review_count !== null ? ` · ${item.review_count} reviews` : ''}`
      : (item.seller_name ? escapeHtml(item.seller_name) : 'Seller rating unavailable');
  const vision = item.vision_score !== null ? `${item.vision_score}/100` : 'Not scored';
  const supportsNegotiation = ['carousell', 'mudah'].includes(item.marketplace);

  card.innerHTML = `
    <div class="deal-image">${image}<span class="source-badge source-${escapeAttr(item.marketplace)}"><small>LISTED ON</small><img src="${marketplaceLogo(item.marketplace)}" alt="${marketplaceName(item.marketplace)}"></span></div>
    <div class="deal-body">
      <div class="deal-topline"><span class="decision ${item.is_profitable ? 'positive' : 'negative'}">${item.is_profitable ? 'BUY SIGNAL' : 'PASS'}</span><span class="risk risk-${item.risk_level}">${item.risk_level} risk</span></div>
      <h3>${escapeHtml(item.title)}</h3>
      <p class="seller-line"><b>From ${marketplaceName(item.marketplace)}</b> · ${seller} · ${escapeHtml(item.true_condition)}</p>
      <div class="economics">
        <div><small>ASK</small><strong>${formatMoney(item.price)}</strong></div>
        <div><small>NET PROFIT</small><strong class="${item.estimated_profit_myr >= 0 ? 'gain' : 'loss'}">${signedMoney(item.estimated_profit_myr)}</strong></div>
        <div><small>MARGIN</small><strong>${item.estimated_margin_pct.toFixed(1)}%</strong></div>
      </div>
      <p class="reasoning">${escapeHtml(item.reasoning)}</p>
      ${evidence.length ? `<div class="evidence">${evidence.map((value) => `<span>${escapeHtml(value)}</span>`).join('')}</div>` : ''}
      <div class="agent-strip">
        <div><small>CONTEXT AGENT</small><strong>${escapeHtml(item.true_condition)}</strong></div>
        <div><small>VISION AGENT</small><strong>${vision}</strong></div>
        <div><small>STRATEGIST</small><strong>${item.is_profitable ? 'Candidate' : 'Rejected'}</strong></div>
      </div>
      ${item.negotiation_message && supportsNegotiation ? negotiationBlock(item.negotiation_message) : ''}
      <div class="deal-actions"><a href="${escapeAttr(item.url)}" target="_blank" rel="noopener noreferrer">Open on ${marketplaceName(item.marketplace)} <span>↗</span></a><span>Total cost ${formatMoney(item.total_cost_myr)}</span></div>
    </div>`;

  const img = card.querySelector('img');
  if (img) img.addEventListener('error', () => { img.replaceWith(makePlaceholder()); }, { once: true });
  const copy = card.querySelector('.copy-button');
  if (copy) copy.addEventListener('click', async () => {
    await navigator.clipboard.writeText(item.negotiation_message);
    copy.textContent = 'Copied';
    setTimeout(() => { copy.textContent = 'Copy'; }, 1300);
  });
  return card;
}

function negotiationBlock(message) {
  return `<div class="negotiation"><div><small>NEGOTIATION DRAFT</small><p>${escapeHtml(message)}</p></div><button class="copy-button" type="button">Copy</button></div>`;
}

function makePlaceholder() {
  const element = document.createElement('div');
  element.className = 'image-placeholder';
  element.innerHTML = '<span>AS</span>';
  return element;
}

function emptyState(total) {
  const element = document.createElement('div');
  element.className = 'empty-state';
  element.innerHTML = `<span>0</span><h3>No trustworthy candidate made the cut.</h3><p>${total ? 'The source returned listings, but all failed relevance, price, or evidence checks.' : 'No matching records were returned for this query and source.'}</p>`;
  return element;
}

function renderDiscarded(items) {
  const panel = $('#discardedPanel');
  panel.hidden = !items.length;
  $('#discardedCount').textContent = `${items.length} listing${items.length === 1 ? '' : 's'} filtered out`;
  const list = $('#discardedList');
  list.replaceChildren();
  items.forEach((item) => {
    const li = document.createElement('li');
    li.innerHTML = `<strong>${escapeHtml(item.title || item.id)}</strong><span>${escapeHtml(item.reason)}</span>`;
    list.appendChild(li);
  });
}

function renderSourceWarnings(items) {
  sourceWarnings.hidden = !items.length;
  const list = $('#sourceWarningList');
  list.replaceChildren();
  items.forEach((item) => {
    const li = document.createElement('li');
    li.textContent = `${marketplaceName(item.marketplace)}: ${item.message}`;
    list.appendChild(li);
  });
}

function getHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    return Array.isArray(value) ? value : [];
  } catch (_) {
    return [];
  }
}

function saveHistory(request, response) {
  const signature = JSON.stringify({
    query: request.query.toLowerCase(),
    resale: request.resale_estimate,
    max: request.max_purchase_price,
    mode: request.source_mode,
    marketplaces: [...request.marketplaces].sort(),
  });
  const entry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    signature,
    created_at: new Date().toISOString(),
    request,
    response,
  };
  const next = [entry, ...getHistory().filter((item) => item.signature !== signature)].slice(0, HISTORY_LIMIT);
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch (_) {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(next.slice(0, 4)));
    } catch (_) {
      showToast('This result was too large to save locally');
    }
  }
  renderHistory();
}

function renderHistory() {
  const entries = getHistory();
  const list = $('#historyList');
  list.replaceChildren();
  $('#historyEmpty').hidden = entries.length > 0;
  $('#clearHistoryBtn').hidden = entries.length === 0;
  $('#historyCount').hidden = entries.length === 0;
  $('#historyCount').textContent = entries.length;

  entries.forEach((entry) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'history-item';
    item.dataset.historyId = entry.id;
    const decisions = entry.response?.decisions || [];
    const buys = decisions.filter((decision) => decision.is_profitable).length;
    const markets = entry.request?.source_mode === 'demo'
      ? 'Demo snapshot'
      : (entry.request?.marketplaces || []).map(marketplaceName).join(' + ');
    item.innerHTML = `
      <span class="history-item-top"><strong>${escapeHtml(entry.response?.query || entry.request?.query || 'Saved search')}</strong><time>${formatHistoryDate(entry.created_at)}</time></span>
      <span class="history-item-markets">${escapeHtml(markets || 'Marketplace search')}</span>
      <span class="history-item-stats"><b>${decisions.length} analyzed</b><b>${buys} buy signal${buys === 1 ? '' : 's'}</b><em>Open snapshot →</em></span>`;
    list.appendChild(item);
  });
}

function restoreHistory(id) {
  const entry = getHistory().find((item) => item.id === id);
  if (!entry?.response) return;
  const request = entry.request || {};
  $('#query').value = request.query || entry.response.query || '';
  if (request.resale_estimate != null) $('#resale').value = request.resale_estimate;
  $('#maxPrice').value = request.max_purchase_price ?? '';
  const mode = document.querySelector(`input[name="sourceMode"][value="${request.source_mode || 'live'}"]`);
  if (mode) mode.checked = true;
  document.querySelectorAll('input[name="marketplace"]').forEach((input) => {
    input.checked = (request.marketplaces || entry.response.marketplaces || []).includes(input.value);
  });
  updateSourceNote();
  clearOutput();
  renderResponse(entry.response, { instant: true });
  closeHistory();
  showToast('Loaded saved result — no rerun needed');
}

function openHistory() {
  renderHistory();
  historyDrawer.inert = false;
  historyDrawer.classList.add('open');
  historyDrawer.setAttribute('aria-hidden', 'false');
  historyScrim.hidden = false;
  requestAnimationFrame(() => historyScrim.classList.add('visible'));
  $('#historyBtn').setAttribute('aria-expanded', 'true');
  document.body.classList.add('drawer-open');
  $('#closeHistoryBtn').focus();
}

function closeHistory() {
  historyDrawer.classList.remove('open');
  historyDrawer.setAttribute('aria-hidden', 'true');
  historyDrawer.inert = true;
  historyScrim.classList.remove('visible');
  setTimeout(() => { if (!historyDrawer.classList.contains('open')) historyScrim.hidden = true; }, 180);
  $('#historyBtn').setAttribute('aria-expanded', 'false');
  document.body.classList.remove('drawer-open');
}

function showToast(message) {
  clearTimeout(toastTimer);
  const toast = $('#toast');
  toast.textContent = message;
  toast.hidden = false;
  requestAnimationFrame(() => toast.classList.add('visible'));
  toastTimer = setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => { toast.hidden = true; }, 180);
  }, 2400);
}

function formatHistoryDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('en-MY', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date);
}

function marketplaceName(value) { return ({ carousell: 'Carousell', lazada: 'Lazada', mudah: 'Mudah', shopee: 'Shopee' })[value] || value; }
function marketplaceLogo(value) { return `/static/assets/${({ carousell: 'carousell', lazada: 'lazada', mudah: 'mudah', shopee: 'shopee' })[value] || 'carousell'}.svg`; }
function providerLabel(provider) { return ({ multi_market: 'Multi-market', carousell: 'Carousell', lazada: 'Lazada', mudah: 'Mudah', demo_cache: 'Demo snapshot' })[provider] || provider; }
function formatMoney(value) { return `RM${Number(value).toLocaleString('en-MY', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`; }
function signedMoney(value) { return `${value >= 0 ? '+' : '−'}${formatMoney(Math.abs(value))}`; }
function escapeHtml(value) { const div = document.createElement('div'); div.textContent = String(value ?? ''); return div.innerHTML; }
function escapeAttr(value) { return escapeHtml(value).replaceAll('`', '&#96;'); }

loadHealth();
updateSourceNote();
renderHistory();
