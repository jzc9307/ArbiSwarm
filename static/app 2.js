const startBtn = document.getElementById('startBtn');
const btnLabel = startBtn.querySelector('.btn-label');
const btnSpinner = startBtn.querySelector('.btn-spinner');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');

startBtn.addEventListener('click', async () => {
  const query = document.getElementById('query').value.trim();
  const resale_estimate = parseFloat(document.getElementById('resale').value);
  const use_live = document.getElementById('useLive').checked;

  if (!query) {
    setStatus('Enter an item to search for first.', true);
    return;
  }

  resultsEl.innerHTML = '';
  setStatus('Swarm running — this can take a moment (one LLM pass per listing).');
  setLoading(true);

  try {
    const res = await fetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, resale_estimate, use_live }),
    });

    if (!res.ok) {
      let message = `Server error ${res.status}`;
      try {
        const errBody = await res.json();
        if (errBody.detail) message = errBody.detail;
      } catch (_) {}
      throw new Error(message);
    }

    const data = await res.json();

    let statusText = `Kept ${data.kept_after_filter} of ${data.total_scraped} listings after the hard-filter.`;
    if (!use_live) {
      statusText += ' (Using cached demo data — unrelated to your search term. Turn on Live scrape to search for what you typed.)';
    } else if (data.used_fallback_cache) {
      statusText += ' Live scrape returned nothing — showing cached demo data instead.';
    }
    setStatus(statusText);

    if (data.decisions.length === 0) {
      resultsEl.innerHTML = '<p class="empty-state">Nothing survived the hard-filter. Try a different search term.</p>';
    } else {
      data.decisions.forEach((d, i) => resultsEl.appendChild(renderCard(d, i)));
    }
  } catch (err) {
    setStatus(`${err.message}`, true);
  } finally {
    setLoading(false);
  }
});

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.className = 'status' + (isError ? ' error' : '');
}

function setLoading(isLoading) {
  startBtn.disabled = isLoading;
  btnLabel.textContent = isLoading ? 'Thinking…' : 'Start swarm';
  btnSpinner.hidden = !isLoading;
}

function renderCard(d, index) {
  const card = document.createElement('div');
  card.className = 'card ' + (d.is_profitable ? 'profitable' : 'pass');
  card.style.animationDelay = `${index * 70}ms`;

  card.innerHTML = `
    <h3>${escapeHtml(d.title)}</h3>
    <p class="meta">
      <span><strong>RM${d.price}</strong></span>
      <span>Margin <strong>${d.estimated_margin_pct}%</strong></span>
      <span class="${d.is_profitable ? 'badge yes' : 'badge no'}">${d.is_profitable ? 'Profitable' : 'Pass'}</span>
    </p>
    <p class="reasoning"><strong>Reasoning</strong> — ${escapeHtml(d.reasoning)}</p>
    ${d.negotiation_message ? `
      <div class="negotiation" data-message="${escapeHtml(d.negotiation_message)}">
        ${escapeHtml(d.negotiation_message)}
        <button class="copy-btn" type="button">Copy</button>
      </div>
    ` : ''}
    <a class="listing-link" href="${d.url}" target="_blank" rel="noopener">View listing →</a>
  `;

  const copyBtn = card.querySelector('.copy-btn');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      const msg = copyBtn.parentElement.dataset.message;
      navigator.clipboard.writeText(msg).then(() => {
        const original = copyBtn.textContent;
        copyBtn.textContent = 'Copied';
        setTimeout(() => { copyBtn.textContent = original; }, 1400);
      });
    });
  }

  return card;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}