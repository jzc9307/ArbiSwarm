import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import api
import copilot
from tests.test_core import listing


class BoardWiringTests(unittest.TestCase):
    def run_search(self, rows, **fields):
        counts = {market: sum(item.marketplace == market for item in rows) for market in fields.get('marketplaces', ['carousell'])}
        with patch.object(api.marketplace_service, 'search_many', return_value=([item.model_dump(mode='json') for item in rows], counts, [])), patch.object(api.config, 'GEMINI_API_KEY', ''), patch.object(api.config, 'GEMINI_API_KEYS', ()):
            return api.search(api.SearchRequest(query='Labubu Macaron', pricing_mode='auto', max_purchase_price=299, source_mode='live', **fields))

    def test_visible_range_obeys_budget_but_retains_price_evidence(self):
        response = self.run_search([listing(price=23), listing(id='2345678901', price=873.26, url='https://www.carousell.com.my/p/labubu-2345678901/')])
        self.assertEqual(len(response.market_listings), 2)
        self.assertEqual(len(response.decisions), 1)
        self.assertEqual(response.product_groups[0].highest_price_myr, 23)
        self.assertEqual(response.decisions[0].resale_sample_size, 2)

    def test_refresh_and_full_search_use_identical_matching_and_values(self):
        carousell = listing(price=80)
        lazada = listing(id='123456', marketplace='lazada', source='lazada_live', price=90, url='https://www.lazada.com.my/products/labubu-i123456.html')
        full = self.run_search([carousell, lazada], marketplaces=['carousell', 'lazada'])
        old_time = datetime(2026, 10, 6, tzinfo=timezone.utc)
        refreshed = self.run_search([carousell], marketplaces=['carousell'], retained_market_listings=[lazada, lazada], retained_source_times={'lazada':old_time})
        self.assertEqual(len(refreshed.market_listings), 2)
        self.assertEqual([(item.offer_id, item.group_id, item.resale_estimate_myr) for item in full.decisions], [(item.offer_id, item.group_id, item.resale_estimate_myr) for item in refreshed.decisions])
        retained = next(item for item in refreshed.decisions if item.marketplace == 'lazada')
        self.assertEqual(retained.collected_at, old_time)


class CopilotTests(unittest.TestCase):
    def request(self, message, **context):
        return copilot.ChatRequest(message=message, context={'query':'Liverpool jersey', 'max_purchase_price':299, 'marketplaces':['carousell', 'lazada'], **context})

    def local(self, request):
        with patch.object(copilot, 'is_enabled', return_value=False):
            return copilot.chat(request)

    def test_budget_change_retains_current_query(self):
        reply = self.local(self.request('under RM200'))
        self.assertEqual(reply['action']['query'], 'Liverpool jersey')
        self.assertEqual(reply['action']['max_purchase_price'], 200)

    def test_new_product_and_budget_do_not_reuse_old_query(self):
        reply = self.local(self.request('find camera under RM200'))
        self.assertEqual(reply['action']['query'], 'camera')
        self.assertEqual(reply['action']['max_purchase_price'], 200)

    def test_help_me_search_runs_new_query_with_size_and_season(self):
        reply = self.local(self.request('help me search liverpool jersey 26/27 m size', query='Labubu Macaron', max_purchase_price=60))
        self.assertEqual(reply['action']['query'], 'liverpool jersey 26/27 m size')
        self.assertEqual(reply['action']['max_purchase_price'], 60)
        self.assertEqual(reply['action']['pricing_mode'], 'auto')
        self.assertTrue(reply['auto_execute'])

    def test_polite_search_preserves_variant_after_budget_and_selects_sources(self):
        reply = self.local(self.request('Can you help me search for Liverpool jersey 26/27 under RM300 size M on Shopee and Lazada'))
        self.assertEqual(reply['action']['query'], 'Liverpool jersey 26/27 size M')
        self.assertEqual(reply['action']['marketplaces'], ['shopee','lazada'])
        self.assertEqual(reply['action']['max_purchase_price'], 300)
        self.assertTrue(reply['auto_execute'])

    def test_search_again_retains_product(self):
        reply = self.local(self.request('search again under RM200'))
        self.assertEqual(reply['action']['query'], 'Liverpool jersey')
        self.assertEqual(reply['action']['max_purchase_price'], 200)

    def test_question_about_searching_does_not_auto_run(self):
        reply = self.local(self.request('How do I search for a jersey?'))
        self.assertFalse(reply['auto_execute'])
        self.assertIsNone(reply['action'])

    def test_invalid_direct_search_does_not_run_or_wait_for_ai(self):
        with patch.object(copilot, 'is_enabled', return_value=False):
            for message in ['search jersey under RM0','search jersey under RM-10','search jersey under RM1000001','help me search x']:
                with self.subTest(message=message):
                    reply = copilot.chat(self.request(message))
                    self.assertIsNone(reply['action'])
                    self.assertFalse(reply['auto_execute'])

    def test_direct_search_uses_fast_command_path_even_with_ai_configured(self):
        with patch.object(copilot, 'is_enabled', return_value=True), patch.object(copilot, 'call_json') as model:
            reply = copilot.chat(self.request('please find LEGO 75192 under RM3000'))
            model.assert_not_called()
            self.assertTrue(reply['auto_execute'])

    def test_new_search_does_not_attach_previous_selected_listing(self):
        reply = self.local(self.request('help me search LEGO 75192 under RM3000', offers=[{'offer_id':'old','title':'Jersey','marketplace':'carousell','price':100}], selected_offer_id='old'))
        self.assertEqual(reply['offer_ids'], [])

    def test_invalid_direct_search_is_not_overridden_by_model(self):
        with patch.object(copilot, 'is_enabled', return_value=True), patch.object(copilot, 'call_json') as model:
            reply = copilot.chat(self.request('find jersey under RM-10'))
            model.assert_not_called()
            self.assertIsNone(reply['action'])
            self.assertFalse(reply['auto_execute'])

    def test_product_named_watch_is_not_a_watchlist_command(self):
        reply = self.local(self.request('find Apple Watch under RM200'))
        self.assertEqual(reply['action']['type'], 'search')
        self.assertEqual(reply['action']['query'], 'Apple Watch')

    def test_explanation_uses_exact_selected_evidence(self):
        offer = {'offer_id':'carousell:123', 'title':'Jersey', 'marketplace':'carousell', 'price':100, 'shipping_cost_myr':5, 'platform_fee_myr':10, 'total_cost_myr':115, 'resale_estimate_myr':120, 'estimated_profit_myr':5, 'estimated_margin_pct':4.3, 'reasoning':'Variant unclear', 'risk_level':'high'}
        reply = self.local(self.request('explain this', offers=[offer], selected_offer_id='carousell:123'))
        self.assertIn('total cost RM115.00', reply['reply'])
        self.assertIn('Variant unclear', reply['reply'])
        self.assertEqual(reply['offer_ids'], ['carousell:123'])
        self.assertEqual(reply['view'], 'explain')

    def test_unknown_ai_offer_ids_are_removed(self):
        with patch.object(copilot, 'is_enabled', return_value=True), patch.object(copilot, 'call_json', return_value=copilot.ChatPlan(intent='explain', offer_ids=['invented'])):
            reply = copilot.chat(self.request('explain this'))
        self.assertEqual(reply['offer_ids'], [])
        self.assertIn('Choose Ask about this', reply['reply'])

    def test_refresh_is_proposed_not_executed(self):
        with patch.object(api.marketplace_service, 'search_many') as provider:
            reply = self.local(self.request('refresh carousell'))
            provider.assert_not_called()
        self.assertEqual(reply['action']['marketplaces'], ['carousell'])

    def test_invalid_command_budget_does_not_crash(self):
        reply = self.local(self.request('budget 0'))
        self.assertIsNone(reply['action'])

    def test_authenticity_discussion_does_not_change_filters(self):
        reply = self.local(self.request('Is it fake?'))
        self.assertIsNone(reply['action'])
        self.assertIn('not proof of a fake', reply['reply'])

    def test_demo_does_not_promise_live_actions(self):
        self.assertIsNone(self.local(self.request('watch this search', source_mode='demo'))['action'])
        self.assertIsNone(self.local(self.request('refresh carousell', source_mode='demo'))['action'])


class LlmFallbackTests(unittest.TestCase):
    def test_gemini_deadline_never_falls_below_service_minimum(self):
        from agents._llm import call_json
        from types import SimpleNamespace
        with patch('google.genai.Client') as client, patch.object(api.config,'GEMINI_API_KEY','test-key'):
            client.return_value.models.generate_content.return_value = SimpleNamespace(text='{"reply":"hello"}')
            call_json('test','test',copilot.ChatPlan,timeout_ms=8000)
        self.assertGreaterEqual(client.call_args.kwargs['http_options']['timeout'],10000)

    def test_quota_error_is_explained_without_exposing_exception_secrets(self):
        from google.genai.errors import ClientError
        with patch.object(copilot,'is_enabled',return_value=True), patch.object(copilot,'call_json',side_effect=ClientError(429,{'error':{'message':'secret-value'}})):
            result = copilot.chat(copilot.ChatRequest(message='got any just for 250?',context={'query':'Liverpool jersey','max_purchase_price':300}))
        self.assertEqual(result['action']['type'],'filter')
        self.assertEqual(result['ai_status']['state'],'rate_limited')
        self.assertIn('429',result['ai_status']['message'])
        self.assertNotIn('secret-value',str(result))

    def test_ai_receives_history_and_current_filters(self):
        request = copilot.ChatRequest(message='anything cheaper than that?',history=[{'role':'user','content':'Only Shopee please'}],context={'query':'LEGO 75192','visible_marketplaces':['shopee'],'view_max_price':3000})
        with patch.object(copilot,'is_enabled',return_value=True), patch.object(copilot,'call_json',return_value=copilot.ChatPlan(intent='filter',max_purchase_price=2500)) as model:
            result = copilot.chat(request)
        self.assertIn('Only Shopee please',model.call_args.args[1])
        self.assertIn('visible_marketplaces',model.call_args.args[1])
        self.assertEqual(result['action']['marketplaces'],['shopee'])
        self.assertEqual(result['action']['max_price'],2500)
        self.assertEqual(result['mode'],'ai')

    def test_retired_model_retries_supported_default(self):
        from google.genai.errors import ClientError
        from agents._llm import call_json
        from types import SimpleNamespace
        with patch('google.genai.Client') as client, patch.object(api.config, 'GEMINI_API_KEY', 'test-key'), patch.object(api.config, 'CHEAP_MODEL', 'retired'), patch.object(api.config, 'FALLBACK_MODEL', 'supported'):
            generate = client.return_value.models.generate_content
            generate.side_effect = [ClientError(404, {'error':{'message':'retired'}}), SimpleNamespace(text='{"reply":"Context received"}')]
            reply = call_json('test', 'test', copilot.ChatPlan)
            self.assertEqual(reply.reply, 'Context received')
            self.assertEqual([call.kwargs['model'] for call in generate.call_args_list], ['retired', 'supported'])

    def test_auth_errors_do_not_retry_another_model(self):
        from google.genai.errors import ClientError
        from agents._llm import call_json
        with patch('google.genai.Client') as client, patch.object(api.config, 'GEMINI_API_KEY', 'test-key'):
            generate = client.return_value.models.generate_content
            generate.side_effect = ClientError(401, {'error':{'message':'unauthorized'}})
            with self.assertRaises(ClientError):
                call_json('test', 'test', copilot.ChatPlan)
            self.assertEqual(generate.call_count, 1)

    def test_high_margin_pass_explains_existing_evidence_block(self):
        from agents.lead_strategist import decide
        from schemas import ContextAnalysis, VisionCheck
        retail = listing(price=23, marketplace='lazada', source='lazada_live', url='https://www.lazada.com.my/products/labubu-i123456.html')
        with patch.object(api.config, 'GEMINI_API_KEY', ''), patch.object(api.config, 'GEMINI_API_KEYS', ()):
            decision = decide(retail, ContextAnalysis(true_condition='New'), VisionCheck(consistency_score=None), 80)
        self.assertGreater(decision.estimated_margin_pct, 20)
        self.assertFalse(decision.is_profitable)
        self.assertIn('retail review evidence', decision.reasoning)
        self.assertNotIn('margin is below', decision.reasoning)


if __name__ == '__main__':
    unittest.main()
