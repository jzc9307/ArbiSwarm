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
let viewFilters = {markets:[], kind:'', maxPrice:null};
let viewRevision = 0;
let operationBusy = false;
let selectedOfferId = null;
let chatHistory = [];
let chatBusy = false;
let pendingSelection = null;
let selectionReturnFocus = null;
let composerDraft = null;
let closeChatTimer;
let dragState = null;
let chatBackgroundState = [];
let quickActionsTimer;
let chatResizeAnimation = null;
let chatLayoutFollow = false;
let chatLayoutTimer;

function selectedListing() { return currentResponse?.decisions.find((item) => offerKey(item) === selectedOfferId); }
function visibleOffers() { return ArbiChatState.filterOffers(currentResponse?.decisions || [], viewFilters); }
function listingIdentity(item, full = false) {
  return `${item.image_url ? `<img class="item-thumb" src="${escapeAttr(item.image_url)}" alt="" referrerpolicy="no-referrer">` : '<div class="item-thumb item-no-photo">AS</div>'}<div class="item-identity"><small>${escapeHtml(marketplaceName(item.marketplace))} · ${formatMoney(item.price)}</small><${full ? 'h3 id="selectionTitle"' : 'strong'}>${escapeHtml(item.title)}</${full ? 'h3' : 'strong'}><span>${escapeHtml(item.variant_label || item.true_condition || 'Variant not established')}</span></div>`;
}
function previewListing(item) {
  selectionReturnFocus = document.activeElement;
  pendingSelection = { item, response: currentResponse };
  $('#selectionPreview').innerHTML = `<div class="selection-product">${listingIdentity(item, true)}</div><div class="selection-facts"><span><small>ASKING PRICE</small><b>${formatMoney(item.price)}</b></span><span><small>DECISION</small><b>${item.is_profitable ? 'Buy signal' : 'Pass'} · ${escapeHtml(item.risk_level)} risk</b></span></div>`;
  $('#selectionDialog').showModal();
  $('#confirmSelection').focus();
}
$('#cancelSelection').addEventListener('click', () => $('#selectionDialog').close());
$('#selectionDialog').addEventListener('close', () => {
  if (pendingSelection) selectionReturnFocus?.focus();
  pendingSelection = null;
});
$('#confirmSelection').addEventListener('click', () => {
  if (!pendingSelection || pendingSelection.response !== currentResponse || operationBusy) {
    $('#selectionDialog').close(); showToast('The search changed. Select an item from the current board.'); return;
  }
  selectedOfferId = offerKey(pendingSelection.item);
  pendingSelection = null;
  $('#selectionDialog').close();
  openCopilot();
  setChatDraft('Explain this listing', {kind:'review'});
});
$('#selectedIdentity').addEventListener('click', () => { const item = selectedListing(); if (item) previewListing(item); });

function focusListing(item) {
  const card = $$('.deal-card').find((node) => node.dataset.offerId === offerKey(item));
  if (!card) return;
  closeCopilot();
  $$('.deal-card').forEach((node) => node.classList.remove('arbi-selected'));
  card.classList.add('arbi-selected');
  card.scrollIntoView({behavior:'smooth', block:'center'});
  $('.ask-listing', card)?.focus({preventScroll:true});
}
function insightCard(item, snapshot = currentResponse) {
  const card = document.createElement('section'); card.className = 'arbi-insight';
  const verdict = item.is_profitable ? 'Clears the current checks. Verify the item before buying.' : item.estimated_profit_myr > 0 ? 'Positive profit, but evidence or risk checks still fail.' : 'Does not clear the required profit and margin checks.';
card.innerHTML = `<div class="insight-heading"><b>${item.is_profitable ? 'BUY SIGNAL' : 'PASS'}</b><span>${escapeHtml(item.risk_level)} risk</span></div><div class="insight-metrics"><div><small>ASK</small><strong>${formatMoney(item.price)}</strong></div><div><small>EST. PROFIT</small><strong class="${item.estimated_profit_myr >= 0 ? 'gain' : 'loss'}">${signedMoney(item.estimated_profit_myr)}</strong></div><div><small>MARGIN</small><strong>${Number(item.estimated_margin_pct).toFixed(1)}%</strong></div></div><p class="insight-summary">${escapeHtml(verdict)}</p><details><summary>Why this decision? <span>＋</span></summary><p>${escapeHtml(item.reasoning)}</p><dl><div><dt>Listing price</dt><dd>${formatMoney(item.price)}</dd></div><div><dt>Estimated shipping</dt><dd>${formatMoney(item.shipping_cost_myr || 0)}</dd></div><div><dt>Resale fee</dt><dd>${formatMoney(item.platform_fee_myr || 0)}</dd></div><div><dt>Total cost</dt><dd>${formatMoney(item.total_cost_myr)}</dd></div><div><dt>Estimated resale</dt><dd>${formatMoney(item.resale_estimate_myr)}</dd></div></dl><p class="insight-caveat">${escapeHtml(item.resale_confidence || 'Low')} pricing confidence. Asking-price estimates, not completed sales or authenticity verification.</p></details>`;
  return card;
}
function renderListingReview(item) {
  if (!item) return;
  const bubble = addChatMessage('Here’s the quick verdict.', 'assistant');
  bubble.classList.add('structured-message');
  bubble.appendChild(insightCard(item));
  scrollChatToEnd();
  return `${item.title}: ${item.is_profitable ? 'buy signal' : 'pass'}, ${item.risk_level} risk. ${item.reasoning}`;
}
function compareInWorkspace() {
  const snapshot = currentResponse;
  const selected = selectedListing();
  const offers = visibleOffers().filter((item) => !selected || item.group_id === selected.group_id).sort((a,b) => a.price - b.price).slice(0,5);
  const bubble = addChatMessage(selected ? 'Displayed offers in this comparison group' : 'Lowest asking prices on your board', 'assistant');
  if (!offers.length) { bubble.textContent = 'Run a search first to compare actual offers.'; return bubble.textContent; }
  const note = document.createElement('small'); note.className = 'comparison-caution'; note.textContent = 'Variant matching is provisional. These offers are not necessarily interchangeable.'; bubble.appendChild(note);
  offers.forEach((item) => {
    const row = document.createElement('button'); row.type = 'button'; row.className = 'workspace-offer'; row.innerHTML = listingIdentity(item);
    row.addEventListener('click', () => snapshot === currentResponse ? previewListing(item) : showToast('This comparison belongs to an earlier search.'));
    bubble.appendChild(row);
  });
  scrollChatToEnd();
  return `${offers.length} displayed offers compared by asking price. Variant matching is provisional.`;
}
function renderWorkspaceTools() {
  const selected = selectedListing();
  const offers = visibleOffers();
  const overview = $('#copilotOverview');
  overview.innerHTML = `<div class="welcome-orb" aria-hidden="true">✦</div><p class="workspace-kicker">YOUR SEARCH, IN CONTEXT</p><h3>${selected ? 'Let’s look closer.' : 'What’s your next move?'}</h3><p>${selected ? 'I have your selected item. Ask for a quick review or compare its offers.' : offers.length ? 'Compare offers, adjust your budget, or check the numbers. Your board is already connected.' : 'Find a product on the board, or tell me what you’re looking for.'}</p>`;
  overview.hidden = !!$('#copilotMessages .chat-turn');
  const tools = $('#copilotTools');
  tools.innerHTML = selected ? '<button type="button" data-workspace-action="review">Review item ↗</button><button type="button" data-workspace-action="compare">Compare offers ↗</button><button type="button" data-workspace-action="draft">Seller questions ↗</button>' : '<button type="button" data-workspace-action="compare">Compare offers ↗</button><button type="button" data-workspace-action="budget">Change budget ↗</button><button type="button" data-workspace-action="watch">Watch this ↗</button>';
  const menu = $('#copilotMenu');
  const menuActions = selected ? [['review','Review'],['compare','Compare'],['locate','Locate'],['draft','Seller draft'],['budget','Budget'],['watch','Watchlist']] : [['compare','Compare'],['budget','Budget'],['watch','Watchlist']];
  const icons = {review:'<circle cx="12" cy="12" r="8"/><path d="M12 10v6m0-9v1"/>',compare:'<path d="M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4"/>',locate:'<path d="M14 4h6v6m0-6L9 15M10 4H4v16h16v-6"/>',draft:'<path d="M14 3H5v18h14V8L14 3Zm0 0v5h5M8 12h8m-8 4h5"/>',budget:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 10h18m-6 5h3"/>',watch:'<path d="M6 3h12v18l-6-4-6 4V3Z"/>'};
  menu.innerHTML = menuActions.map(([action,label]) => `<button type="button" data-workspace-action="${action}" class="${['budget','watch'].includes(action) && selected ? 'action-secondary' : 'action-tile'}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">${icons[action]}</svg><span>${label}</span></button>`).join('');
  if (currentRequest?.source_mode === 'live' && currentResponse) {
    const refresh = document.createElement('select'); refresh.id = 'workspaceRefresh'; refresh.setAttribute('aria-label','Refresh a marketplace');
    refresh.innerHTML = '<option value="">↻ Refresh source…</option>' + (currentRequest.marketplaces || []).map((market) => `<option value="${market}">${marketplaceName(market)}</option>`).join('');
    refresh.disabled = operationBusy || chatBusy; menu.appendChild(refresh);
    refresh.addEventListener('change', () => {
      if (!refresh.value) return;
      const market = refresh.value;
      setChatDraft(`Refresh ${marketplaceName(market)} for this search`, {kind:'refresh', market});
      refresh.value = ''; setQuickActions(false);
    });
  }
  $$('button', tools).concat($$('button', menu)).forEach((button) => { button.disabled = operationBusy || chatBusy; });
}
function handleChatShortcut(event) {
  const action = event.target.closest('[data-workspace-action]')?.dataset.workspaceAction;
  if (!action || operationBusy || chatBusy) return;
  setQuickActions(false);
  if (action === 'review') setChatDraft('Explain this listing', {kind:'review'});
  if (action === 'compare') setChatDraft(selectedListing() ? 'Compare offers for this item' : 'Compare the offers on my board', {kind:'compare'});
  if (action === 'locate') setChatDraft('Show this item on my board', {kind:'locate'});
  if (action === 'budget') { $('#copilotBudget').hidden = false; $('#copilotBudgetValue').value = currentRequest?.max_purchase_price || $('#maxPrice').value; $('#copilotBudgetValue').focus(); }
  if (action === 'watch') setChatDraft('Save this search to my watchlist', {kind:'watch'});
  if (action === 'draft') setChatDraft('Draft questions for this seller', {kind:'draft'});
}
$('#copilotTools').addEventListener('click', handleChatShortcut);
$('#copilotMenu').addEventListener('click', handleChatShortcut);
function setQuickActions(open) {
  clearTimeout(quickActionsTimer);
  if ($('.copilot-context-shell').classList.contains('is-actions-open') !== open) followChatDuringLayout();
  $('.copilot-context-shell').classList.toggle('is-actions-open', open);
  $('#copilotQuickActions').setAttribute('aria-expanded', String(open));
  $('#copilotActionTray').setAttribute('aria-hidden', String(!open));
  $('#copilotActionTray').inert = !open;
}
const actionContext = $('.copilot-context-shell');
actionContext.addEventListener('pointerenter', (event) => {
  if (event.pointerType !== 'mouse' || !matchMedia('(hover: hover)').matches) return;
  clearTimeout(quickActionsTimer); quickActionsTimer = setTimeout(() => setQuickActions(true), 140);
});
actionContext.addEventListener('pointerleave', () => {
  clearTimeout(quickActionsTimer);
  if (!actionContext.contains(document.activeElement)) quickActionsTimer = setTimeout(() => setQuickActions(false), 220);
});
actionContext.addEventListener('focusout', (event) => {
  if (!actionContext.contains(event.relatedTarget)) setQuickActions(false);
});
$('#copilotQuickActions').addEventListener('click', () => setQuickActions($('#copilotQuickActions').getAttribute('aria-expanded') !== 'true'));
$('#cancelCopilotBudget').addEventListener('click', () => { $('#copilotBudget').hidden = true; });
$('#applyCopilotBudget').addEventListener('click', () => {
  const input = $('#copilotBudgetValue');
  if (!input.value || !input.reportValidity() || operationBusy) return;
  $('#copilotBudget').hidden = true;
  setChatDraft(`Search again with a maximum buy price of ${formatMoney(Number(input.value))}`, {kind:'budget', budget:Number(input.value)});
});

function sizeChatInput() {
  const input = $('#copilotInput'); input.style.height = 'auto'; input.style.height = `${Math.min(100, input.scrollHeight)}px`;
}
function setChatDraft(text, command) {
  $('#copilotInput').value = text;
  composerDraft = {text, response:currentResponse, offerId:selectedOfferId, ...command};
  sizeChatInput(); $('#copilotInput').focus();
  $('#copilotStatus').textContent = 'Message ready · edit it or press Send. Nothing sent yet.';
}
$('#copilotInput').addEventListener('input', () => { composerDraft = null; sizeChatInput(); });

function offerKey(item) { return item.offer_id || `${item.marketplace}:${item.listing_id}`; }
function chatContext() {
  const request = currentRequest || buildRequest();
  const fields = ['title', 'marketplace', 'price', 'resale_estimate_myr', 'estimated_profit_myr', 'estimated_margin_pct', 'total_cost_myr', 'platform_fee_myr', 'shipping_cost_myr', 'is_profitable', 'risk_level', 'reasoning', 'red_flags', 'variant_label', 'variant_kind', 'group_id', 'resale_confidence'];
  return { source_mode: currentResponse?.source_mode || request.source_mode, query: currentResponse?.query || request.query, max_purchase_price: request.max_purchase_price, marketplaces: request.marketplaces,
    selected_offer_id: selectedOfferId, source_errors: currentResponse?.source_errors || [], discarded_count: currentResponse?.discarded?.length || 0,
    visible_marketplaces:viewFilters.markets, visible_variant_kind:viewFilters.kind, view_max_price:viewFilters.maxPrice, visible_offer_ids:visibleOffers().map(offerKey), total_offer_count:currentResponse?.decisions.length || 0,
    offers: (currentResponse?.decisions || []).map((item) => ({offer_id: offerKey(item), ...Object.fromEntries(fields.filter((key) => item[key] != null).map((key) => [key, item[key]]))})) };
}
function updateChatContext() {
  const context = chatContext();
  $('#copilotContext').innerHTML = `<b>${escapeHtml(context.query || 'No search yet')}</b><small>${context.max_purchase_price ? `Buy ceiling ${formatMoney(context.max_purchase_price)} · ` : ''}${visibleOffers().length} visible of ${context.offers.length}${viewFilters.markets.length ? ` · ${viewFilters.markets.map(marketplaceName).join(' + ')}` : ''}${viewFilters.maxPrice ? ` · view ≤ ${formatMoney(viewFilters.maxPrice)}` : ''}${operationBusy ? ' · updating' : ''}</small>`;
  const selected = selectedListing();
  if (!selected) selectedOfferId = null;
  $('#copilotSelection').hidden = !selected;
  $('#selectedIdentity').innerHTML = selected ? `<button type="button" class="selected-product" aria-label="Preview selected listing">${listingIdentity(selected)}</button>` : '';
  $$('.deal-card').forEach((card) => card.classList.toggle('arbi-selected', !!selected && card.dataset.offerId === selectedOfferId));
  $('#copilotInput').placeholder = selected ? 'Ask about this item…' : 'Ask or change your search…';
  renderWorkspaceTools();
}
function openCopilot() {
  closeHistory();
  clearTimeout(closeChatTimer);
  const panel = $('#copilotPanel');
  if (panel.hidden || panel.classList.contains('is-closing')) panel.classList.add('is-opening');
  panel.classList.remove('is-closing'); panel.inert = false; panel.hidden = false;
  $('#copilotLauncher').setAttribute('aria-expanded', 'true');
  $('#copilotLauncher').tabIndex = -1;
  updateChatContext();
  setChatModal(panel.classList.contains('is-fullscreen'));
  clampChatPosition();
  $('#copilotInput').focus();
}
function closeCopilot() {
  const panel = $('#copilotPanel');
  if (panel.hidden) return;
  panel.classList.add('is-closing'); panel.inert = true;
  panel.classList.remove('is-opening');
  chatResizeAnimation?.cancel(); chatResizeAnimation = null; panel.classList.remove('is-resizing');
  setQuickActions(false);
  setChatModal(false);
  clearTimeout(closeChatTimer);
  closeChatTimer = setTimeout(() => { panel.hidden = true; panel.classList.remove('is-closing'); panel.inert = false; }, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 200);
  $('#copilotLauncher').setAttribute('aria-expanded', 'false');
  $('#copilotLauncher').tabIndex = 0;
  $('#copilotLauncher').focus();
}
function placeChat(x, y) {
  const panel = $('#copilotPanel');
  const rect = panel.getBoundingClientRect();
  const point = ArbiChatState.clampPosition(x, y, rect.width, rect.height, innerWidth, innerHeight);
  panel.style.setProperty('--chat-x', `${point.x}px`); panel.style.setProperty('--chat-y', `${point.y}px`);
  panel.classList.add('is-positioned');
}
function clampChatPosition() {
  const panel = $('#copilotPanel');
  if (panel.hidden || panel.classList.contains('is-resizing') || panel.classList.contains('is-fullscreen') || !panel.classList.contains('is-positioned')) return;
  const rect = panel.getBoundingClientRect(); placeChat(rect.left, rect.top);
}
function setChatModal(active) {
  $('#copilotPanel').setAttribute('aria-modal', String(active));
  document.body.classList.toggle('arbi-chat-expanded', active);
  if (active && !chatBackgroundState.length) {
    chatBackgroundState = $$('body > main, body > .topbar, body > footer').map((node) => ({node, inert:node.inert}));
    chatBackgroundState.forEach(({node}) => { node.inert = true; });
  } else if (!active) {
    chatBackgroundState.forEach(({node, inert}) => { node.inert = inert; }); chatBackgroundState = [];
  }
}
$('#fullscreenCopilot').addEventListener('click', () => {
  const panel = $('#copilotPanel');
  followChatDuringLayout();
  const before = panel.getBoundingClientRect(); const beforeRadius = getComputedStyle(panel).borderRadius;
  chatResizeAnimation?.cancel();
  panel.classList.remove('is-opening');
  panel.classList.add('is-resizing');
  const expanded = panel.classList.toggle('is-fullscreen');
  $('#fullscreenCopilot').setAttribute('aria-pressed', String(expanded));
  $('#fullscreenCopilot').setAttribute('aria-label', expanded ? 'Exit fullscreen chat' : 'Enter fullscreen chat');
  $('#fullscreenCopilot').title = expanded ? 'Restore floating chat' : 'Fullscreen';
  $('#copilotMove').disabled = expanded;
  setChatModal(expanded);
  const target = panel.getBoundingClientRect();
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { panel.classList.remove('is-resizing'); clampChatPosition(); return; }
  // Animate the actual window geometry, not a scaled screenshot of its contents.
  const frame = (rect, borderRadius) => ({left:`${rect.left}px`, top:`${rect.top}px`, width:`${rect.width}px`, height:`${rect.height}px`, right:'auto', bottom:'auto', borderRadius, transform:'none'});
  const animation = panel.animate([frame(before, beforeRadius), frame(target, getComputedStyle(panel).borderRadius)], {duration:520, easing:'cubic-bezier(.22,1,.36,1)'});
  chatResizeAnimation = animation;
  animation.onfinish = () => {
    if (chatResizeAnimation !== animation) return;
    chatResizeAnimation = null; panel.classList.remove('is-resizing'); clampChatPosition();
  };
});
$('#copilotPanel').addEventListener('animationend', (event) => {
  if (event.target === $('#copilotPanel') && event.animationName === 'arbi-reveal') $('#copilotPanel').classList.remove('is-opening');
});
const dragArea = $('#copilotDragArea');
dragArea.addEventListener('pointerdown', (event) => {
  const panel = $('#copilotPanel');
  if (event.button !== 0 || panel.classList.contains('is-fullscreen') || panel.classList.contains('is-resizing') || event.target.closest('.copilot-window-controls')) return;
  const rect = panel.getBoundingClientRect();
  dragState = {pointerId:event.pointerId, x:event.clientX, y:event.clientY, left:rect.left, top:rect.top};
  dragArea.setPointerCapture(event.pointerId); panel.classList.add('is-dragging');
  event.preventDefault();
});
dragArea.addEventListener('pointermove', (event) => {
  if (!dragState || dragState.pointerId !== event.pointerId) return;
  placeChat(dragState.left + event.clientX - dragState.x, dragState.top + event.clientY - dragState.y);
});
function endChatDrag() { dragState = null; $('#copilotPanel').classList.remove('is-dragging'); }
dragArea.addEventListener('pointerup', endChatDrag);
dragArea.addEventListener('pointercancel', endChatDrag);
dragArea.addEventListener('lostpointercapture', endChatDrag);
$('#copilotMove').addEventListener('keydown', (event) => {
  const directions = {ArrowLeft:[-1,0], ArrowRight:[1,0], ArrowUp:[0,-1], ArrowDown:[0,1]};
  const panel = $('#copilotPanel'); if (panel.classList.contains('is-fullscreen')) return;
  if (event.key === 'Home') { event.preventDefault(); panel.classList.remove('is-positioned'); return; }
  if (!directions[event.key]) return;
  event.preventDefault(); const rect = panel.getBoundingClientRect(); const step = event.shiftKey ? 40 : 16;
  placeChat(rect.left + directions[event.key][0] * step, rect.top + directions[event.key][1] * step);
});
window.addEventListener('resize', clampChatPosition);
$('#copilotLauncher').addEventListener('click', () => $('#copilotPanel').hidden ? openCopilot() : closeCopilot());
$('#closeCopilot').addEventListener('click', closeCopilot);
$('#copilotSelection button').addEventListener('click', () => { selectedOfferId = null; updateChatContext(); });
document.addEventListener('keydown', (event) => {
  if ($('#selectionDialog').open) return;
  const panel = $('#copilotPanel');
  if (event.key === 'Tab' && !panel.hidden && !panel.inert && panel.classList.contains('is-fullscreen')) {
    const nodes = $$('button:not(:disabled), textarea, input, select, summary', panel).filter((node) => node.getClientRects().length && !node.closest('[hidden], [inert]'));
    const first = nodes[0], last = nodes[nodes.length - 1];
    if (event.shiftKey && (document.activeElement === first || !panel.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || !panel.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
  }
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openCopilot(); }
  if (event.key === 'Escape' && !$('#copilotPanel').hidden) {
    if ($('#copilotQuickActions').getAttribute('aria-expanded') === 'true') { setQuickActions(false); $('#copilotQuickActions').focus(); }
    else closeCopilot();
  }
});
document.addEventListener('pointerdown', (event) => { if (!event.target.closest('.copilot-context-shell')) setQuickActions(false); });
$$('[data-chat-prompt]').forEach((button) => button.addEventListener('click', () => {
  setChatDraft(button.dataset.chatPrompt);
}));
$('#copilotInput').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('#copilotForm').requestSubmit(); }
});
let chatStickToEnd = true;
const chatLog = $('#copilotMessages');
chatLog.addEventListener('scroll', () => { if (!chatLayoutFollow) chatStickToEnd = chatLog.scrollHeight - chatLog.clientHeight - chatLog.scrollTop < 24; }, {passive:true});
new ResizeObserver(() => {
  if ((chatStickToEnd || chatLayoutFollow) && !$('#copilotPanel').hidden) chatLog.scrollTop = chatLog.scrollHeight;
}).observe(chatLog);
function followChatDuringLayout() {
  clearTimeout(chatLayoutTimer);
  chatLayoutFollow = chatStickToEnd || chatLog.scrollHeight - chatLog.clientHeight - chatLog.scrollTop < 24;
  chatLayoutTimer = setTimeout(() => {
    if (chatLayoutFollow) { chatLog.scrollTop = chatLog.scrollHeight; chatStickToEnd = true; }
    chatLayoutFollow = false;
  }, 560);
}
function scrollChatToEnd() {
  chatStickToEnd = true;
  requestAnimationFrame(() => { chatLog.scrollTop = chatLog.scrollHeight; });
}
function addChatMessage(text, role) {
  $('#copilotOverview').hidden = true;
  const turn = document.createElement('div'); turn.className = `chat-turn ${role}`;
  const avatar = document.createElement('span'); avatar.className = 'chat-avatar'; avatar.textContent = '✦'; avatar.setAttribute('aria-hidden','true');
  const content = document.createElement('div'); content.className = 'chat-turn-content';
  const meta = document.createElement('div'); meta.className = 'chat-turn-meta';
  const author = document.createElement('b'); author.textContent = role === 'user' ? 'You' : 'Arbi';
  const time = document.createElement('time'); time.dateTime = new Date().toISOString(); time.textContent = new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  meta.append(author, time);
  const message = document.createElement('div');
  message.arbiSnapshot = currentResponse;
  message.className = `chat-message ${role}`;
  message.textContent = text;
  const selected = selectedListing();
  if (role === 'user' && selected) {
    const scope = document.createElement('small'); scope.className = 'turn-context'; scope.textContent = `${marketplaceName(selected.marketplace)} · ${selected.title}`; message.prepend(scope);
  }
  content.append(meta, message); turn.append(avatar, content);
  $('#copilotMessages').appendChild(turn);
  scrollChatToEnd();
  return message;
}
function showChatTyping() {
  const typing = document.createElement('div'); typing.className = 'chat-turn assistant chat-typing'; typing.setAttribute('aria-hidden','true');
  typing.innerHTML = '<span class="chat-avatar">✦</span><div class="chat-turn-content"><div class="chat-turn-meta"><b>Arbi</b><span>Working on it</span></div><div class="chat-message"><i></i><i></i><i></i></div></div>';
  $('#copilotMessages').appendChild(typing); scrollChatToEnd(); return typing;
}
function rememberChatTurn(text, reply) {
  chatHistory.push({role:'user',content:text}, {role:'assistant',content:reply}); chatHistory = chatHistory.slice(-12);
}
async function runChatShortcut(draft) {
  const item = selectedListing();
  let reply;
  if (draft.kind === 'review') {
    reply = item ? renderListingReview(item) : 'Select a listing first using “Ask about this”.';
    if (!item) addChatMessage(reply, 'assistant');
  } else if (draft.kind === 'compare') reply = compareInWorkspace();
  else if (draft.kind === 'locate') {
    reply = item ? 'Highlighted your selected listing on the board.' : 'Select a listing first.';
    addChatMessage(reply, 'assistant'); if (item) focusListing(item);
  } else if (draft.kind === 'draft') {
    reply = item ? 'Here’s a message you can send to the seller:\n\nHi! Can you confirm the exact variant/size, condition, what is included and the delivered price? Please share clear photos of the product code/labels and any purchase receipt available. Thank you.\n\nDraft only — nothing has been sent to the seller.' : 'Select a listing first so the draft is attached to the right item.';
    addChatMessage(reply, 'assistant');
  } else if (draft.kind === 'watch') {
    reply = saveCurrentWatchlist() ? 'Search saved to your watchlist. Open History → Watchlists → Scan now to check again. Background monitoring is not running.' : 'Run a search first, then save it to your watchlist.';
    addChatMessage(reply, 'assistant');
  } else if (draft.kind === 'refresh') {
    const updated = await refreshMarketplace(draft.market, $(`[data-refresh-market="${draft.market}"]`));
    reply = updated ? `${marketplaceName(draft.market)} refreshed. Other marketplaces were retained and the comparisons recalculated.` : 'This source could not be refreshed. Check the status notice on the board.';
    addChatMessage(reply, 'assistant');
  } else if (draft.kind === 'budget') {
    const request = {...(currentRequest || buildRequest()), max_purchase_price:draft.budget};
    restoreForm(request, {}); const data = await executeSearch(request, {save:true});
    reply = data ? `${data.decisions.length} offers on your board within ${formatMoney(draft.budget)}.` : 'The search did not complete. See the search error on the board.';
    addChatMessage(reply, 'assistant');
  }
  return reply;
}
async function runSearchFromChat(action, bubble) {
  const base = currentRequest || buildRequest();
  const request = {...base, query:action.query, max_purchase_price:action.max_purchase_price, marketplaces:action.marketplaces, pricing_mode:action.pricing_mode || base.pricing_mode};
  if (request.pricing_mode === 'auto') request.resale_estimate = null;
  restoreForm(request, {});
  const state = document.createElement('div'); state.className = 'chat-search-state is-running';
  const label = document.createElement('strong'); label.textContent = 'Form filled · analysis running';
  const note = document.createElement('small'); note.textContent = `${request.source_mode === 'demo' ? 'Demo snapshot' : request.marketplaces.map(marketplaceName).join(' + ')} · ${request.max_purchase_price ? `under ${formatMoney(request.max_purchase_price)}` : 'no purchase ceiling'}`;
  state.append(label, note); bubble.appendChild(state); scrollChatToEnd();
  $('#copilotStatus').textContent = 'Running the analysis from your message…';
  bubble.arbiSnapshot = null;
  const data = await executeSearch(request, {save:true});
  state.classList.remove('is-running');
  label.textContent = data ? `${data.decisions.length} offers analyzed · ${data.decisions.filter((item) => item.is_profitable).length} buy signals` : 'Search could not complete';
  note.textContent = data ? `${data.source_errors?.length ? `${data.source_errors.length} source issues · ` : ''}${request.source_mode === 'demo' ? 'Demo results, not live market data.' : 'Results are ready on your board.'}` : $('#errorText').textContent || 'Check the search error on your board.';
  bubble.arbiSnapshot = data;
  if (data) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'chat-action'; button.textContent = 'Show results on my board ↗';
    button.addEventListener('click', () => {
      if (data !== currentResponse) { showToast('Those results belong to an earlier search.'); return; }
      closeCopilot(); resultsSection.scrollIntoView({behavior:'smooth', block:'start'});
    }); state.appendChild(button);
  }
  $('#copilotStatus').textContent = data ? 'Analysis complete · started from your message' : 'Search failed · details are shown above';
  scrollChatToEnd(); return data;
}
function markEarlierMessages(data) {
  $$('#copilotMessages .chat-message').forEach((message) => {
    if (!message.arbiSnapshot || message.arbiSnapshot === data || message.classList.contains('stale-message')) return;
    message.classList.add('stale-message');
    const label = document.createElement('small'); label.className = 'earlier-board'; label.textContent = 'Earlier board · read-only';
    message.prepend(label);
    $$('button', message).forEach((button) => { button.disabled = true; });
  });
}
$('#copilotForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (chatBusy || operationBusy) { showToast('Please wait for the current operation to finish.'); return; }
  const text = $('#copilotInput').value.trim();
  if (!text) return;
  if (!ArbiChatState.draftMatches(composerDraft, text, currentResponse, selectedOfferId)) {
    $('#copilotStatus').textContent = 'Your board or selected item changed. Choose the shortcut again, or edit this message.';
    $('#copilotInput').focus(); return;
  }
  const draft = composerDraft; composerDraft = null;
  chatBusy = true;
  $('#copilotSend').disabled = true;
  $('#copilotInput').value = '';
  sizeChatInput(); renderWorkspaceTools();
  const userBubble = addChatMessage(text, 'user');
  const context = chatContext();
  const contextResponse = currentResponse;
  const contextRequest = currentRequest;
  const contextViewRevision = viewRevision;
  $('#copilotStatus').textContent = 'Reading your search context…';
  const typing = showChatTyping();
  try {
    if (draft?.kind) {
      await new Promise((resolve) => setTimeout(resolve, 260));
      // The selection may change during the entry animation; never run an old shortcut.
      if (!ArbiChatState.draftMatches(draft, text, currentResponse, selectedOfferId)) {
        typing.remove();
        const reply = 'Your board or selected item changed. Please choose the shortcut again.';
        addChatMessage(reply, 'assistant'); rememberChatTurn(text, reply); return;
      }
      typing.remove();
      const reply = await runChatShortcut(draft);
      rememberChatTurn(text, reply);
      $('#copilotStatus').textContent = 'Workspace action · uses your actual board data';
      return;
    }
    const response = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:text, history:chatHistory.slice(-12), context})});
    if (!response.ok) throw new Error('Chat is unavailable. Please try again.');
    const answer = await response.json();
    typing.remove();
    const explainedOffer = answer.view === 'explain' && contextResponse?.decisions.find((item) => offerKey(item) === answer.offer_ids?.[0]);
    const bubble = addChatMessage(explainedOffer ? 'Here’s the breakdown for that item.' : answer.reply, 'assistant');
    bubble.arbiSnapshot = contextResponse;
    if (explainedOffer) { bubble.classList.add('structured-message'); bubble.appendChild(insightCard(explainedOffer, contextResponse)); }
    rememberChatTurn(text, answer.reply);
    (answer.offer_ids || []).forEach((id) => {
      if (explainedOffer) return;
      const offer = contextResponse?.decisions.find((item) => offerKey(item) === id);
      if (!offer) return;
      const ref = document.createElement('button');
      ref.className = 'chat-offer'; ref.type = 'button';
      ref.textContent = `${marketplaceName(offer.marketplace)} · ${formatMoney(offer.price)}\n${offer.title}`;
      ref.addEventListener('click', () => {
        if (currentResponse !== contextResponse) { showToast('This reply refers to an earlier search.'); return; }
        previewListing(offer);
      });
      bubble.appendChild(ref);
    });
    if (answer.action?.type === 'filter') {
      if (currentResponse === contextResponse && currentRequest === contextRequest && viewRevision === contextViewRevision) {
        const action = answer.action;
        applyViewFilters(action.reset ? {markets:[],kind:'',maxPrice:null} : {markets:action.marketplaces || [],kind:action.variant_kind || '',maxPrice:action.max_price ?? null});
      } else bubble.appendChild(document.createTextNode('\nYour board changed while I read this. Ask again to apply the filter.'));
    } else if (answer.action?.type === 'search' && answer.auto_execute) {
      if (currentRequest !== contextRequest || currentResponse !== contextResponse) {
        addChatMessage('The board changed while I read your message. Send your search request again so I don’t overwrite the newer search.', 'assistant');
        return;
      }
      $('.turn-context', userBubble)?.remove(); userBubble.arbiSnapshot = null;
      await runSearchFromChat(answer.action, bubble);
      markEarlierMessages(currentResponse);
      return;
    }
    if (answer.action && answer.action.type !== 'filter') {
      const action = answer.action;
      const button = document.createElement('button'); button.type = 'button'; button.className = 'chat-action'; button.textContent = `${action.label} ↗`;
      button.addEventListener('click', async () => {
        if (operationBusy || chatBusy) { showToast('Wait for the current operation to finish.'); return; }
        if (currentRequest !== contextRequest || currentResponse !== contextResponse) { button.disabled = true; showToast('Search changed. Ask Arbi for an updated action.'); return; }
        button.disabled = true;
        const actionTurn = addChatMessage(action.label, 'user');
        if (action.type === 'search') { $('.turn-context', actionTurn)?.remove(); actionTurn.arbiSnapshot = null; }
        if (action.type === 'search') {
          const reply = addChatMessage(`Running the search for ${action.query}.`, 'assistant');
          await runSearchFromChat(action, reply);
        } else if (action.type === 'refresh') {
          if (currentRequest?.source_mode !== 'live') { addChatMessage('Source refresh is only available for a live search.', 'assistant'); return; }
          const statuses = [];
          for (const market of action.marketplaces) {
            const updated = await refreshMarketplace(market, $(`[data-refresh-market="${market}"]`));
            statuses.push(`${marketplaceName(market)}: ${updated ? 'refreshed' : 'not refreshed'}`);
          }
          addChatMessage(statuses.join('\n'), 'assistant');
        } else if (action.type === 'watch') { addChatMessage(saveCurrentWatchlist() ? 'Search saved to your watchlist. Background monitoring is not running.' : 'Run a search first to save it.', 'assistant'); }
        updateChatContext();
      });
      bubble.appendChild(button);
    }
    markEarlierMessages(currentResponse);
    $('#copilotStatus').textContent = answer.ai_status?.message || (answer.mode === 'ai' ? 'AI assisted · grounded in the displayed results' : 'Local workspace commands · AI connection unverified');
  } catch (error) { typing.remove(); addChatMessage(error.message, 'assistant'); $('#copilotStatus').textContent = 'The operation did not complete. Check the board for its current state.'; }
  finally { typing.remove(); chatBusy = false; $('#copilotSend').disabled = false; renderWorkspaceTools(); }
});

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
$('#marketFilters').addEventListener('click', (event) => {
  const button = event.target.closest('[data-filter-market]');
  if (!button || operationBusy) return;
  const market = button.dataset.filterMarket;
  const markets = market === 'all' ? [] : viewFilters.markets.includes(market) ? viewFilters.markets.filter((item) => item !== market) : [...viewFilters.markets,market];
  applyViewFilters({markets}); $(`[data-filter-market="${market}"]`)?.focus({preventScroll:true});
});
$('#variantFilter').addEventListener('change', (event) => applyViewFilters({kind:event.target.value}));
$('#viewMaxPrice').addEventListener('change', (event) => {
  if (!event.target.reportValidity()) return;
  applyViewFilters({maxPrice:event.target.value ? Number(event.target.value) : null});
});
$('#resetFilters').addEventListener('click',() => applyViewFilters({markets:[],kind:'',maxPrice:null}));
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
    match_mode: $('#matchMode').value,
    pricing_mode: pricingMode,
    resale_estimate: pricingMode === 'manual' ? Number($('#resale').value) : null,
    max_purchase_price: $('#maxPrice').value ? Number($('#maxPrice').value) : null,
    source_mode: $('input[name="sourceMode"]:checked').value,
    marketplaces: $$('input[name="marketplace"]:checked').map((input) => input.value),
  };
}

async function executeSearch(request, options = {}) {
  if (operationBusy) return null;
  operationBusy = true;
  selectedOfferId = null;
  currentRequest = request;
  currentResponse = null;
  viewFilters = {markets:[],kind:'',maxPrice:null}; viewRevision++;
  updateChatContext();
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
    setLoading(false);
    operationBusy = false;
    updateChatContext();
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
    $('#systemState span:last-child').textContent = `${health.ai_mode === 'gemini' ? 'AI configured' : 'Deterministic mode'}${shopee}${version}`;
    $('#copilotStatus').textContent = health.ai_status?.message || 'AI connection unverified · local workspace commands available';
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
  markEarlierMessages(data);
  summary.hidden = false;
  resultsSection.hidden = false;
  renderFilterControls(data);
  renderBoardView();
  renderDiscarded(data.discarded || []);
  renderSourceWarnings(data.source_errors || []);
  updateChatContext();
  summary.scrollIntoView({ behavior: options.instant ? 'auto' : 'smooth', block: 'start' });
}

function applyViewFilters(changes) {
  viewFilters = {...viewFilters,...changes}; viewRevision++;
  if (!visibleOffers().some((item) => offerKey(item) === selectedOfferId)) selectedOfferId = null;
  // Generated shortcuts must be regenerated against the changed visible board.
  if (composerDraft) composerDraft = {...composerDraft,response:null};
  renderFilterControls(currentResponse);
  renderBoardView(); updateChatContext();
}

function renderFilterControls(data) {
  if (!data) return;
  const offers = data.decisions || [];
  const facetOffers = ArbiChatState.filterOffers(offers,{...viewFilters,markets:[]});
  const bar = $('#marketFilters'); bar.replaceChildren();
  const markets = ['carousell','lazada','mudah','shopee'];
  ['all',...markets].forEach((market) => {
    const button = document.createElement('button'); button.type = 'button'; button.dataset.filterMarket = market;
    const selected = market === 'all' ? !viewFilters.markets.length : viewFilters.markets.includes(market);
    button.className = `filter-chip${selected ? ' active' : ''} ${market === 'all' ? '' : `market-${market}`}`;
    button.setAttribute('aria-pressed',String(selected));
    if (market !== 'all' && !data.marketplaces?.includes(market)) button.title = `${marketplaceName(market)} was not searched in this snapshot; this filter does not crawl it.`;
    const count = market === 'all' ? facetOffers.length : facetOffers.filter((item) => item.marketplace === market).length;
    button.innerHTML = `${market === 'all' ? '<span class="filter-all-icon">◎</span>' : `<span class="filter-market-icon"><img src="${marketplaceLogo(market)}" alt=""></span>`}<span>${market === 'all' ? 'All markets' : marketplaceName(market)}</span><b>${count}</b>`;
    bar.appendChild(button);
  });
  const types = new Map();
  const labels = {building_set:'Building sets / main models',small_model:'Small-scale models',minifigure:'Minifigures only',accessory:'Accessories',incomplete:'Incomplete sets / parts',compatible:'Compatible / third-party',full_set:'Full collectible sets',single:'Single / confirmed items',blind_box:'Sealed blind boxes',unclear:'Unconfirmed variants'};
  offers.forEach((offer) => { if (!types.has(offer.variant_kind)) types.set(offer.variant_kind,labels[offer.variant_kind] || 'Unclassified'); });
  const select = $('#variantFilter'); select.replaceChildren(new Option('All product types',''));
  types.forEach((label,kind) => select.add(new Option(label,kind)));
  select.value = viewFilters.kind;
  $('#viewMaxPrice').value = viewFilters.maxPrice ?? '';
  $('#resetFilters').disabled = !viewFilters.markets.length && !viewFilters.kind && viewFilters.maxPrice == null;
}

function renderBoardView() {
  const data = currentResponse;
  if (!data) return;
  const decisions = visibleOffers();
  const buys = decisions.filter((item) => item.is_profitable);
  const groups = ArbiChatState.filterGroups(normalizedGroups(data),decisions);
  const bestProfit = buys.length ? Math.max(...buys.map((item) => item.estimated_profit_myr)) : null;
  $('#totalMetric').textContent = data.total_scraped;
  $('#keptMetric').textContent = decisions.length;
  $('#buyMetric').textContent = buys.length;
  $('#profitMetric').textContent = bestProfit === null ? '—' : formatMoney(bestProfit);
  $('#resultsTitle').textContent = `${data.query} · ${decisions.length} visible offer${decisions.length === 1 ? '' : 's'}`;
  $('#filterStatus').textContent = `${decisions.length} of ${data.decisions.length} saved offers · ${groups.length} group${groups.length === 1 ? '' : 's'}`;
  $('#resultsExplanation').textContent = `${!data.matching_version ? 'Older snapshot: rerun this search for updated product matching. ' : ''}${data.match_mode === 'related' ? 'Related variants are included, with separate valuations. ' : 'Exact-product checks enabled. '}Visible price ranges follow your filters; resale estimates retain the original comparison evidence. Title matching is provisional, not authenticity verification. Asking prices are not completed sales.`;
  const countText = Object.entries(data.source_counts || {}).map(([name, count]) => `${marketplaceName(name)} ${count}`).join(' · ');
  $('#resultsMeta').textContent = `${countText || providerLabel(data.provider)} · ${data.pricing_mode === 'auto' ? 'market-priced' : 'manual resale'} · ${data.ai_mode === 'gemini' ? 'AI configured · rules decide' : 'rules verified'}`;
  renderSourceBar(data);
  results.replaceChildren();
  if (!decisions.length && data.decisions.length) {
    const empty = document.createElement('div'); empty.className = 'empty-state';
    empty.innerHTML = '<span>◎</span><h3>No saved offers match these filters.</h3><p>Your other results are still here. Reset the filters to see them.</p><button type="button" class="watch-button">Reset filters</button>';
    $('button',empty).addEventListener('click',() => applyViewFilters({markets:[],kind:'',maxPrice:null})); results.appendChild(empty);
  } else if (!decisions.length) results.appendChild(emptyState(data.total_scraped));
  else groups.forEach((group, index) => results.appendChild(renderComparisonGroup(group, index)));
}

function renderComparisonGroup(group, index) {
  const section = document.createElement('section');
  section.className = `comparison-group${group.offers.length === 1 ? ' is-single' : ''}`;
  section.style.setProperty('--delay', `${Math.min(index * 80, 400)}ms`);
  const marketNames = group.marketplaces.map(marketplaceName).join(' + ');
  const prices = group.offers.map((item) => Number(item.price));
  const low = Math.min(...prices), high = Math.max(...prices);
  const budget = viewFilters.maxPrice ?? currentRequest?.max_purchase_price;
  section.innerHTML = `
    <header class="comparison-header">
      <div><p><span class="live-pulse"></span> COMPARISON GROUP</p><h3>${escapeHtml(shorten(group.name, 88))}</h3><div class="variant-row"><b>${escapeHtml(group.variant_label)}</b>${group.variant_warning ? `<span>${escapeHtml(group.variant_warning)}</span>` : ''}</div></div>
      <div class="market-range"><small>${group.offers.length} OFFER${group.offers.length === 1 ? '' : 'S'} · ${escapeHtml(marketNames)}</small><strong>${low === high ? formatMoney(low) : `${formatMoney(low)}—${formatMoney(high)}`}</strong><span>Visible asks${budget ? ` · within ${formatMoney(budget)}` : ''}</span></div>
    </header>
    <div class="group-offers"></div>`;
  const offerGrid = $('.group-offers', section);
  group.offers.forEach((offer, offerIndex) => offerGrid.appendChild(renderCard(offer, offerIndex)));
  return section;
}

function renderCard(item, index) {
  const card = document.createElement('article');
  card.dataset.offerId = offerKey(item);
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
        <div><small>EST. RESALE</small><strong>${formatMoney(item.resale_estimate_myr ?? 0)}</strong><span>${formatMoney(item.resale_low_myr ?? 0)}–${formatMoney(item.resale_high_myr ?? 0)}</span></div>
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
      <button class="ask-listing" type="button">✦ Ask about this</button>
    </div>`;
  const productImage = $('.deal-image > img', card);
  $('.ask-listing', card).addEventListener('click', () => {
    previewListing(item);
  });
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
    const shown = visibleOffers().filter((item) => item.marketplace === market).length;
    const chip = document.createElement('div');
    chip.className = `source-chip market-${market}${failed ? ' failed' : ''}`;
    chip.innerHTML = `<img src="${marketplaceLogo(market)}" alt=""><span><b>${marketplaceName(market)}</b><small>${failed ? 'source unavailable' : `${count} collected · ${shown} shown · ${freshness(data.source_times?.[market] || data.collected_at)}`}</small></span>${data.source_mode === 'live' ? `<button type="button" data-refresh-market="${market}" aria-label="Refresh ${marketplaceName(market)}">↻</button>` : ''}`;
    bar.appendChild(chip);
  });
}

async function refreshMarketplace(market, button) {
  if (operationBusy || !currentResponse || currentRequest?.source_mode !== 'live') return;
  if (!currentResponse.market_listings) {
    showToast('This older snapshot needs a full search before individual sources can refresh.');
    return;
  }
  operationBusy = true;
  startBtn.disabled = true;
  updateChatContext();
  $$('[data-refresh-market]').forEach((item) => { item.disabled = true; });
  button?.classList.add('spinning');
  const previous = currentResponse;
  const sourceTimes = Object.fromEntries((previous.marketplaces || []).map((source) => [source, previous.source_times?.[source] || previous.collected_at]));
  showToast(`Refreshing ${marketplaceName(market)} only…`);
  try {
    const fresh = await fetchSearch({ ...currentRequest, marketplaces: [market], retained_market_listings: previous.market_listings.filter((item) => item.marketplace !== market), retained_source_times: sourceTimes });
    const sourceCounts = { ...(previous.source_counts || {}), [market]: fresh.source_counts?.[market] ?? 0 };
    currentResponse = {
      ...fresh,
      marketplaces: currentRequest.marketplaces,
      source_times: { ...sourceTimes, [market]: fresh.collected_at },
      source_counts: sourceCounts,
      source_errors: [ ...(previous.source_errors || []).filter((item) => item.marketplace !== market), ...(fresh.source_errors || []) ],
      total_scraped: Object.values(sourceCounts).reduce((sum, count) => sum + Number(count || 0), 0),
    };
    renderResponse(currentResponse, { instant: true });
    saveHistory(currentRequest, currentResponse);
    showToast(`${marketplaceName(market)} refreshed — all comparisons recalculated`);
    return true;
  } catch (error) {
    showToast(`${marketplaceName(market)} refresh failed: ${error.message}`);
    return false;
  } finally {
    operationBusy = false;
    startBtn.disabled = false;
    $$('[data-refresh-market]').forEach((item) => { item.disabled = false; });
    button?.classList.remove('spinning');
    updateChatContext();
  }
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
  if (operationBusy) return;
  const entry = getHistory().find((item) => item.id === id);
  if (!entry?.response) return;
  restoreForm(entry.request || {}, entry.response);
  currentRequest = entry.request;
  viewFilters = {markets:[],kind:'',maxPrice:null}; viewRevision++;
  selectedOfferId = null;
  currentResponse = entry.response;
  clearOutput();
  renderResponse(entry.response, { instant: true });
  closeHistory();
  showToast('Loaded saved result — no rerun needed');
}

function saveCurrentWatchlist() {
  if (!currentRequest || !currentResponse) {
    showToast('Run a search first, then save it');
    return false;
  }
  if (currentRequest.source_mode !== 'live') {
    showToast('Watchlists use live market searches — switch to Live market first');
    return false;
  }
  const signature = JSON.stringify({ query: currentRequest.query.toLowerCase(), max: currentRequest.max_purchase_price, marketplaces: currentRequest.marketplaces });
  const decisions = currentResponse.decisions || [];
  const bestPrice = decisions.length ? Math.min(...decisions.map((item) => item.price)) : null;
  const item = { id: `${Date.now()}`, signature, created_at: new Date().toISOString(), last_checked_at: new Date().toISOString(), request: currentRequest, best_price: bestPrice, buy_count: decisions.filter((offer) => offer.is_profitable).length };
  const next = [item, ...getWatchlists().filter((watch) => watch.signature !== signature)];
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next));
  renderWatchlists();
  showToast('Watchlist saved — use Scan now to check the market');
  return true;
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
  $('#matchMode').value = request.match_mode || response.match_mode || 'exact';
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
  setChatModal(false);
  $('#copilotPanel').hidden = true;
  $('#copilotLauncher').setAttribute('aria-expanded', 'false');
  $('#copilotLauncher').tabIndex = 0;
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
