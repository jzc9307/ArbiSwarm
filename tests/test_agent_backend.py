"""Backend contract, quota and evidence tests. All providers are mocked."""
import asyncio
import json
import os
import runpy
import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from google.genai.errors import ClientError, ServerError
from pydantic import BaseModel

import api
import config
import copilot
import marketplaces
import search_intent
from agents import _llm, batch_analyst as analyst, runtime
from tests.test_core import listing


class Answer(BaseModel):
    ok: bool


def response(text='{"ok":true}'):
    return SimpleNamespace(text=text, usage_metadata=SimpleNamespace(prompt_token_count=12,
        candidates_token_count=8, thoughts_token_count=5, total_token_count=25))


def finding(item, **updates):
    return analyst.Finding(offer_id=analyst.offer_id(item), relevance='match',
                           evidence=[analyst.EvidenceQuote(field='title', text=item.title)], **updates)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        for name, value in {'GEMINI_API_KEY':'fake-1','GEMINI_API_KEYS':tuple(f'fake-{i}' for i in range(1,6)),
            'GEMINI_KEY_PROJECTS':('a','b','c','d','e'),'GEMINI_LOCAL_RPM':5,'GEMINI_LOCAL_RPD':20,
            'GEMINI_MAX_ATTEMPTS':2,'AI_OPERATION_BUDGET':3,'AI_SHORTLIST_SIZE':8,
            'CHEAP_MODEL':'gemini-3.8-flash','FALLBACK_MODEL':'gemini-3.6-flash'}.items():
            self.stack.enter_context(patch.object(config, name, value))
        # Any accidental SDK/network use fails immediately, not against user quota.
        self.stack.enter_context(patch('httpx.Client.send', side_effect=AssertionError('Unmocked network request in backend tests')))
        for value in (_llm._cooldowns,_llm._limits,_llm._project_cooldowns,_llm._model_cooldowns,
                      _llm._unavailable_models,analyst._cache,copilot._plan_cache,search_intent._cache):
            value.clear()
        _llm._last_status={'state':'unverified','message':'AI connection not yet verified.'}

    def tearDown(self):
        self.stack.close()

    def test_five_roles_prefer_their_own_slots(self):
        calls=[]
        class Client:
            def __init__(self, api_key, **kwargs): self.key=api_key;self.models=self
            def generate_content(self, **kwargs): calls.append(self.key);return response()
            def close(self): pass
        with patch('google.genai.Client',Client):
            for role in ('manager','analyst','vision','reviewer','chat'):
                _llm.call_json('test','test',Answer,role=role)
        self.assertEqual(calls,[f'fake-{i}' for i in range(1,6)])

    def test_request_ledger_counts_real_metadata_not_guessed_tokens(self):
        with patch('google.genai.Client') as client,runtime.operation('test',1) as run:
            client.return_value.models.generate_content.return_value=response()
            _llm.call_json('test','test',Answer,role='analyst')
            report=run.snapshot()
        self.assertEqual(report['provider_attempts'],1)
        self.assertEqual(report['successful_provider_responses'],1)
        self.assertEqual(report['token_usage']['total_token_count'],25)
        self.assertTrue(report['usage_complete'])
        self.assertNotIn('fake-',json.dumps(report))

    def test_invalid_json_keeps_billable_usage_but_never_claims_valid_analysis(self):
        with patch('google.genai.Client') as client,runtime.operation('test',1) as run:
            client.return_value.models.generate_content.return_value=response('invalid')
            with self.assertRaises(ValueError):_llm.call_json('s','u',Answer)
            report=run.snapshot()
        self.assertEqual(report['token_usage']['total_token_count'],25)
        self.assertFalse(report['ai_completed'])
        self.assertEqual(runtime.mode(report),'deterministic')

    def test_missing_usage_is_unknown_not_zero(self):
        with patch('google.genai.Client') as client,runtime.operation('test',1) as run:
            client.return_value.models.generate_content.return_value=SimpleNamespace(text='{"ok":true}')
            _llm.call_json('s','u',Answer)
            report=run.snapshot()
        self.assertIsNone(report['token_usage'])
        self.assertFalse(report['usage_complete'])

    def test_partial_metadata_never_fills_missing_tokens_with_zero(self):
        with runtime.operation('test', 2) as run:
            runtime.record('analyst', 'provider_response', usage={'total_token_count': 25, 'prompt_token_count': 12})
            runtime.record('chat', 'provider_response', usage={'total_token_count': 10})
            report = run.snapshot()
        self.assertEqual(report['token_usage']['total_token_count'], 35)
        self.assertIsNone(report['token_usage']['prompt_token_count'])
        self.assertIsNone(report['token_usage']['candidates_token_count'])
        self.assertFalse(report['usage_complete'])

    def test_numbered_credentials_sort_numerically_and_deduplicate_before_backups(self):
        values = {'GEMINI_API_KEY': 'one', 'GEMINI_API_KEY_10': 'ten',
                  'GEMINI_API_KEY_2': 'two', 'GEMINI_API_KEY_3': '',
                  'GEMINI_API_KEYS': 'two,extra', 'GEMINI_KEY_PROJECTS': 'a,b,c,d'}
        with patch.dict(os.environ, values, clear=True), patch('dotenv.load_dotenv'):
            loaded = runpy.run_path(config.__file__)
        self.assertEqual(loaded['GEMINI_API_KEYS'], ('one', 'two', 'ten', 'extra'))
        self.assertEqual(loaded['GEMINI_KEY_PROJECTS'], ('a', 'b', 'c', 'd'))

    def test_workflow_budget_prevents_more_provider_requests(self):
        with patch('google.genai.Client') as client,runtime.operation('test',1) as run:
            client.return_value.models.generate_content.return_value=response()
            _llm.call_json('s','u',Answer)
            with self.assertRaises(runtime.RequestBudgetExceeded):_llm.call_json('s','u',Answer)
        self.assertEqual(client.return_value.models.generate_content.call_count,1)
        self.assertEqual(run.snapshot()['provider_attempts'],1)

    def test_429_fails_over_to_an_independent_project_with_two_attempts(self):
        with patch('google.genai.Client') as client,runtime.operation('test',3) as run:
            client.return_value.models.generate_content.side_effect=[ClientError(429,{}),response()]
            self.assertTrue(_llm.call_json('s','u',Answer).ok)
        self.assertEqual(client.call_args_list[0].kwargs['api_key'],'fake-1')
        self.assertEqual(client.call_args_list[1].kwargs['api_key'],'fake-2')
        self.assertEqual(run.snapshot()['provider_attempts'],2)

    def test_same_project_is_not_retried_with_another_key_after_429(self):
        with patch.object(config,'GEMINI_KEY_PROJECTS',('same',)*5),patch('google.genai.Client') as client,runtime.operation('test',3) as run:
            client.return_value.models.generate_content.side_effect=ClientError(429,{})
            with self.assertRaises(_llm.KeysCoolingDown):_llm.call_json('s','u',Answer)
        self.assertEqual(client.return_value.models.generate_content.call_count,1)

    def test_shared_local_project_rpm_enforced_across_keys(self):
        with patch.object(config,'GEMINI_KEY_PROJECTS',('same',)*5),patch.object(config,'GEMINI_LOCAL_RPM',1),patch('google.genai.Client') as client:
            client.return_value.models.generate_content.return_value=response()
            _llm.call_json('s','u',Answer,role='manager')
            with self.assertRaises(_llm.LocalQuotaExceeded):_llm.call_json('s','u',Answer,role='chat')
        self.assertEqual(client.return_value.models.generate_content.call_count,1)

    def test_daily_budget_is_separate_from_minute_budget(self):
        with patch.object(config,'GEMINI_KEY_PROJECTS',('same',)*5),patch.object(config,'GEMINI_LOCAL_RPD',1),patch('google.genai.Client') as client:
            client.return_value.models.generate_content.return_value=response()
            _llm.call_json('s','u',Answer)
            for bucket in _llm._limits.values():bucket['minute'].clear()
            with self.assertRaises(_llm.LocalQuotaExceeded):_llm.call_json('s','u',Answer)
        self.assertEqual(client.return_value.models.generate_content.call_count,1)

    def test_transient_503_retries_same_key_once(self):
        with patch('google.genai.Client') as client,patch.object(_llm.time,'sleep'):
            client.return_value.models.generate_content.side_effect=[ServerError(503,{}),response()]
            self.assertTrue(_llm.call_json('s','u',Answer).ok)
        self.assertEqual(client.call_count,1)
        self.assertEqual(client.return_value.models.generate_content.call_count,2)

    def test_repeated_503_has_model_cooldown_and_no_key_storm(self):
        with patch('google.genai.Client') as client,patch.object(_llm.time,'sleep'):
            client.return_value.models.generate_content.side_effect=ServerError(503,{})
            with self.assertRaises(ServerError):_llm.call_json('s','u',Answer)
            with self.assertRaises(_llm.KeysCoolingDown):_llm.call_json('s','u',Answer)
        self.assertEqual(client.return_value.models.generate_content.call_count,2)

    def test_503_provider_retry_hint_defers_instead_of_retrying(self):
        error = ServerError(503, {'error': {'details': [
            {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '120s'}]}})
        with patch('google.genai.Client') as client, patch.object(_llm.time, 'sleep') as sleep:
            client.return_value.models.generate_content.side_effect = error
            with self.assertRaises(ServerError):
                _llm.call_json('s', 'u', Answer)
            with self.assertRaises(_llm.KeysCoolingDown):
                _llm.call_json('s', 'u', Answer)
        sleep.assert_not_called()
        self.assertEqual(client.return_value.models.generate_content.call_count, 1)

    def test_known_unavailable_model_not_probed_again_on_next_call(self):
        with patch('google.genai.Client') as client:
            client.return_value.models.generate_content.side_effect=[ClientError(404,{}),response(),response()]
            _llm.call_json('s','u',Answer);_llm.call_json('s','u',Answer)
        self.assertEqual([call.kwargs['model'] for call in client.return_value.models.generate_content.call_args_list],
                         ['gemini-3.8-flash','gemini-3.6-flash','gemini-3.6-flash'])

    def test_batch_reviews_many_items_with_one_call_and_balanced_sources(self):
        rows=[listing(id=str(i),price=40+i) for i in range(12)]
        rows += [listing(id='laz',marketplace='lazada',source='lazada_live',url='https://www.lazada.com.my/products/x-i123.html')]
        def generate(prompt,encoded,schema,**kwargs):
            ids={item['offer_id'] for item in json.loads(encoded)['listings']}
            return analyst.Findings(findings=[finding(item) for item in rows if analyst.offer_id(item) in ids])
        with patch.object(analyst,'call_json',side_effect=generate) as model:
            result=analyst.analyze_shortlist(rows,'Labubu Macaron')
        self.assertEqual(model.call_count,1)
        self.assertEqual(sum(value=='ai_completed' for value in result.statuses.values()),8)
        self.assertEqual(result.statuses['lazada:laz'],'ai_completed')
        self.assertEqual(sum(value=='not_reviewed' for value in result.statuses.values()),5)

    def test_unchanged_evidence_cached_changed_price_or_query_requires_analysis(self):
        row=listing()
        def generate(prompt,encoded,schema,**kwargs):
            return analyst.Findings(findings=[finding(row)])
        with patch.object(analyst,'call_json',side_effect=generate) as model:
            analyst.analyze_shortlist([row],'Labubu Macaron')
            cached=analyst.analyze_shortlist([row],'Labubu Macaron')
            analyst.analyze_shortlist([row.model_copy(update={'price':41})],'Labubu Macaron')
            analyst.analyze_shortlist([row],'Labubu Macaron full set')
        self.assertEqual(cached.statuses[analyst.offer_id(row)],'cache_reused')
        self.assertEqual(model.call_count,3)

    def test_refresh_analyses_only_changed_records(self):
        first=listing(id='1');second=listing(id='2')
        def generate(prompt,encoded,schema,**kwargs):
            rows=json.loads(encoded)['listings']
            return analyst.Findings(findings=[analyst.Finding(offer_id=row['offer_id'],relevance='match',evidence=[{'field':'title','text':row['title']}]) for row in rows])
        with patch.object(analyst,'call_json',side_effect=generate) as model:
            analyst.analyze_shortlist([first,second],'Labubu Macaron')
            analyst.analyze_shortlist([first,second.model_copy(update={'description':'Changed description with new condition evidence.'})],'Labubu Macaron')
        self.assertEqual(len(json.loads(model.call_args.args[1])['listings']),1)

    def test_fabricated_duplicate_and_missing_findings_never_become_reviewed(self):
        rows=[listing(id='1'),listing(id='2')]
        bad=finding(rows[0]);bad.evidence[0].text='Imaginary receipt verified'
        fake=finding(rows[0]);fake.offer_id='invented:999'
        with patch.object(analyst,'call_json',return_value=analyst.Findings(findings=[bad,finding(rows[0]),fake])):
            result=analyst.analyze_shortlist(rows,'Labubu Macaron')
        self.assertFalse(result.findings)
        self.assertTrue(all(status=='local_fallback' for status in result.statuses.values()))

    def test_whitespace_quote_is_rejected(self):
        row=listing();bad=finding(row);bad.evidence[0].text='   '
        with patch.object(analyst,'call_json',return_value=analyst.Findings(findings=[bad])):
            result=analyst.analyze_shortlist([row],'Labubu Macaron')
        self.assertFalse(result.findings)

    def test_batch_cannot_remove_local_risk_flags(self):
        row=listing(description='Used. Missing parts. Deposit requested. Contact on whatsapp. No returns.')
        with patch.object(analyst,'call_json',return_value=analyst.Findings(findings=[finding(row)])):
            result=analyst.analyze_shortlist([row],'Labubu Macaron')
        analysis=result.analyses[analyst.offer_id(row)]
        self.assertTrue(analysis.missing_parts)
        self.assertGreaterEqual(len(analysis.red_flags),2)

    def test_busy_batch_never_duplicates_a_provider_call(self):
        analyst._batch_lock.acquire()
        try:
            with patch.object(analyst,'call_json') as model:
                result=analyst.analyze_shortlist([listing()],'Labubu Macaron')
            model.assert_not_called()
            self.assertIn('local_fallback',result.statuses.values())
        finally:analyst._batch_lock.release()

    def test_local_mode_never_invokes_the_batch_model(self):
        with patch.object(analyst,'call_json') as model:
            analyst.analyze_shortlist([listing()],'Labubu Macaron',enabled=False)
        model.assert_not_called()

    def test_legacy_entry_point_cannot_emit_buy_signal_after_ai_failure(self):
        from orchestrator import run_swarm
        with patch.object(analyst, 'call_json', side_effect=ClientError(429, {})):
            decision = run_swarm(listing(), 100)
        self.assertFalse(decision.is_profitable)
        self.assertIsNone(decision.negotiation_message)
        self.assertIn('Needs verification', decision.reasoning)

    def test_local_only_photo_request_is_rejected_without_any_provider_call(self):
        with patch.object(api.marketplace_service, 'search_many') as retrieve, patch.object(api.lens, 'compare') as vision:
            with self.assertRaises(HTTPException) as failure:
                api.search(api.SearchRequest(query='Labubu Macaron', pricing_mode='auto', analysis_mode='local', lens_reference_id='test-reference-token-12345'))
        retrieve.assert_not_called(); vision.assert_not_called()
        self.assertEqual(failure.exception.status_code, 422)

    def test_api_preserves_contract_no_per_listing_agent_calls_and_cache_reuse(self):
        rows=[listing(id=str(i),price=40+i) for i in range(10)]
        def generate(prompt,encoded,schema,**kwargs):
            source=json.loads(encoded)['listings']
            return analyst.Findings(findings=[analyst.Finding(offer_id=row['offer_id'],relevance='match',evidence=[{'field':'title','text':row['title']}]) for row in source])
        with patch.object(api.marketplace_service,'search_many',return_value=([row.model_dump() for row in rows],{'carousell':10},[])),patch.object(analyst,'call_json',side_effect=generate) as model,patch('agents.context_analyst.call_json') as context,patch('agents.vision_authenticator.call_json') as vision,patch('agents.lead_strategist.call_json') as strategist,patch('notify.send_telegram_alert'):
            req=api.SearchRequest(query='Labubu Macaron',pricing_mode='manual',resale_estimate=100,marketplaces=['carousell'])
            result=api.search(req);again=api.search(req)
        self.assertEqual(model.call_count,2)  # First 8, then only the remaining 2.
        context.assert_not_called();vision.assert_not_called();strategist.assert_not_called()
        self.assertEqual(len(result.decisions),10)
        self.assertEqual(result.ai_mode,'gemini')
        self.assertEqual(sum(item.agent_analysis['status']=='not_reviewed' for item in result.decisions),2)
        self.assertTrue(all(not item.is_profitable for item in result.decisions if item.agent_analysis['status']=='not_reviewed'))
        self.assertTrue(again.agent_run['cached_ai_reused'])
        self.assertTrue(all(item.images_checked==0 for item in result.decisions))

    def test_api_batch_failure_is_honestly_local_and_cannot_emit_alerts(self):
        row=listing()
        with patch.object(api.marketplace_service,'search_many',return_value=([row.model_dump()],{'carousell':1},[])),patch.object(analyst,'call_json',side_effect=ClientError(429,{})),patch('notify.send_telegram_alert') as alert:
            result=api.search(api.SearchRequest(query='Labubu Macaron',pricing_mode='manual',resale_estimate=100,marketplaces=['carousell']))
        self.assertEqual(result.ai_mode,'deterministic')
        self.assertEqual(result.decisions[0].agent_analysis['status'],'local_fallback')
        self.assertFalse(result.decisions[0].is_profitable);alert.assert_not_called()

    def test_clear_form_goal_and_photo_search_skip_ai_planner(self):
        with patch.object(api,'plan_search',wraps=search_intent.plan_search) as planner,patch.object(api.marketplace_service,'search_many',return_value=([],{'carousell':0},[])):
            api.search(api.SearchRequest(query='LEGO 75192',pricing_mode='auto',marketplaces=['carousell']))
        self.assertFalse(planner.call_args.kwargs['use_ai'])

    def test_manager_clarification_stops_before_retrieving_marketplaces(self):
        plan = search_intent.SearchIntent(queries=['find a camera'], clarification='Which camera model do you want?')
        with patch.object(api, 'plan_search', return_value=plan), patch.object(api.marketplace_service, 'search_many') as retrieve:
            with self.assertRaises(HTTPException) as failure:
                api.search(api.SearchRequest(query='find a camera', pricing_mode='auto', marketplaces=['carousell']))
        retrieve.assert_not_called()
        self.assertEqual(failure.exception.status_code, 422)
        self.assertEqual(failure.exception.detail['code'], 'CLARIFICATION_REQUIRED')
        self.assertIn('agent_run', failure.exception.detail)

    def test_mismatch_and_unreviewed_offers_cannot_price_reviewed_matches(self):
        rows = [listing(id='match', price=100), listing(id='mismatch', price=10), listing(id='unreviewed', price=2000)]
        mismatch = finding(rows[1]); mismatch.relevance = 'mismatch'
        with patch.object(api.marketplace_service, 'search_many', return_value=([row.model_dump() for row in rows], {'carousell': 3}, [])), patch.object(analyst, 'call_json', return_value=analyst.Findings(findings=[finding(rows[0]), mismatch])), patch('notify.send_telegram_alert'):
            result = api.search(api.SearchRequest(query='Labubu Macaron', pricing_mode='auto', marketplaces=['carousell']))
        matched = next(item for item in result.decisions if item.listing_id == 'match')
        self.assertEqual(matched.resale_estimate_myr, 100)
        self.assertEqual(matched.resale_sample_size, 1)
        self.assertEqual(len(result.product_groups), 3)

    def test_marketplace_tools_run_concurrently_and_preserve_runtime_context(self):
        entered = {name: threading.Event() for name in ('carousell', 'lazada')}
        def adapter(name, other):
            def run(query, limit):
                entered[name].set()
                if not entered[other].wait(2):
                    raise AssertionError('Independent tools did not run concurrently')
                return []
            return run
        adapters = {name: adapter(name, other) for name, other in [('carousell', 'lazada'), ('lazada', 'carousell')]}
        with patch.dict(marketplaces.ADAPTERS, adapters), runtime.operation('parallel_test', 0) as run:
            rows, counts, errors = marketplaces.search_many('Labubu Macaron', ['carousell', 'lazada'], 12,
                intent=search_intent.SearchIntent(queries=['Labubu Macaron']))
            events = run.snapshot()['events']
        self.assertFalse(errors)
        self.assertEqual(list(counts), ['carousell', 'lazada'])
        self.assertEqual(len([item for item in events if item['status'] == 'completed']), 2)
        self.assertEqual(run.snapshot()['provider_attempts'], 0)

    def test_secondary_marketplace_failure_redacts_secrets_and_keeps_results(self):
        with patch.dict(marketplaces.ADAPTERS, {'carousell': unittest.mock.Mock(side_effect=[
                [listing().model_dump()], marketplaces.MarketplaceSearchError('provider rejected fake-1')])}):
            rows, counts, errors = marketplaces.search_many('Labubu Macaron', ['carousell'], 12,
                intent=search_intent.SearchIntent(queries=['Labubu Macaron', 'Labubu toy']))
        self.assertEqual(len(rows), 1)
        self.assertEqual(counts['carousell'], 1)
        self.assertIn('[redacted]', errors[0]['message'])
        self.assertNotIn('fake-1', errors[0]['message'])
        self.assertEqual(errors[0]['quota_system'], 'marketplace_provider')

    def test_http_search_chat_and_runtime_expose_actual_request_accounting(self):
        row = listing()
        generated = response(analyst.Findings(findings=[finding(row)]).model_dump_json())
        async def smoke():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url='http://test') as client:
                result = await client.post('/api/search', json={'query': 'Labubu Macaron', 'pricing_mode': 'manual',
                    'resale_estimate': 100, 'marketplaces': ['carousell']})
                self.assertEqual(result.status_code, 200, result.text)
                body = result.json()
                self.assertEqual(body['agent_run']['provider_attempts'], 1)
                self.assertEqual(body['agent_run']['token_usage']['total_token_count'], 25)
                self.assertEqual(body['ai_mode'], 'gemini')
                self.assertEqual(body['decisions'][0]['agent_analysis']['status'], 'ai_completed')
                chat = await client.post('/api/chat', json={'message': 'compare offers', 'context': {'query': 'Labubu Macaron'}})
                self.assertEqual(chat.status_code, 200, chat.text)
                self.assertEqual(chat.json()['agent_run']['provider_attempts'], 0)
                status = await client.get('/api/agents/runtime')
                self.assertEqual(status.status_code, 200)
                self.assertEqual(status.json()['scheduler']['configured_key_count'], 5)
                self.assertNotIn('fake-', status.text)
        with patch.object(api.marketplace_service, 'search_many', return_value=([row.model_dump()], {'carousell': 1}, [])), patch('google.genai.Client') as provider, patch('notify.send_telegram_alert'):
            provider.return_value.models.generate_content.return_value = generated
            asyncio.run(smoke())
        self.assertEqual(provider.return_value.models.generate_content.call_count, 1)

    def test_simple_chat_operations_do_not_call_gemini(self):
        for message in ('only Shopee','got any just for 250?','compare offers','explain this','watch this','refresh carousell'):
            with self.subTest(message=message),patch.object(copilot,'call_json') as model:
                result=copilot.chat(copilot.ChatRequest(message=message,context={'query':'LEGO 75192'}))
                model.assert_not_called()
                self.assertEqual(result['mode'],'local')

    def test_flexible_chat_is_cached_and_evidence_changes_invalidate(self):
        req=copilot.ChatRequest(message='Would the other option suit my needs?',context={'query':'headphones'})
        with patch.object(copilot,'call_json',return_value=copilot.ChatPlan(reply='Which option do you mean?')) as model:
            first=copilot.chat(req);copilot.chat(req)
            copilot.chat(req.model_copy(update={'context':req.context.model_copy(update={'query':'camera'})}))
        self.assertEqual(model.call_count,2)
        self.assertEqual(first['mode'],'ai')

    def test_reviewer_is_explicit_bounded_and_never_sends_alerts(self):
        row=listing()
        with patch.object(analyst,'call_json',return_value=analyst.Findings(findings=[finding(row)])) as model,patch('notify.send_telegram_alert') as alert:
            result=api.deep_review(api.ReviewRequest(query='Labubu Macaron',listings=[row]))
        self.assertEqual(model.call_args.kwargs['role'],'reviewer')
        self.assertEqual(result['statuses'][analyst.offer_id(row)],'ai_completed')
        alert.assert_not_called()

    def test_runtime_endpoint_and_health_do_not_call_any_provider_or_expose_keys(self):
        with patch('google.genai.Client') as client:
            result=api.agents_runtime();health=api.health()
        client.assert_not_called()
        self.assertTrue(health['ai_configured'])
        self.assertEqual(health['ai_mode'],'deterministic')
        self.assertEqual(result['scheduler']['configured_key_count'],5)
        self.assertNotIn('fake-',json.dumps(result))


if __name__=='__main__':unittest.main()
