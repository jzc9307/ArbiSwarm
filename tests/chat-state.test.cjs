const {test} = require('node:test');
const assert = require('node:assert/strict');
const {clampPosition, draftMatches, filterOffers, filterGroups} = require('../static/chat-state.js');

const savedOffers = [
  {offer_id:'a', marketplace:'carousell',price:200,variant_kind:'building_set',resale_estimate_myr:300},
  {offer_id:'b', marketplace:'shopee',price:250,variant_kind:'building_set',resale_estimate_myr:300},
  {offer_id:'c', marketplace:'shopee',price:50,variant_kind:'accessory',resale_estimate_myr:60},
];
test('marketplace and price facets narrow saved records without mutating valuations', () => {
  const filtered = filterOffers(savedOffers,{markets:['shopee'],maxPrice:250,kind:'building_set'});
  assert.deepEqual(filtered.map(item => item.offer_id),['b']);
  assert.equal(filtered[0],savedOffers[1]);
  assert.equal(filtered[0].resale_estimate_myr,300);
  assert.equal(savedOffers.length,3);
  assert.equal(filterOffers(savedOffers,{}).length,3);
});
test('filtered groups drop empty groups and recompute marketplace/count labels', () => {
  const groups = [{group_id:'set',offers:savedOffers.slice(0,2)}, {group_id:'accessory',offers:savedOffers.slice(2)}];
  const filtered = filterGroups(groups,filterOffers(savedOffers,{markets:['carousell']}));
  assert.equal(filtered.length,1);
  assert.equal(filtered[0].offer_count,1);
  assert.deepEqual(filtered[0].marketplaces,['carousell']);
  assert.deepEqual(filterGroups(groups,[]),[]);
  assert.equal(groups[0].offers.length,2);
});

test('drag position keeps every edge inside the viewport', () => {
  assert.deepEqual(clampPosition(-100, -20, 468, 760, 1440, 900), {x:12,y:12});
  assert.deepEqual(clampPosition(9999, 9999, 468, 760, 1440, 900), {x:960,y:128});
  assert.deepEqual(clampPosition(500, 60, 468, 760, 1440, 900), {x:500,y:60});
});
test('resize clamps a floating panel on a narrow screen', () => {
  assert.deepEqual(clampPosition(800, 80, 366, 720, 390, 844), {x:12,y:80});
  assert.deepEqual(clampPosition(800, 80, 366, 720, 390, 500), {x:12,y:12});
});
test('a shortcut is valid only for its original board, selection and text', () => {
  const board = {}; const draft = {text:'Explain this listing', response:board, offerId:'carousell:1'};
  assert.equal(draftMatches(draft, draft.text, board, draft.offerId), true);
  assert.equal(draftMatches(draft, draft.text, {}, draft.offerId), false);
  assert.equal(draftMatches(draft, draft.text, board, 'shopee:2'), false);
  assert.equal(draftMatches(draft, draft.text, board, null), false);
  assert.equal(draftMatches(draft, 'New question', board, draft.offerId), false);
  assert.equal(draftMatches(null, 'A typed question', board, null), true);
});
