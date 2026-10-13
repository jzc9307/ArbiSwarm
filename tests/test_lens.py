import base64
import io
import time
import unittest
from unittest.mock import patch, MagicMock

from PIL import Image
from fastapi.testclient import TestClient

import api
import lens
from agents import _llm
from copilot import ChatRequest, ChatContext, chat
from orchestrator import run_swarm
from schemas import Listing


def image_bytes(size=(640, 480), fmt='PNG'):
    output = io.BytesIO()
    image = Image.new('RGB', size, '#83a14d')
    image.save(output, format=fmt)
    return output.getvalue()


def identity():
    return lens.LensIdentity(name='Sony WH-1000XM5 headphones', query='Sony WH-1000XM5', similar_query='black over ear headphones', category='headphones', confidence='medium', observations=['Black over-ear design'], uncertainties=['Model label is not visible'], objects=[lens.LensObject(label='Headphones',box=[.1,.1,.9,.9])])


def listing(index=1, **updates):
    payload = dict(id=str(index),title='Sony WH-1000XM5 headphones',description='Used headphones, includes a carrying case. Please verify model label.',price=500,marketplace='carousell',source='carousell_live',source_verified=True,url=f'https://www.carousell.com.my/p/sony-headphones-{index}/',image_urls=['https://media.karousell.com/sony.jpg'])
    payload.update(updates)
    return Listing(**payload)


class LensTests(unittest.TestCase):
    def setUp(self):
        lens._references.clear();lens._identifications.clear();lens._comparisons.clear()
        self.client = TestClient(api.app)

    def scan(self):
        with patch.object(lens,'is_enabled',return_value=True), patch.object(lens,'call_json',return_value=identity()):
            return lens.identify(base64.b64encode(image_bytes()).decode())

    def test_normalizes_dimensions_and_removes_metadata(self):
        normalized=lens.normalize_image(image_bytes((2000,1000)))
        with Image.open(io.BytesIO(normalized)) as image:
            self.assertEqual(image.size,(1024,512))
            self.assertEqual(image.format,'JPEG')
            self.assertFalse(image.getexif())

    def test_rejects_invalid_and_unsupported_formats(self):
        for data in (b'not a photo', b'<svg><script/></svg>',image_bytes(fmt='GIF')):
            with self.assertRaises(lens.LensError):lens.normalize_image(data)

    def test_rejects_upload_size(self):
        with self.assertRaises(lens.LensError) as context:lens.normalize_image(b'a'*(lens.MAX_UPLOAD+1))
        self.assertEqual(context.exception.status,413)

    def test_rejects_pixel_bomb_before_conversion(self):
        with patch.object(lens,'MAX_PIXELS',100):
            with self.assertRaises(lens.LensError):lens.normalize_image(image_bytes((20,20)))

    def test_base64_and_missing_key_errors(self):
        with self.assertRaises(lens.LensError):lens.identify('!!invalid')
        with patch.object(lens,'is_enabled',return_value=False):
            with self.assertRaises(lens.LensError) as context:lens.identify(base64.b64encode(image_bytes()).decode())
            self.assertEqual(context.exception.status,503)

    def test_one_recognition_call_cached_random_references(self):
        encoded=base64.b64encode(image_bytes()).decode()
        with patch.object(lens,'is_enabled',return_value=True),patch.object(lens,'call_json',return_value=identity()) as model:
            first=lens.identify(encoded);second=lens.identify(encoded)
        self.assertEqual(model.call_count,1)
        self.assertFalse(first['cached']);self.assertTrue(second['cached'])
        self.assertNotEqual(first['reference_id'],second['reference_id'])
        self.assertNotIn('image',first)

    def test_expiry_and_removal(self):
        result=self.scan();ref=lens.get_reference(result['reference_id'])
        ref.created=time.monotonic()-lens.TTL-1
        with self.assertRaises(lens.LensError) as context:lens.get_reference(result['reference_id'])
        self.assertEqual(context.exception.status,410)
        result=self.scan();lens.forget_reference(result['reference_id'])
        with self.assertRaises(lens.LensError):lens.get_reference(result['reference_id'])
        self.assertEqual(len(lens._identifications),0)

    def test_cache_capacity(self):
        for number in range(70):lens._references[str(number)]=lens.Reference(b'a',identity(),time.monotonic())
        lens._cleanup();self.assertEqual(len(lens._references),64)

    def test_identify_failure_does_not_fabricate_a_result(self):
        with patch.object(lens,'is_enabled',return_value=True),patch.object(lens,'call_json',side_effect=RuntimeError('secret provider message')):
            with self.assertRaises(lens.LensError) as context:lens.identify(base64.b64encode(image_bytes()).decode())
        self.assertNotIn('secret',str(context.exception))
        self.assertFalse(lens._references)

    def test_scanner_concurrency_bounded(self):
        lens._scan_lock.acquire()
        try:
            with patch.object(lens,'is_enabled',return_value=True):
                with self.assertRaises(lens.LensError) as context:lens.identify(base64.b64encode(image_bytes()).decode())
                self.assertEqual(context.exception.status,429)
        finally:lens._scan_lock.release()

    def test_batch_checks_six_not_entire_board_and_ignores_invented_ids(self):
        reference=lens.Reference(image_bytes(),identity(),time.monotonic())
        matches=lens.LensBatch(matches=[lens.LensMatch(offer_id='carousell:1',status='similar',reason='Model label not visible'),lens.LensMatch(offer_id='invented',status='likely_match',reason='bad')])
        with patch.object(lens,'is_enabled',return_value=True),patch.object(lens,'_fetch_image',return_value=(image_bytes(),'image/png')) as download,patch.object(lens,'call_json',return_value=matches) as model:
            result=lens.compare(reference,[listing(i) for i in range(1,15)],'Sony WH-1000XM5')
        self.assertEqual(download.call_count,6);self.assertEqual(model.call_count,1)
        self.assertEqual(result['matches']['carousell:1'].status,'similar')
        self.assertNotIn('invented',result['matches'])
        self.assertEqual(result['matches']['carousell:14'].status,'unverified')

    def test_comparison_cache_reuses_image_call(self):
        reference=lens.Reference(image_bytes(),identity(),time.monotonic())
        batch=lens.LensBatch(matches=[lens.LensMatch(offer_id='carousell:1',status='likely_match',reason='Design consistent')])
        with patch.object(lens,'is_enabled',return_value=True),patch.object(lens,'_fetch_image',return_value=(image_bytes(),'image/png')),patch.object(lens,'call_json',return_value=batch) as model:
            lens.compare(reference,[listing()],'Sony WH-1000XM5')
            second=lens.compare(reference,[listing()],'Sony WH-1000XM5')
            self.assertEqual(model.call_count,1)
            lens.compare(reference,[listing()],'Sony WH-1000XM5 white')
            self.assertEqual(model.call_count,2)
        self.assertTrue(second['cached'])

    def test_failed_or_unusable_photos_stay_unverified(self):
        reference=lens.Reference(image_bytes(),identity(),time.monotonic())
        with patch.object(lens,'is_enabled',return_value=True),patch.object(lens,'_fetch_image',return_value=None),patch.object(lens,'call_json') as model:
            result=lens.compare(reference,[listing()],'Sony')
            model.assert_not_called()
        self.assertEqual(result['checked'],0)
        self.assertEqual(result['matches']['carousell:1'].status,'unverified')
        with patch.object(lens,'is_enabled',return_value=True),patch.object(lens,'_fetch_image',return_value=(image_bytes(),'image/png')),patch.object(lens,'call_json',side_effect=RuntimeError('quota')):
            result=lens.compare(reference,[listing()],'Sony')
        self.assertEqual(result['checked'],0)

    def test_no_listing_agent_ai_calls_in_lens_cost_aware_path(self):
        with patch('agents.context_analyst.call_json') as context,patch('agents.vision_authenticator.call_json') as vision,patch('agents.lead_strategist.call_json') as strategist:
            decision,_,visual=run_swarm(listing(),900,include_evidence=True,cost_aware=True)
        context.assert_not_called();vision.assert_not_called();strategist.assert_not_called()
        self.assertIsNone(visual.consistency_score)

    def test_upload_route_json_validation_and_success(self):
        self.assertEqual(self.client.post('/api/lens/identify',content='invalid').status_code,422)
        with patch.object(lens,'is_enabled',return_value=True),patch.object(lens,'call_json',return_value=identity()):
            response=self.client.post('/api/lens/identify',json={'image_base64':base64.b64encode(image_bytes()).decode()})
        self.assertEqual(response.status_code,200)
        self.assertIn('reference_id',response.json())
        self.assertNotIn('image_base64',response.json())

    def test_search_expired_reference_rejected_before_marketplace_requests(self):
        with patch.object(api.marketplace_service,'search_many') as provider:
            response=self.client.post('/api/search',json={'query':'Sony headphones','pricing_mode':'auto','lens_reference_id':'a'*32})
        self.assertEqual(response.status_code,410);provider.assert_not_called()

    def test_photo_demo_search_rejected(self):
        response=self.client.post('/api/search',json={'query':'Sony headphones','pricing_mode':'auto','source_mode':'demo','lens_reference_id':'a'*32})
        self.assertEqual(response.status_code,422)

    def test_search_wires_reference_matches_and_prevents_alert(self):
        result=self.scan()
        item=listing()
        visual={'matches':{'carousell:1':lens.LensMatch(offer_id='carousell:1',status='likely_match',reason='Visible design consistent')},'checked':1,'usage':{},'cached':False,'note':'Provisional'}
        with patch.object(api,'plan_search',return_value=None),patch.object(api.marketplace_service,'search_many',return_value=([item.model_dump()],{'carousell':1},[])),patch.object(lens,'compare',return_value=visual) as compare,patch('notify.send_telegram_alert') as alert:
            response=self.client.post('/api/search',json={'query':'Sony WH-1000XM5','pricing_mode':'manual','resale_estimate':2000,'marketplaces':['carousell'],'lens_reference_id':result['reference_id']})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json();self.assertEqual(data['lens_context']['checked'],1)
        self.assertEqual(data['decisions'][0]['lens_match']['status'],'likely_match')
        self.assertFalse(data['decisions'][0]['is_profitable']);alert.assert_not_called()
        self.assertIn('exact SKU',data['decisions'][0]['reasoning'])
        compare.assert_called_once()

    def test_chat_reference_followup_and_unrelated_search(self):
        context=ChatContext(query='Sony WH-1000XM5',lens_summary='Black headphones, model label unclear',lens_reference_available=True)
        with patch('copilot.is_enabled',return_value=False):
            same=chat(ChatRequest(message='find this in white under RM700',context=context))
            other=chat(ChatRequest(message='find a Nintendo Switch',context=context))
        self.assertTrue(same['action']['use_reference'])
        self.assertIn('Sony WH-1000XM5',same['action']['query'])
        self.assertFalse(other['action']['use_reference'])

    def test_visually_different_prices_cannot_value_likely_matches(self):
        result=self.scan()
        items=[listing().model_copy(update={'id':str(i),'price':price}) for i,price in [(1,500),(2,550),(3,20)]]
        visual={'matches':{f'carousell:{i}':lens.LensMatch(offer_id=f'carousell:{i}',status='different' if i==3 else 'likely_match',reason='Test visual evidence') for i in (1,2,3)},'checked':3,'usage':{},'cached':False,'note':'Provisional'}
        with patch.object(api,'plan_search',return_value=None),patch.object(api.marketplace_service,'search_many',return_value=([item.model_dump() for item in items],{'carousell':3},[])),patch.object(lens,'compare',return_value=visual):
            response=self.client.post('/api/search',json={'query':'Sony WH-1000XM5','pricing_mode':'auto','marketplaces':['carousell'],'lens_reference_id':result['reference_id']})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json();matches=[item for item in data['decisions'] if item['lens_match']['status']=='likely_match']
        self.assertEqual(len(matches),2)
        self.assertTrue(all(item['resale_estimate_myr']==525 for item in matches))
        self.assertTrue(all(item['resale_confidence']=='low' for item in matches))
        self.assertEqual(len(data['product_groups']),2)

    def test_local_chat_explains_only_actual_visual_evidence(self):
        context=ChatContext(query='Sony headphones',lens_summary='black headphones',offers=[{'offer_id':'carousell:1','title':'Sony headphones','marketplace':'carousell','price':500,'lens_match':{'status':'similar','reason':'Model label unavailable'}}])
        with patch('copilot.is_enabled',return_value=False):answer=chat(ChatRequest(message='Which matches my photo?',context=context))
        self.assertIn('Model label unavailable',answer['reply'])
        self.assertNotIn('authentic product',answer['reply'])


if __name__=='__main__':unittest.main()
