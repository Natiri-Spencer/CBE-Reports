from datetime import date


TERM_SCHEDULE = [
    {
        "term": 1,
        "months": "January to April",
        "instruction_weeks": 14,
        "holiday_after_weeks": 3,
        "holiday_after": "After Term 1",
    },
    {
        "term": 2,
        "months": "May to August",
        "instruction_weeks": 13,
        "holiday_after_weeks": 3,
        "holiday_after": "After Term 2",
    },
    {
        "term": 3,
        "months": "September to November",
        "instruction_weeks": 10,
        "holiday_after_weeks": 4,
        "holiday_after": "December holiday (1 month)",
    },
]


def current_academic_period(on_date: date | None = None) -> tuple[int, int]:
    on_date = on_date or date.today()
    if on_date.month <= 4:
        term = 1
    elif on_date.month <= 8:
        term = 2
    else:
        # December is the holiday period; default to the most recent term.
        term = 3
    return on_date.year, term


def validate_term(term: int) -> int:
    if term not in (0, 1, 2, 3):
        raise ValueError("Term must be 1, 2, or 3; term 0 is reserved for legacy records")
    return term
