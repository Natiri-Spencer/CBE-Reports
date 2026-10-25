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


if __name__ == "__main__":
    unittest.main()
