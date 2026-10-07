const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
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
const HISTORY_KEY = 'arbiswarm.search-history.v2';
const WATCHLIST_KEY = 'arbiswarm.watchlists.v1';
const HISTORY_LIMIT = 10;
let progressTimer;
let stageTimer;
let toastTimer;
let currentRequest = null;
let currentResponse = null;

const pipelineStages = [
  ['Opening marketplace channels', 'Negotiating verified source connections.'],
  ['Streaming listing signals', 'Reading live prices, seller evidence, and product URLs.'],
  ['Fingerprinting variants', 'Separating full sets, blind boxes, characters, and accessories.'],
  ['Clustering cross-market matches', 'Linking equivalent offers without mixing incompatible variants.'],
  ['Estimating fair resale band', 'Calculating a market median and confidence range.'],
  ['Scoring seller confidence', 'Weighing ratings, reviews, sold count, and suspicious pricing.'],
  ['Running risk engine', 'Applying shipping, fees, evidence penalties, and margin rules.'],
  ['Assembling intelligence board', 'Ranking the strongest opportunities for review.'],
];

$$('input[name="sourceMode"]').forEach((input) => input.addEventListener('change', updateSourceNote));
$$('input[name="pricingMode"]').forEach((input) => input.addEventListener('change', updatePricingMode));
$('#useDemoBtn').addEventListener('click', () => {
  $('input[name="sourceMode"][value="demo"]').checked = true;
  updateSourceNote();
  form.requestSubmit();
});
$('#historyBtn').addEventListener('click', openHistory);
$('#closeHistoryBtn').addEventListener('click', closeHistory);
historyScrim.addEventListener('click', closeHistory);
$('#watchSearchBtn').addEventListener('click', saveCurrentWatchlist);
$('#addCurrentWatchBtn').addEventListener('click', saveCurrentWatchlist);
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
$('#watchlistList').addEventListener('click', async (event) => {
  const scan = event.target.closest('[data-watch-scan]');
  const remove = event.target.closest('[data-watch-remove]');
  if (scan) await scanWatchlist(scan.dataset.watchScan);
  if (remove) removeWatchlist(remove.dataset.watchRemove);
});
$$('[data-saved-tab]').forEach((button) => button.addEventListener('click', () => switchSavedTab(button.dataset.savedTab)));
$('#sourceBar').addEventListener('click', async (event) => {
  const button = event.target.closest('[data-refresh-market]');
  if (button) await refreshMarketplace(button.dataset.refreshMarket, button);
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && historyDrawer.classList.contains('open')) closeHistory();
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const request = buildRequest();
  if (request.source_mode === 'live' && request.marketplaces.length === 0) {
    showError('Select at least one marketplace.', request.source_mode);
    return;
  }
  await executeSearch(request, { save: true });
});

function buildRequest() {
  const pricingMode = $('input[name="pricingMode"]:checked').value;
  return {
    query: $('#query').value.trim(),
    pricing_mode: pricingMode,
    resale_estimate: pricingMode === 'manual' ? Number($('#resale').value) : null,
    max_purchase_price: $('#maxPrice').value ? Number($('#maxPrice').value) : null,
    source_mode: $('input[name="sourceMode"]:checked').value,
    marketplaces: $$('input[name="marketplace"]:checked').map((input) => input.value),
  };
}

async function executeSearch(request, options = {}) {
  currentRequest = request;
  setLoading(true, request.source_mode);
  clearOutput();
  try {
    const payload = await fetchSearch(request);
    currentResponse = payload;
    completeLoading();
    renderResponse(payload);
    if (options.save) saveHistory(request, payload);
    return payload;
  } catch (error) {
    showError(error.message, request.source_mode);
    return null;
  } finally {
    window.setTimeout(() => setLoading(false), 320);
  }
}

async function fetchSearch(request) {
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
  return payload;
}

async function loadHealth() {
  try {
    const response = await fetch('/api/health');
    const health = await response.json();
    $('#systemState').classList.add('online');
    const shopee = health.marketplaces?.shopee === 'nexscope_api' ? ' · Shopee API ready' : '';
    const version = health.version ? ` · v${health.version}` : '';
    $('#systemState span:last-child').textContent = `${health.ai_mode === 'gemini' ? 'AI agents online' : 'Deterministic mode'}${shopee}${version}`;
  } catch (_) {
    $('#systemState span:last-child').textContent = 'Backend unavailable';
  }
}

function updateSourceNote() {
  const live = $('input[name="sourceMode"]:checked').value === 'live';
  $('#marketplacePicker').hidden = !live;
  $('#sourceNote').textContent = live
    ? 'Search four Malaysian marketplaces in one run. A failed source is reported and never replaced with fake results.'
    : 'Demo mode uses a small, clearly labeled snapshot and only returns records relevant to your exact query.';
}

function updatePricingMode() {
  const manual = $('input[name="pricingMode"]:checked').value === 'manual';
  $('#manualResaleWrap').hidden = !manual;
  $('#autoResaleState').hidden = manual;
  $('#resale').required = manual;
}

function setLoading(active, sourceMode = 'live') {
  clearInterval(progressTimer);
  clearInterval(stageTimer);
  startBtn.disabled = active;
  startBtn.querySelector('span').textContent = active ? 'Analyzing…' : 'Run analysis';
  runPanel.hidden = !active;
  if (!active) return;
  let progress = 7;
  let stage = 0;
  renderLoadingStage(stage, sourceMode, progress);
  progressTimer = setInterval(() => {
    progress = Math.min(progress + Math.max(.8, (93 - progress) * .052), 93);
    $('#runProgress').style.width = `${progress}%`;
    $('#runPercent').textContent = `${Math.round(progress)}%`;
  }, 280);
  stageTimer = setInterval(() => {
    stage = Math.min(stage + 1, pipelineStages.length - 1);
    renderLoadingStage(stage, sourceMode, progress);
  }, 920);
}

function renderLoadingStage(index, sourceMode, progress) {
  const [title, text] = pipelineStages[index];
  $('#runTitle').textContent = sourceMode === 'demo' && index === 0 ? 'Opening verified demo snapshot' : title;
  $('#runText').textContent = text;
  $('#runPercent').textContent = `${Math.round(progress)}%`;
  $('#runProgress').style.width = `${progress}%`;
  const start = Math.max(0, index - 2);
  $('#runLog').innerHTML = pipelineStages.slice(start, index + 1).map((item, offset, rows) => {
    const active = offset === rows.length - 1;
    return `<span class="${active ? 'active' : 'done'}"><i>${active ? '●' : '✓'}</i>${escapeHtml(item[0])}</span>`;
  }).join('');
}

function completeLoading() {
  clearInterval(progressTimer);
  clearInterval(stageTimer);
  $('#runTitle').textContent = 'Intelligence board ready';
  $('#runText').textContent = 'Market evidence clustered, valued, and risk-scored.';
  $('#runPercent').textContent = '100%';
  $('#runProgress').style.width = '100%';
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

function normalizedGroups(data) {
  const decisions = data.decisions || [];
  if (data.product_groups?.length) {
    return data.product_groups.map((group) => ({
      ...group,
      offers: group.offer_ids.map((id) => decisions.find((item) => (item.offer_id || `${item.marketplace}:${item.listing_id}`) === id)).filter(Boolean),
    }));
  }
  return decisions.map((item, index) => ({
    group_id: item.group_id || `legacy-${index}`,
    name: item.group_name || item.title,
    variant_label: item.variant_label || 'Listing',
    variant_warning: item.variant_warning || null,
    offer_count: 1,
    marketplace_count: 1,
    marketplaces: [item.marketplace],
    lowest_price_myr: item.price,
    median_price_myr: item.resale_estimate_myr || item.price,
    highest_price_myr: item.price,
    confidence: item.resale_confidence || 'manual',
    offers: [item],
  }));
}

function renderResponse(data, options = {}) {
  currentResponse = data;
  summary.hidden = false;
  resultsSection.hidden = false;
  const decisions = data.decisions || [];
  const buys = decisions.filter((item) => item.is_profitable);
  const groups = normalizedGroups(data);
  const bestProfit = buys.length ? Math.max(...buys.map((item) => item.estimated_profit_myr)) : null;
  $('#totalMetric').textContent = data.total_scraped;
  $('#keptMetric').textContent = decisions.length;
  $('#buyMetric').textContent = buys.length;
  $('#profitMetric').textContent = bestProfit === null ? '—' : formatMoney(bestProfit);
  $('#resultsTitle').textContent = decisions.length ? `${groups.length} matched product${groups.length === 1 ? '' : 's'} · ${data.query}` : 'No verified candidates';
  const countText = Object.entries(data.source_counts || {}).map(([name, count]) => `${marketplaceName(name)} ${count}`).join(' · ');
  $('#resultsMeta').textContent = `${countText || providerLabel(data.provider)} · ${data.pricing_mode === 'auto' ? 'market-priced' : 'manual resale'} · ${data.ai_mode === 'gemini' ? 'AI enhanced' : 'rules verified'}`;
  renderSourceBar(data);
  results.replaceChildren();
  if (!decisions.length) results.appendChild(emptyState(data.total_scraped));
  else groups.forEach((group, index) => results.appendChild(renderComparisonGroup(group, index)));
  renderDiscarded(data.discarded || []);
  renderSourceWarnings(data.source_errors || []);
  summary.scrollIntoView({ behavior: options.instant ? 'auto' : 'smooth', block: 'start' });
}

function renderComparisonGroup(group, index) {
  const section = document.createElement('section');
  section.className = 'comparison-group';
  section.style.setProperty('--delay', `${Math.min(index * 80, 400)}ms`);
  const marketNames = group.marketplaces.map(marketplaceName).join(' + ');
  section.innerHTML = `
    <header class="comparison-header">
      <div><p><span class="live-pulse"></span> CROSS-MARKET MATCH</p><h3>${escapeHtml(shorten(group.name, 88))}</h3><div class="variant-row"><b>${escapeHtml(group.variant_label)}</b>${group.variant_warning ? `<span>${escapeHtml(group.variant_warning)}</span>` : ''}</div></div>
      <div class="market-range"><small>${group.offer_count} OFFER${group.offer_count === 1 ? '' : 'S'} · ${escapeHtml(marketNames)}</small><strong>${formatMoney(group.lowest_price_myr)}—${formatMoney(group.highest_price_myr)}</strong><span>${escapeHtml(group.confidence)} pricing confidence</span></div>
    </header>
    <div class="group-offers"></div>`;
  const offerGrid = $('.group-offers', section);
  group.offers.forEach((offer, offerIndex) => offerGrid.appendChild(renderCard(offer, offerIndex)));
  return section;
}

function renderCard(item, index) {
  const card = document.createElement('article');
  card.className = `deal-card market-${item.marketplace} ${item.is_profitable ? 'buy' : 'pass'}`;
  card.style.setProperty('--delay', `${Math.min(index * 55, 275)}ms`);
  const image = item.image_url
    ? `<img src="${escapeAttr(item.image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : '<div class="image-placeholder" aria-hidden="true"><span>AS</span></div>';
  const evidence = [...(item.flaws_found || []), ...(item.red_flags || [])].slice(0, 3);
  const seller = item.seller_rating !== null && item.seller_rating !== undefined
    ? `★ ${Number(item.seller_rating).toFixed(1)}${item.seller_name ? ` · ${escapeHtml(item.seller_name)}` : ''}`
    : item.listing_rating !== null && item.listing_rating !== undefined
      ? `★ ${Number(item.listing_rating).toFixed(1)}${item.review_count !== null ? ` · ${item.review_count} reviews` : ''}`
      : (item.seller_name ? escapeHtml(item.seller_name) : 'Rating evidence unavailable');
  const vision = item.vision_score !== null && item.vision_score !== undefined ? `${item.vision_score}/100` : 'Not scored';
  const supportsNegotiation = ['carousell', 'mudah'].includes(item.marketplace);
  const confidence = item.seller_confidence_score ?? 35;
  const collectedAt = item.collected_at || currentResponse?.collected_at;
  const factors = item.decision_factors || [item.reasoning];

  card.innerHTML = `
    <div class="deal-image">${image}<span class="source-badge"><small>LISTED ON</small><img src="${marketplaceLogo(item.marketplace)}" alt="${marketplaceName(item.marketplace)}"></span><span class="freshness-badge">● ${freshness(collectedAt)}</span></div>
    <div class="deal-body">
      <div class="deal-topline"><span class="decision ${item.is_profitable ? 'positive' : 'negative'}">${item.is_profitable ? 'BUY SIGNAL' : 'PASS'}</span><span class="risk risk-${item.risk_level}">${item.risk_level} risk</span></div>
      <h3>${escapeHtml(item.title)}</h3>
      <p class="seller-line"><b>From ${marketplaceName(item.marketplace)}</b> · ${seller} · ${escapeHtml(item.true_condition)}</p>
      <div class="confidence-line"><span><i style="--score:${confidence}%"></i></span><b>${confidence}/100 seller confidence</b><em>${escapeHtml(item.seller_confidence_label || 'limited')}</em></div>
      <div class="economics">
        <div><small>ASK</small><strong>${formatMoney(item.price)}</strong></div>
        <div><small>FAIR RESALE</small><strong>${formatMoney(item.resale_estimate_myr ?? 0)}</strong><span>${formatMoney(item.resale_low_myr ?? 0)}–${formatMoney(item.resale_high_myr ?? 0)}</span></div>
        <div><small>NET PROFIT</small><strong class="${item.estimated_profit_myr >= 0 ? 'gain' : 'loss'}">${signedMoney(item.estimated_profit_myr)}</strong></div>
        <div><small>MARGIN</small><strong>${Number(item.estimated_margin_pct).toFixed(1)}%</strong><span>${escapeHtml(item.resale_confidence || 'manual')} confidence</span></div>
      </div>
      <p class="reasoning">${escapeHtml(item.reasoning)}</p>
      ${evidence.length ? `<div class="evidence">${evidence.map((value) => `<span>${escapeHtml(value)}</span>`).join('')}</div>` : ''}
      <div class="agent-strip"><div><small>CONTEXT</small><strong>${escapeHtml(item.true_condition)}</strong></div><div><small>VISION</small><strong>${vision}</strong></div><div><small>STRATEGIST</small><strong>${item.is_profitable ? 'Candidate' : 'Rejected'}</strong></div></div>
      <details class="deal-breakdown"><summary><span>How this decision was calculated</span><i>⌄</i></summary><div class="breakdown-body">
        <div class="formula"><span>${formatMoney(item.price)}<small>listing</small></span><b>+</b><span>${formatMoney(item.shipping_cost_myr ?? 0)}<small>shipping</small></span><b>+</b><span>${formatMoney(item.platform_fee_myr ?? 0)}<small>fee</small></span><b>=</b><span>${formatMoney(item.total_cost_myr)}<small>total cost</small></span></div>
        <div class="factor-grid"><div><small>MARKET EVIDENCE</small><ul>${factors.map((factor) => `<li>${escapeHtml(factor)}</li>`).join('')}</ul></div><div><small>SELLER SIGNALS</small><ul>${(item.seller_confidence_reasons || ['Seller evidence unavailable']).map((reason) => `<li>${escapeHtml(reason)}</li>`).join('')}</ul></div></div>
      </div></details>
      ${item.negotiation_message && supportsNegotiation ? negotiationBlock(item.negotiation_message) : ''}
      <div class="deal-actions"><a href="${escapeAttr(item.url)}" target="_blank" rel="noopener noreferrer">Open on ${marketplaceName(item.marketplace)} <span>↗</span></a><span>Total cost ${formatMoney(item.total_cost_myr)}</span></div>
    </div>`;
  const productImage = $('.deal-image > img', card);
  if (productImage) productImage.addEventListener('error', () => productImage.replaceWith(makePlaceholder()), { once: true });
  const copy = $('.copy-button', card);
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
  element.innerHTML = `<span>0</span><h3>No trustworthy candidate made the cut.</h3><p>${total ? 'The source returned listings, but all failed relevance, price, variant, or evidence checks.' : 'No matching records were returned for this query and source.'}</p>`;
  return element;
}

function renderSourceBar(data) {
  const bar = $('#sourceBar');
  bar.replaceChildren();
  const markets = data.marketplaces || Object.keys(data.source_counts || {});
  markets.forEach((market) => {
    const count = data.source_counts?.[market] ?? 0;
    const failed = (data.source_errors || []).some((item) => item.marketplace === market);
    const chip = document.createElement('div');
    chip.className = `source-chip market-${market}${failed ? ' failed' : ''}`;
    chip.innerHTML = `<img src="${marketplaceLogo(market)}" alt=""><span><b>${marketplaceName(market)}</b><small>${failed ? 'source unavailable' : `${count} found · ${freshness(data.collected_at)}`}</small></span>${data.source_mode === 'live' ? `<button type="button" data-refresh-market="${market}" aria-label="Refresh ${marketplaceName(market)}">↻</button>` : ''}`;
    bar.appendChild(chip);
  });
}

async function refreshMarketplace(market, button) {
  if (!currentRequest || currentRequest.source_mode !== 'live') return;
  button.disabled = true;
  button.classList.add('spinning');
  showToast(`Refreshing ${marketplaceName(market)} only…`);
  try {
    const fresh = await fetchSearch({ ...currentRequest, marketplaces: [market] });
    const other = (currentResponse.decisions || []).filter((item) => item.marketplace !== market);
    const merged = [...other, ...(fresh.decisions || [])];
    const sourceCounts = { ...(currentResponse.source_counts || {}), [market]: fresh.source_counts?.[market] ?? 0 };
    currentResponse = rebuildClientGroups({
      ...currentResponse,
      collected_at: fresh.collected_at,
      source_counts: sourceCounts,
      source_errors: [ ...(currentResponse.source_errors || []).filter((item) => item.marketplace !== market), ...(fresh.source_errors || []) ],
      total_scraped: Object.values(sourceCounts).reduce((sum, count) => sum + Number(count || 0), 0),
      kept_after_filter: merged.length,
      decisions: merged,
      discarded: [ ...(currentResponse.discarded || []).filter((item) => item.marketplace !== market), ...(fresh.discarded || []) ],
    });
    renderResponse(currentResponse, { instant: true });
    saveHistory(currentRequest, currentResponse);
    showToast(`${marketplaceName(market)} refreshed — ${fresh.decisions.length} analyzed`);
  } catch (error) {
    showToast(`${marketplaceName(market)} refresh failed: ${error.message}`);
  } finally {
    button.disabled = false;
    button.classList.remove('spinning');
  }
}

function rebuildClientGroups(data) {
  const groups = [];
  (data.decisions || []).forEach((offer) => {
    let group = groups.find((candidate) => candidate.variant_kind === offer.variant_kind && titleSimilarity(candidate.name, offer.group_name || offer.title) >= .35);
    if (!group) {
      group = { group_id: offer.group_id, name: offer.group_name || offer.title, variant_label: offer.variant_label, variant_kind: offer.variant_kind, variant_warning: offer.variant_warning, offers: [] };
      groups.push(group);
    }
    group.offers.push(offer);
  });
  data.product_groups = groups.map((group) => {
    const prices = group.offers.map((item) => item.price).sort((a, b) => a - b);
    return { ...group, offer_ids: group.offers.map((item) => item.offer_id), offer_count: group.offers.length, marketplace_count: new Set(group.offers.map((item) => item.marketplace)).size, marketplaces: [...new Set(group.offers.map((item) => item.marketplace))], lowest_price_myr: prices[0], median_price_myr: prices[Math.floor(prices.length / 2)], highest_price_myr: prices.at(-1), confidence: group.offers[0]?.resale_confidence || 'low' };
  });
  return data;
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

function getStored(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) ? value : [];
  } catch (_) { return []; }
}

function getHistory() { return getStored(HISTORY_KEY); }
function getWatchlists() { return getStored(WATCHLIST_KEY); }

function saveHistory(request, response) {
  const signature = JSON.stringify({ query: request.query.toLowerCase(), pricing: request.pricing_mode, resale: request.resale_estimate, max: request.max_purchase_price, mode: request.source_mode, marketplaces: [...request.marketplaces].sort() });
  const entry = { id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, signature, created_at: new Date().toISOString(), request, response };
  const next = [entry, ...getHistory().filter((item) => item.signature !== signature)].slice(0, HISTORY_LIMIT);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)); }
  catch (_) {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next.slice(0, 4))); }
    catch (_) { showToast('This result was too large to save locally'); }
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
    const groups = entry.response?.product_groups?.length || decisions.length;
    const buys = decisions.filter((decision) => decision.is_profitable).length;
    const markets = entry.request?.source_mode === 'demo' ? 'Demo snapshot' : (entry.request?.marketplaces || []).map(marketplaceName).join(' + ');
    item.innerHTML = `<span class="history-item-top"><strong>${escapeHtml(entry.response?.query || entry.request?.query || 'Saved search')}</strong><time>${formatHistoryDate(entry.created_at)}</time></span><span class="history-item-markets">${escapeHtml(markets || 'Marketplace search')}</span><span class="history-item-stats"><b>${groups} matches</b><b>${buys} buy signal${buys === 1 ? '' : 's'}</b><em>Open snapshot →</em></span>`;
    list.appendChild(item);
  });
  renderWatchlists();
}

function restoreHistory(id) {
  const entry = getHistory().find((item) => item.id === id);
  if (!entry?.response) return;
  restoreForm(entry.request || {}, entry.response);
  currentRequest = entry.request;
  currentResponse = entry.response;
  clearOutput();
  renderResponse(entry.response, { instant: true });
  closeHistory();
  showToast('Loaded saved result — no rerun needed');
}

function saveCurrentWatchlist() {
  if (!currentRequest || !currentResponse) {
    showToast('Run a search first, then save it');
    return;
  }
  if (currentRequest.source_mode !== 'live') {
    showToast('Watchlists use live market searches — switch to Live market first');
    return;
  }
  const signature = JSON.stringify({ query: currentRequest.query.toLowerCase(), max: currentRequest.max_purchase_price, marketplaces: currentRequest.marketplaces });
  const decisions = currentResponse.decisions || [];
  const bestPrice = decisions.length ? Math.min(...decisions.map((item) => item.price)) : null;
  const item = { id: `${Date.now()}`, signature, created_at: new Date().toISOString(), last_checked_at: new Date().toISOString(), request: currentRequest, best_price: bestPrice, buy_count: decisions.filter((offer) => offer.is_profitable).length };
  const next = [item, ...getWatchlists().filter((watch) => watch.signature !== signature)];
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next));
  renderWatchlists();
  showToast('Watchlist saved — use Scan now to check the market');
}

function renderWatchlists() {
  const items = getWatchlists();
  const list = $('#watchlistList');
  list.replaceChildren();
  $('#watchlistEmpty').hidden = items.length > 0;
  $('#watchCount').hidden = items.length === 0;
  $('#watchCount').textContent = items.length;
  items.forEach((watch) => {
    const card = document.createElement('article');
    card.className = 'watch-item';
    card.innerHTML = `<div class="watch-item-top"><span><i></i><b>ACTIVE WATCH</b></span><time>${formatHistoryDate(watch.last_checked_at)}</time></div><h3>${escapeHtml(watch.request.query)}</h3><p>${(watch.request.marketplaces || []).map(marketplaceName).join(' + ')} · Ceiling ${watch.request.max_purchase_price ? formatMoney(watch.request.max_purchase_price) : 'none'}</p><div class="watch-stats"><span><small>BEST SEEN</small><strong>${watch.best_price == null ? '—' : formatMoney(watch.best_price)}</strong></span><span><small>BUY SIGNALS</small><strong>${watch.buy_count || 0}</strong></span></div><div class="watch-actions"><button type="button" data-watch-scan="${watch.id}">↻ Scan now</button><button class="remove" type="button" data-watch-remove="${watch.id}">Remove</button></div>`;
    list.appendChild(card);
  });
}

async function scanWatchlist(id) {
  const watch = getWatchlists().find((item) => item.id === id);
  if (!watch) return;
  closeHistory();
  restoreForm(watch.request, {});
  const previousPrice = watch.best_price;
  const previousBuys = watch.buy_count || 0;
  const response = await executeSearch(watch.request, { save: true });
  if (!response) return;
  const offers = response.decisions || [];
  const bestPrice = offers.length ? Math.min(...offers.map((item) => item.price)) : null;
  const buyCount = offers.filter((item) => item.is_profitable).length;
  const next = getWatchlists().map((item) => item.id === id ? { ...item, last_checked_at: new Date().toISOString(), best_price: bestPrice, buy_count: buyCount } : item);
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next));
  renderWatchlists();
  if (bestPrice !== null && previousPrice !== null && bestPrice < previousPrice) showToast(`Price alert: best offer dropped ${formatMoney(previousPrice - bestPrice)}`);
  else if (buyCount > previousBuys) showToast(`Deal alert: ${buyCount - previousBuys} new buy signal${buyCount - previousBuys === 1 ? '' : 's'}`);
  else showToast('Watchlist checked — no stronger deal yet');
}

function removeWatchlist(id) {
  if (!window.confirm('Remove this watchlist?')) return;
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(getWatchlists().filter((item) => item.id !== id)));
  renderWatchlists();
  showToast('Watchlist removed');
}

function restoreForm(request, response) {
  $('#query').value = request.query || response.query || '';
  const pricing = request.pricing_mode || (request.resale_estimate != null ? 'manual' : 'auto');
  const pricingRadio = $(`input[name="pricingMode"][value="${pricing}"]`);
  if (pricingRadio) pricingRadio.checked = true;
  if (request.resale_estimate != null) $('#resale').value = request.resale_estimate;
  $('#maxPrice').value = request.max_purchase_price ?? '';
  const mode = $(`input[name="sourceMode"][value="${request.source_mode || 'live'}"]`);
  if (mode) mode.checked = true;
  $$('input[name="marketplace"]').forEach((input) => { input.checked = (request.marketplaces || response.marketplaces || []).includes(input.value); });
  updateSourceNote();
  updatePricingMode();
}

function switchSavedTab(name) {
  $$('[data-saved-tab]').forEach((button) => button.classList.toggle('active', button.dataset.savedTab === name));
  $('#historyPane').hidden = name !== 'history';
  $('#watchlistsPane').hidden = name !== 'watchlists';
  $('#historyTitle').textContent = name === 'history' ? 'Search history' : 'Watchlists';
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
  }, 3000);
}

function freshness(value) {
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return 'snapshot';
  const seconds = Math.max(0, Math.round((Date.now() - time) / 1000));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function titleSimilarity(left, right) {
  const tokens = (value) => new Set(String(value || '').toLowerCase().match(/[a-z0-9]+/g) || []);
  const a = tokens(left); const b = tokens(right); const union = new Set([...a, ...b]);
  return union.size ? [...a].filter((value) => b.has(value)).length / union.size : 0;
}

function formatHistoryDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('en-MY', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }).format(date); }
function marketplaceName(value) { return ({ carousell: 'Carousell', lazada: 'Lazada', mudah: 'Mudah', shopee: 'Shopee' })[value] || value; }
function marketplaceLogo(value) { return `/static/assets/${({ carousell: 'carousell', lazada: 'lazada', mudah: 'mudah', shopee: 'shopee' })[value] || 'carousell'}.svg`; }
function providerLabel(provider) { return ({ multi_market: 'Multi-market', carousell: 'Carousell', lazada: 'Lazada', mudah: 'Mudah', shopee: 'Shopee', demo_cache: 'Demo snapshot' })[provider] || provider; }
function formatMoney(value) { const number = Number(value); return Number.isFinite(number) ? `RM${number.toLocaleString('en-MY', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}` : '—'; }
function signedMoney(value) { const number = Number(value) || 0; return `${number >= 0 ? '+' : '−'}${formatMoney(Math.abs(number))}`; }
function shorten(value, length) { const text = String(value || 'Matched product'); return text.length > length ? `${text.slice(0, length - 1)}…` : text; }
function escapeHtml(value) { const div = document.createElement('div'); div.textContent = String(value ?? ''); return div.innerHTML; }
function escapeAttr(value) { return escapeHtml(value).replaceAll('`', '&#96;'); }

loadHealth();
updateSourceNote();
updatePricingMode();
renderHistory();
