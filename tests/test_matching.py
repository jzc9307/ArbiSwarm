"""Adversarial identity/valuation regressions; no live marketplace or AI calls."""
import unittest
from unittest.mock import patch

import api
from filters import hard_filter
from intelligence import group_listings, profile_variant
from tests.test_core import listing


class ProductIdentityTests(unittest.TestCase):
    def test_exact_set_rejects_figures_accessories_small_and_wrong_codes(self):
        titles = [
            'LEGO 75192 UCS Millennium Falcon',
            'LEGO 75192 Han Solo minifigure only',
            'LEGO 75192 full set LED lighting kit',
            'LEGO 75192 mini Millennium Falcon',
            'LEGO 75105 Millennium Falcon',
            'LEGO 75192 incomplete missing parts',
            'Millennium Falcon building set',
        ]
        rows = [listing(id=str(index), title=title, description='LEGO 75192 search keywords') for index, title in enumerate(titles)]
        kept, removed = hard_filter(rows, query='LEGO 75192', max_price=4000)
        self.assertEqual([row.id for row in kept], ['0'])
        self.assertEqual(len(removed), 6)
        self.assertTrue(all(row['reason'] for row in removed))

    def test_included_figures_do_not_make_a_complete_set_figure_only(self):
        title = 'LEGO 75192 UCS Millennium Falcon with 8 minifigures'
        kept, _ = hard_filter([listing(title=title)], query='LEGO 75192')
        self.assertEqual(len(kept), 1)
        self.assertEqual(profile_variant(title).kind, 'building_set')

    def test_explicit_minifigure_search_still_works(self):
        kept, _ = hard_filter([listing(title='LEGO 75192 minifigure Han Solo')], query='LEGO 75192 minifigure')
        self.assertEqual(len(kept), 1)

    def test_related_mode_never_merges_models_or_product_types(self):
        titles = ['LEGO 75192 UCS Millennium Falcon', 'LEGO 75105 Millennium Falcon', 'LEGO 75192 minifigure only', 'LEGO 75192 display case']
        rows = [listing(id=str(index), title=title) for index,title in enumerate(titles)]
        self.assertEqual(len(group_listings(rows, 'LEGO Falcon')), 4)

    def test_description_cannot_override_wrong_title_set(self):
        kept, removed = hard_filter([listing(title='LEGO 75375 Millennium Falcon', description='Also fits LEGO 75192')], query='LEGO 75192')
        self.assertEqual(kept, [])
        self.assertIn('set number', removed[0]['reason'])

    def test_figure_only_description_cannot_borrow_complete_set_valuation(self):
        full = listing(id='full',title='LEGO 75192 UCS Millennium Falcon',price=3000)
        figure = listing(id='fig',title='LEGO 75192 UCS Millennium Falcon',price=100,description='Minifigures only. Set sold separately.')
        kept, removed = hard_filter([full,figure],query='LEGO 75192',max_price=4000)
        self.assertEqual([row.id for row in kept],['full'])
        self.assertIn('seller description',removed[0]['reason'])
        self.assertEqual(len(group_listings([full,figure],'LEGO 75192')),2)

    def test_piece_counts_are_not_model_ids(self):
        self.assertEqual(profile_variant('LEGO 75192 10000 pieces building set').model_ids, ('75192',))

    def test_compact_lego_code_and_big_version_intent(self):
        kept, removed = hard_filter([listing(title='LEGO StarWars UCS MillenniumFalcon 75192')],query='LEGO75192 big version')
        self.assertEqual(len(kept),1)
        self.assertEqual(removed,[])

    def test_missing_figures_is_incomplete_not_a_full_set(self):
        self.assertEqual(profile_variant('LEGO 75192 without minifigures').kind,'incomplete')

    def test_seasons_and_audiences_cannot_share_jersey_valuations(self):
        titles = ['Liverpool Home jersey 26/27 Men', 'Liverpool Home jersey 25/26 Men', 'Liverpool Home jersey 26/27 Kids', 'Liverpool Away jersey 26/27 Men']
        rows = [listing(id=str(index),title=title) for index,title in enumerate(titles)]
        self.assertEqual(len(group_listings(rows,'Liverpool jersey')), 4)

    def test_requested_season_and_size_must_be_present(self):
        rows = [listing(id='1',title='Liverpool Home jersey 26/27 size M'), listing(id='2',title='Liverpool Home jersey 25/26 size M',description='Liverpool 26/27 M'), listing(id='3',title='Liverpool Home jersey 26/27 size L')]
        kept, removed = hard_filter(rows, query='Liverpool jersey 26/27 size M')
        self.assertEqual([row.id for row in kept], ['1'])
        self.assertEqual(len(removed),2)

    def test_no_silent_set_number_correction(self):
        kept, _ = hard_filter([listing(title='LEGO 75192 UCS Millennium Falcon')], query='LEGO 71592')
        self.assertEqual(kept, [])


class ValuationGuardTests(unittest.TestCase):
    def run_search(self, rows, match_mode='exact'):
        with patch.object(api.marketplace_service,'search_many',return_value=([row.model_dump(mode='json') for row in rows], {'carousell':len(rows)}, [])), patch.object(api.config,'GEMINI_API_KEY',''), patch.object(api.config,'GEMINI_API_KEYS',()), patch.object(api.notify,'send_telegram_alert'):
            return api.search(api.SearchRequest(query='LEGO 75192', pricing_mode='auto', max_purchase_price=4000, match_mode=match_mode))

    def test_figures_cannot_pollute_full_set_median(self):
        rows = [listing(id=str(index),title='LEGO 75192 UCS Millennium Falcon',price=price) for index,price in enumerate([2800,2900,3000,3100,3200])]
        rows += [listing(id='figure',title='LEGO 75192 minifigure only',price=155)]
        result = self.run_search(rows)
        self.assertEqual(len(result.decisions),5)
        self.assertTrue(all(row.resale_estimate_myr == 3000 for row in result.decisions))
        self.assertEqual(len(result.discarded),1)

    def test_extreme_price_outlier_never_becomes_899_percent_buy_signal(self):
        rows = [listing(id=str(index),title='LEGO 75192 UCS Millennium Falcon',price=price) for index,price in enumerate([155,2800,2900,3000,3100,3200])]
        result = self.run_search(rows)
        bargain = next(row for row in result.decisions if row.price == 155)
        self.assertFalse(bargain.is_profitable)
        self.assertIn('Confirm the exact item',bargain.reasoning)
        self.assertIn('hypothetical',bargain.reasoning)
        self.assertIn('does not prove a fake',bargain.reasoning)

    def test_related_accessory_has_its_own_low_confidence_price(self):
        result = self.run_search([listing(id='set',title='LEGO 75192 UCS Millennium Falcon',price=3000),listing(id='led',title='LEGO 75192 LED lighting kit',price=100)], match_mode='related')
        accessory = next(row for row in result.decisions if row.variant_kind == 'accessory')
        self.assertEqual(accessory.resale_estimate_myr,100)
        self.assertEqual(accessory.resale_sample_size,1)
        self.assertFalse(accessory.is_profitable)


if __name__ == '__main__':
    unittest.main()
