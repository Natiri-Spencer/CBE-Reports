import unittest

from app.services.grading import grade_comment


class GradeCommentTests(unittest.TestCase):
    def test_every_band_boundary(self):
        expected = {
            0: "BE2", 10: "BE2", 11: "BE1", 20: "BE1",
            21: "AE2", 30: "AE2", 31: "AE1", 42: "AE1",
            43: "ME2", 53: "ME2", 54: "ME1", 67: "ME1",
            68: "EE2", 90: "EE2", 91: "EE1", 100: "EE1",
        }
        for score, band in expected.items():
            with self.subTest(score=score):
                self.assertEqual(grade_comment(score), band)

    def test_out_of_range_scores_are_invalid(self):
        self.assertEqual(grade_comment(-1), "Invalid")
        self.assertEqual(grade_comment(101), "Invalid")

    def test_fractional_rounding_and_non_finite_scores(self):
        for score, expected in ((0, "BE2"), (0.01, "BE2"), (10.4, "BE2"), (10.6, "BE1"),
                                (42.4, "AE1"), (42.6, "ME2"), (67.8, "EE2"), (90.6, "EE1"),
                                (10.5, "BE2"), (53.5, "ME1")):
            with self.subTest(score=score):
                self.assertEqual(grade_comment(score), expected)
        for score in (-0.1, 100.1, float("inf"), float("-inf"), float("nan")):
            self.assertEqual(grade_comment(score), "Invalid")


if __name__ == "__main__":
    unittest.main()
