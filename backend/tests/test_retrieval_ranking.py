import unittest

from incidentiq.services.ranking import reciprocal_rank_fusion


class ReciprocalRankFusionTests(unittest.TestCase):
    def test_shared_result_ranks_above_single_list_results(self):
        ranking = reciprocal_rank_fusion([["a", "b"], ["b", "c"]])
        self.assertEqual([item_id for item_id, _ in ranking], ["b", "a", "c"])

    def test_empty_and_duplicate_rankings(self):
        ranking = reciprocal_rank_fusion([[], ["a"], ["a"]])
        self.assertEqual([item_id for item_id, _ in ranking], ["a"])
        self.assertAlmostEqual(ranking[0][1], 2 / 61)
