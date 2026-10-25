"""Canonical CBC score-band rules used by marks and reports."""


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
    """Return the configured band for a score from 0 through 100."""
    for minimum, maximum, label in GRADE_BANDS:
        if minimum <= score <= maximum:
            return label
    return "Invalid"
