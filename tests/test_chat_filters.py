import unittest
from unittest.mock import patch
import copilot


class ChatFilterTests(unittest.TestCase):
    def chat(self,message,**changes):
        context = {'query':'Liverpool jersey 26/27 size M','max_purchase_price':300,'marketplaces':['carousell','shopee'],'offers':[
            {'offer_id':'c1','title':'Jersey M','marketplace':'carousell','price':260},
            {'offer_id':'s1','title':'Jersey M','marketplace':'shopee','price':230},
        ],**changes}
        with patch.object(copilot,'is_enabled',return_value=False):
            return copilot.chat(copilot.ChatRequest(message=message,context=context))

    def test_natural_budget_question_narrows_saved_board(self):
        result = self.chat('got any just for 250?')
        self.assertEqual(result['action']['type'],'filter')
        self.assertEqual(result['action']['max_price'],250)
        self.assertEqual(result['offer_ids'],['s1'])
        self.assertIn('1 saved offer',result['reply'])
        self.assertFalse(result['auto_execute'])

    def test_market_only_follow_up(self):
        result = self.chat('compare only Shopee')
        self.assertEqual(result['action']['marketplaces'],['shopee'])
        self.assertEqual(result['offer_ids'],['s1'])

    def test_empty_filter_does_not_invent_or_start_a_crawl(self):
        result = self.chat('anything for 100?')
        self.assertEqual(result['offer_ids'],[])
        self.assertIn('No saved offers',result['reply'])
        self.assertEqual(result['action']['type'],'filter')

    def test_reset_can_restore_previously_hidden_offers(self):
        result = self.chat('show everything again',visible_offer_ids=['s1'],visible_marketplaces=['shopee'],view_max_price=240)
        self.assertTrue(result['action']['reset'])
        self.assertEqual(result['offer_ids'],['s1','c1'])

    def test_comparison_respects_visible_board(self):
        result = self.chat('cheapest please',visible_offer_ids=['s1'])
        self.assertEqual(result['offer_ids'],['s1'])

    def test_follow_up_preserves_active_market_filter(self):
        result = self.chat('how about 250?',visible_marketplaces=['carousell'])
        self.assertEqual(result['action']['marketplaces'],['carousell'])
        self.assertEqual(result['offer_ids'],[])

    def test_unknown_message_asks_clarification_not_generic_intro(self):
        result = self.chat('hmm this one maybe you know?')
        self.assertIn("couldn't reliably interpret",result['reply'])
        self.assertIsNone(result['action'])

    def test_season_follow_up_is_not_mistaken_for_a_price(self):
        result = self.chat('what about 26/27 season?')
        self.assertIsNone(result['action'])
