/* Small shared invariants for movable chat and context-bound shortcut drafts. */
(function (root) {
  const state = {
    filterOffers(offers, filters = {}) {
      return offers.filter((offer) => (!filters.markets?.length || filters.markets.includes(offer.marketplace))
        && (!filters.kind || filters.kind === offer.variant_kind)
        && (filters.maxPrice == null || Number(offer.price) <= filters.maxPrice));
    },
    filterGroups(groups, offers) {
      const visibleIds = new Set(offers.map((item) => item.offer_id || `${item.marketplace}:${item.listing_id}`));
      return groups.map((group) => {
        const visible = group.offers.filter((item) => visibleIds.has(item.offer_id || `${item.marketplace}:${item.listing_id}`));
        return {...group, offers:visible, marketplaces:[...new Set(visible.map((item) => item.marketplace))], offer_count:visible.length};
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
