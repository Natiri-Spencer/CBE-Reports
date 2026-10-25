"""Canonical CBC score-band rules used by marks and reports."""
import math


GRADE_BANDS = (
    (0, 10, "BE2"),
    (11, 20, "BE1"),
    (21, 30, "AE2"),
    (31, 42, "AE1"),
    (43, 53, "ME2"),
    (54, 67, "ME1"),
    (68, 90, "EE2"),
    (91, 100, "EE1"),
)


def grade_comment(score: float) -> str:
    """Grade valid scores using the marks form's nearest-whole-mark rounding."""
    if not math.isfinite(score) or not 0 <= score <= 100:
        return "Invalid"
    score = round(score)
    for minimum, maximum, label in GRADE_BANDS:
        if minimum <= score <= maximum:
            return label
    return "Invalid"
