/* Small shared invariants for movable chat and context-bound shortcut drafts. */
(function (root) {
  const state = {
    analysisStatus(data = {}) {
      const status = data.ai_status || {};
      const labels = {connected:'Gemini reviewed', partial:'AI review partial', skipped:'AI review skipped',
        not_configured:'Gemini not configured', invalid_request:'AI request rejected', access_denied:'Gemini access denied',
        rate_limited:'AI rate-limited', budget_limited:'Local AI budget reached', timeout:'AI timed out',
        unavailable:'AI unavailable', invalid_response:'AI response rejected', output_truncated:'AI output incomplete'};
      const attempts = data.agent_run?.provider_attempts;
      const tokens = data.agent_run?.token_usage?.total_token_count;
      const usage = Number.isFinite(attempts) ? `${attempts} Gemini attempt${attempts === 1 ? '' : 's'}${Number.isFinite(tokens) ? ` · ${tokens.toLocaleString()} reported tokens` : ' · tokens not reported'}` : '';
      return {
        label: (labels[status.state] || 'Saved AI status unverified') + (status.code ? ` (${status.code})` : ''),
        message: [status.message || 'This saved result has no current AI execution status; rerun to verify.', ...(status.configuration_warnings || [])].join(' '),
        usage,
      };
    },
    filterOffers(offers, filters = {}) {
      return offers.filter((offer) => (!filters.markets?.length || filters.markets.includes(offer.marketplace))
        && (!filters.kind || filters.kind === offer.variant_kind)
        && (filters.maxPrice == null || Number(offer.price) <= filters.maxPrice));
    },
    filterGroups(groups, offers) {
      const visibleIds = new Set(offers.map((item) => item.offer_id || `${item.marketplace}:${item.listing_id}`));
      return groups.map((group) => {
        const visible = group.offers.filter((item) => visibleIds.has(item.offer_id || `${item.marketplace}:${item.listing_id}`));
        const name = visible.some((item) => item.title === group.name) ? group.name : visible[0]?.title || group.name;
        return {...group, name, offers:visible, marketplaces:[...new Set(visible.map((item) => item.marketplace))], offer_count:visible.length};
      }).filter((group) => group.offers.length);
    },
    clampPosition(x, y, width, height, viewportWidth, viewportHeight, inset = 12) {
      return {
        x: Math.max(inset, Math.min(x, Math.max(inset, viewportWidth - width - inset))),
        y: Math.max(inset, Math.min(y, Math.max(inset, viewportHeight - height - inset))),
      };
    },
    draftMatches(draft, text, response, offerId) {
      return !draft || (draft.text === text && draft.response === response && draft.offerId === offerId);
    },
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = state;
  else root.ArbiChatState = state;
})(typeof globalThis !== 'undefined' ? globalThis : this);
