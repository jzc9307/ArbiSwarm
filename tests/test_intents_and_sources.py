"""No live credentials: intent, key-pool and official-adapter regressions."""
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai.errors import ClientError
from pydantic import BaseModel, ValidationError

import api
import config
import copilot
import international_markets as international
import marketplaces
from agents import _llm
from filters import hard_filter
from intelligence import profile_variant
from search_intent import AliasGroup, SearchIntent, plan_search, query_variants
from tests.test_core import listing


class IntentTests(unittest.TestCase):
    def test_seasons_and_jersey_aliases_match_both_queries(self):
        row = listing(title='Liverpool football shirt 1997/1998')
        for query in ['Liverpool jersey 97/98', 'Liverpool 97/98', 'LFC shirt 1997/98']:
            kept, _ = hard_filter([row], query=query)
            self.assertEqual(len(kept), 1, query)
        self.assertEqual(profile_variant(row.title).season, '97/98')

    def test_wrong_season_cannot_hide_in_description(self):
        row = listing(title='Liverpool jersey 1998/1999', description='Also available 97/98')
        self.assertEqual(hard_filter([row], query='Liverpool 97/98')[0], [])

    def test_non_jersey_fallback_concepts(self):
        cases = [('IKEA sofa', 'IKEA couch'), ('Samsung television', 'Samsung TV'),
            ('Nintendo controller', 'Nintendo gamepad'), ('Sony headphones', 'Sony headset')]
        for query, title in cases:
            kept, _ = hard_filter([listing(title=title)], query=query)
            self.assertEqual(len(kept), 1, query)

    def test_model_punctuation_is_not_identity(self):
        kept, _ = hard_filter([listing(title='Sony WH1000XM5 headphones')], query='Sony WH-1000XM5 headset')
        self.assertEqual(len(kept), 1)

    def test_single_digit_generations_are_not_discarded(self):
        rows = [listing(id='right', title='Apple AirPods Pro 2'), listing(id='wrong', title='Apple AirPods Pro 1')]
        kept, _ = hard_filter(rows, query='Apple AirPods Pro 2')
        self.assertEqual([item.id for item in kept], ['right'])

    def test_size_word_is_not_required_but_actual_size_is(self):
        rows = [listing(id='right', title='Liverpool shirt 97/98 M'), listing(id='wrong', title='Liverpool shirt 97/98 L')]
        kept, _ = hard_filter(rows, query='Liverpool jersey 97/98 size M')
        self.assertEqual([item.id for item in kept], ['right'])

    def test_query_fillers_do_not_become_product_requirements(self):
        kept, _ = hard_filter([listing(title='Samsung TV')], query='looking for a Samsung television please')
        self.assertEqual(len(kept), 1)

    def test_wrong_model_and_accessories_stay_out(self):
        rows = [listing(id='wrong', title='Sony WH-1000XM4 headset', description='Compare to WH1000XM5'),
            listing(id='case', title='Sony WH1000XM5 headphones replacement case')]
        self.assertEqual(hard_filter(rows, query='Sony WH1000XM5 headphones')[0], [])

    def test_general_ai_aliases_are_used_and_cached(self):
        import search_intent
        search_intent._cache.clear()
        planned = SearchIntent(queries=['Acme gaming steering wheel', 'Acme racing wheel'],
            aliases=[AliasGroup(term='gaming', alternatives=['racing']), AliasGroup(term='steering', alternatives=['racing'])], identity_terms=['acme'])
        with patch.object(_llm, 'is_enabled', return_value=True), patch.object(_llm, 'call_json', return_value=planned) as model:
            intent = plan_search('Acme gaming steering wheel')
            plan_search('Acme gaming steering wheel')
        self.assertEqual(model.call_count, 1)
        self.assertEqual(intent.planner, 'gemini')
        self.assertIn('Acme racing wheel', intent.queries)
        self.assertTrue(intent.matches('Acme racing wheel'))
        self.assertFalse(intent.matches('Another-brand racing wheel'))

    def test_model_cannot_relax_brands_or_numbers(self):
        import search_intent
        search_intent._cache.clear()
        bad = SearchIntent(queries=['Samsung TV 99'], aliases=[AliasGroup(term='sony', alternatives=['Samsung']), AliasGroup(term='55', alternatives=['99'])])
        with patch.object(_llm, 'is_enabled', return_value=True), patch.object(_llm, 'call_json', return_value=bad):
            intent = plan_search('Sony television 55')
        self.assertNotIn('Samsung TV 99', intent.queries)
        self.assertFalse(intent.matches('Samsung TV 99'))

    def test_planner_failure_has_honest_fallback(self):
        with patch.object(_llm, 'is_enabled', return_value=True), patch.object(_llm, 'call_json', side_effect=ClientError(429, {})):
            intent = plan_search('IKEA sofa new query')
        self.assertEqual(intent.planner, 'local')
        self.assertIn('unavailable', intent.note)

    def test_queries_are_bounded_and_deduplicated(self):
        queries = query_variants('Liverpool shirt 97/98')
        self.assertLessEqual(len(queries), 3)
        self.assertEqual(len(queries), len(set(queries)))

    def test_alias_retrieval_deduplicates_and_keeps_each_market_depth(self):
        calls = []
        def fetch(query, limit):
            calls.append((query, limit))
            return [] if 'jersey' in query else [{'id':'one', 'title':'Liverpool shirt 1997/1998', 'description':''}]
        with patch.dict(marketplaces.ADAPTERS, {'carousell':fetch}, clear=True):
            rows, counts, errors = marketplaces.search_many('Liverpool jersey 97/98', ['carousell'], 12)
        self.assertEqual(counts, {'carousell':1})
        self.assertEqual(len(rows), 1)
        self.assertEqual(errors, [])
        self.assertTrue(all(limit == 12 for _, limit in calls))
        self.assertLessEqual(len(calls), 3)

    def test_partial_alias_failure_does_not_remove_earlier_results(self):
        row = listing(title='IKEA couch').model_dump(mode='json')
        with patch.dict(marketplaces.ADAPTERS, {'carousell':lambda *_: []}, clear=True), patch.object(marketplaces, 'plan_search', return_value=SearchIntent(queries=['IKEA sofa', 'IKEA couch'])), patch.object(marketplaces, 'ADAPTERS', {'carousell':unittest.mock.Mock(side_effect=[[row], marketplaces.MarketplaceSearchError('blocked')])}):
            rows, counts, errors = marketplaces.search_many('IKEA sofa', ['carousell'], 12)
        self.assertEqual(len(rows), 1)
        self.assertEqual(counts['carousell'], 1)
        self.assertEqual(len(errors), 1)

    def test_api_applies_the_same_ai_plan_to_retrieval_and_filtering(self):
        row = listing(title='Acme racing wheel')
        intent = SearchIntent(queries=['Acme gaming steering wheel', 'Acme racing wheel'],
            aliases=[AliasGroup(term='gaming',alternatives=['racing']), AliasGroup(term='steering',alternatives=['racing'])],
            planner='gemini', identity_terms=['acme'])
        with patch.object(config,'GEMINI_API_KEY',''), patch.object(config,'GEMINI_API_KEYS',()), patch.object(api,'plan_search',return_value=intent), patch.object(api.marketplace_service,'search_many',return_value=([row.model_dump(mode='json')],{'carousell':1},[])) as search:
            response = api.search(api.SearchRequest(query='Acme gaming steering wheel',pricing_mode='auto',marketplaces=['carousell']))
        self.assertEqual(response.kept_after_filter,1)
        self.assertEqual(response.search_intent.planner,'gemini')
        self.assertIs(search.call_args.kwargs['intent'], intent)

    def test_partial_query_failure_is_not_an_all_sources_502(self):
        row = listing(title='IKEA couch')
        with patch.object(config,'GEMINI_API_KEY',''), patch.object(config,'GEMINI_API_KEYS',()), patch.object(api.marketplace_service,'search_many',return_value=([row.model_dump(mode='json')],{'carousell':1},[{'marketplace':'carousell','message':'Additional query failed; earlier results retained.'}])):
            response = api.search(api.SearchRequest(query='IKEA sofa',pricing_mode='auto',marketplaces=['carousell']))
        self.assertEqual(len(response.decisions),1)


class JsonResult(BaseModel):
    answer: str


class KeyPoolTests(unittest.TestCase):
    def setUp(self):
        self.config_patches = [patch.object(config, 'GEMINI_API_KEY', 'fake-primary'), patch.object(config, 'GEMINI_API_KEYS', ('fake-secondary',))]
        for context in self.config_patches:
            context.start()
        _llm._cooldowns.clear()

    def tearDown(self):
        _llm._cooldowns.clear()
        for context in reversed(self.config_patches):
            context.stop()

    def test_numbered_env_keys_load_without_reading_dotenv(self):
        import os
        with patch.dict(os.environ, {'GEMINI_API_KEY':'first','GEMINI_API_KEY_2':'second','GEMINI_API_KEYS':'second,third'}, clear=True), patch('dotenv.load_dotenv'):
            settings = runpy.run_path(str(config.BASE_DIR / 'config.py'))
        self.assertEqual(settings['GEMINI_API_KEYS'], ('first','second','third'))

    def test_rate_limit_uses_second_key_and_skips_cooling_primary(self):
        calls = []
        class Client:
            def __init__(self, api_key, http_options):
                self.key = api_key
                self.models = self
            def generate_content(self, **kwargs):
                calls.append(self.key)
                if self.key == 'fake-primary':
                    raise ClientError(429, {'error': {'details':[{'@type':'type.googleapis.com/google.rpc.RetryInfo','retryDelay':'120s'}]}})
                return SimpleNamespace(text='{"answer":"ok"}')
            def close(self):
                pass
        with patch('google.genai.Client', Client):
            self.assertEqual(_llm.call_json('s','u',JsonResult).answer, 'ok')
            _llm.call_json('s','u',JsonResult)
        self.assertEqual(calls, ['fake-primary','fake-secondary','fake-secondary'])
        self.assertGreater(_llm._cooldowns['fake-primary'] - _llm.time.monotonic(), 119)

    def test_all_limited_keys_stop_without_secret_leaks(self):
        with patch('google.genai.Client') as client:
            client.return_value.models.generate_content.side_effect = ClientError(429, {'error':{'message':'fake-secret'}})
            with self.assertRaises(_llm.KeysCoolingDown):
                _llm.call_json('s','u',JsonResult)
            self.assertEqual(client.call_count, 2)
            with self.assertRaises(_llm.KeysCoolingDown):
                _llm.call_json('s','u',JsonResult)
            self.assertEqual(client.call_count, 2)
        self.assertEqual(_llm.ai_status()['state'], 'rate_limited')
        self.assertNotIn('fake-secret', str(_llm.ai_status()))

    def test_other_errors_do_not_cycle_the_pool(self):
        with patch('google.genai.Client') as client:
            client.return_value.models.generate_content.side_effect = ClientError(403, {})
            with self.assertRaises(ClientError):
                _llm.call_json('s','u',JsonResult)
        self.assertEqual(client.call_count, 1)

    def test_pool_only_configuration_is_enabled_and_health_has_no_keys(self):
        with patch.object(config, 'GEMINI_API_KEY', ''):
            self.assertTrue(_llm.is_enabled())
            self.assertEqual(api.health()['ai_mode'], 'gemini')
            self.assertNotIn('fake-secondary', str(api.health()))

    def test_photo_agent_uses_shared_json_helper(self):
        from agents import vision_authenticator
        from schemas import VisionCheck
        row = listing(image_urls=['https://i.ebayimg.com/photo.jpg'])
        with patch.object(vision_authenticator, '_fetch_image', return_value=(b'fake image', 'image/jpeg')), patch.object(vision_authenticator, 'call_json', return_value=VisionCheck(consistency_score=60, images_checked=0)) as helper:
            result = vision_authenticator.check(row)
        self.assertEqual(result.images_checked, 1)
        self.assertEqual(helper.call_count, 1)
        self.assertIsInstance(helper.call_args.args[1], list)

    def test_photo_agent_blocks_lookalike_hostnames(self):
        from agents.vision_authenticator import _fetch_image
        with patch('httpx.get') as request:
            self.assertIsNone(_fetch_image('https://evilcarousell.com/photo.jpg'))
            self.assertIsNone(_fetch_image('https://127.0.0.1/photo.jpg'))
        request.assert_not_called()


class InternationalAdapterTests(unittest.TestCase):
    def setUp(self):
        international._fx_cache.clear()
        international._token_cache = None

    def test_missing_keys_report_setup_requirements(self):
        with patch.object(config, 'EBAY_CLIENT_ID', ''), patch.object(config, 'ETSY_API_KEY', ''):
            with self.assertRaises(international.InternationalSearchError):
                international.search_ebay('LEGO', 12)
            with self.assertRaises(international.InternationalSearchError):
                international.search_etsy('jersey', 12)

    def test_ebay_token_is_cached_and_401_refresh_is_bounded(self):
        with patch.object(config,'EBAY_CLIENT_ID','fake-id'), patch.object(config,'EBAY_CLIENT_SECRET','fake-secret'), patch.object(international,'_json_request',return_value={'access_token':'fake-token','expires_in':7200}) as request:
            self.assertEqual(international._ebay_token(),'fake-token')
            international._ebay_token()
            self.assertEqual(request.call_count,1)
        with patch.object(international,'_ebay_token',side_effect=['old','new']) as token, patch.object(international,'_json_request',side_effect=[international.InternationalSearchError('expired',401), {'itemSummaries':[]}]):
            self.assertEqual(international.search_ebay('LEGO',12),[])
        self.assertEqual(token.call_count,2)
        self.assertEqual(token.call_args.kwargs,{'force':True})

    def test_conversion_failure_does_not_guess_myr_prices(self):
        with patch.object(international,'_json_request',return_value={'rates':{},'date':'2026-10-07'}):
            with self.assertRaises(international.InternationalSearchError):
                international._myr_money({'value':100,'currency':'USD'})

    def test_ebay_price_shipping_and_feedback_are_normalized_honestly(self):
        product = {'itemId':'v1|123|0','itemWebUrl':'https://www.ebay.com/itm/123','title':'LEGO 75192 UCS Millennium Falcon',
            'price':{'value':'500','currency':'USD'},'buyingOptions':['FIXED_PRICE'],
            'seller':{'username':'seller','feedbackPercentage':'99.8','feedbackScore':500},
            'shippingOptions':[{'shippingCostType':'FIXED','shippingCost':{'value':'25','currency':'USD'}}]}
        with patch.object(international, '_ebay_token', return_value='fake'), patch.object(international, '_json_request', side_effect=[{'itemSummaries':[product]}, {'rates':{'MYR':4},'date':'2026-10-07'}]):
            row = international.search_ebay('LEGO 75192', 12)[0]
        self.assertEqual(row['price'], 2000)
        self.assertEqual(row['shipping_cost_myr'], 100)
        self.assertIsNone(row['seller_rating'])
        self.assertEqual(row['original_currency'], 'USD')
        self.assertFalse(row['landed_cost_verified'])
        self.assertEqual(listing(**row).marketplace, 'ebay')

    def test_etsy_search_and_batch_images_use_documented_parameters(self):
        product = {'listing_id':123,'title':'Liverpool shirt 97/98','url':'https://www.etsy.com/listing/123/liverpool-shirt',
            'price':{'amount':5000,'divisor':100,'currency_code':'MYR'},'listing_type':'physical'}
        enriched = {**product, 'images':[{'url_570xN':'https://images.example.com/photo.jpg'}]}
        with patch.object(config, 'ETSY_API_KEY', 'fake'), patch.object(config, 'ETSY_SHARED_SECRET', 'fake'), patch.object(international, '_json_request', side_effect=[{'results':[product]},{'results':[enriched]}]) as request:
            row = international.search_etsy('Liverpool 97/98', 12)[0]
        self.assertNotIn('includes', request.call_args_list[0].kwargs['params'])
        self.assertEqual(request.call_args_list[1].kwargs['params']['includes'], 'Images')
        self.assertEqual(row['price'], 50)
        self.assertEqual(len(row['image_urls']), 1)
        self.assertEqual(listing(**row).marketplace, 'etsy')

    def test_etsy_digital_and_invalid_prices_are_not_resale_inventory(self):
        product = {'listing_id':123,'title':'Liverpool shirt template','url':'https://www.etsy.com/listing/123/template',
            'price':{'amount':1000,'divisor':100,'currency_code':'MYR'}, 'listing_type':'download'}
        with patch.object(config, 'ETSY_API_KEY', 'fake'), patch.object(config, 'ETSY_SHARED_SECRET', 'fake'), patch.object(international, '_json_request', side_effect=[{'results':[product]},{'results':[]}]):
            self.assertEqual(international.search_etsy('Liverpool',12), [])
        self.assertIsNone(international._myr_money({'value':'NaN','currency':'USD'}))
        self.assertIsNone(international._myr_money({'amount':100,'divisor':0,'currency_code':'MYR'}))

    def test_international_url_validation_and_forged_cost_verification(self):
        with self.assertRaises(ValidationError):
            listing(marketplace='ebay',source='ebay_api',url='https://evil.example/itm/123')
        row = listing(marketplace='etsy',source='etsy_api',url='https://www.etsy.com/listing/123/product',landed_cost_verified=True)
        self.assertFalse(row.landed_cost_verified)

    def test_international_offers_cannot_emit_buy_alerts(self):
        row = listing(title='LEGO 75192 UCS Millennium Falcon', price=100, marketplace='ebay',source='ebay_api',url='https://www.ebay.com/itm/123',shipping_cost_myr=50)
        with patch.object(config, 'GEMINI_API_KEY',''), patch.object(config, 'GEMINI_API_KEYS',()), patch.object(api.marketplace_service, 'search_many', return_value=([row.model_dump(mode='json')], {'ebay':1}, [])), patch.object(api.notify, 'send_telegram_alert') as alert:
            response = api.search(api.SearchRequest(query='LEGO 75192',pricing_mode='manual',resale_estimate=3000,marketplaces=['ebay']))
        self.assertEqual(response.decisions[0].shipping_cost_myr, 50)
        self.assertEqual(response.decisions[0].total_cost_myr, 300)
        self.assertFalse(response.decisions[0].is_profitable)
        self.assertTrue(response.decisions[0].cost_warning)
        alert.assert_not_called()

    def test_six_markets_fit_api_and_chat_contracts(self):
        markets = list(marketplaces.SUPPORTED_MARKETPLACES)
        self.assertEqual(len(api.SearchRequest(query='LEGO',pricing_mode='auto',marketplaces=markets).marketplaces),6)
        self.assertEqual(len(copilot.ChatContext(marketplaces=markets).marketplaces),6)
        request = copilot.ChatRequest(message='find Liverpool shirt 97/98 on ebay and etsy')
        self.assertEqual(copilot._search_command(request).marketplaces,['ebay','etsy'])
