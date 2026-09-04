"""Family age labels evaluated at the photo capture date."""

from __future__ import annotations

from datetime import date, datetime


FAMILY_BIRTHDAYS = {
    "H": date(1978, 6, 1),
    "A": date(1978, 9, 22),
    "R": date(2012, 12, 2),
}

FAMILY_DISPLAY_NAMES = {
    "H": "His",
    "A": "Ah-ca",
    "R": "Rin",
}


def _completed_years(birth: date, captured: date) -> int:
    return captured.year - birth.year - ((captured.month, captured.day) < (birth.month, birth.day))


def _completed_months(birth: date, captured: date) -> int:
    months = (captured.year - birth.year) * 12 + captured.month - birth.month
    if captured.day < birth.day:
        months -= 1
    return max(0, months)


def format_family_age(person: str, birth: date, captured: date) -> str | None:
    if captured < birth:
        return None
    months = _completed_months(birth, captured)
    years = _completed_years(birth, captured)
    display_name = FAMILY_DISPLAY_NAMES.get(person, person)
    if person == "R" and years < 3:
        return f"{display_name} {years}y {months - years * 12}m"
    return f"{display_name} {years}y"


def family_age_labels(capture_date: datetime | date | None) -> tuple[str, ...]:
    if capture_date is None:
        return ()
    captured = capture_date.date() if isinstance(capture_date, datetime) else capture_date
    labels = []
    for person, birth in FAMILY_BIRTHDAYS.items():
        label = format_family_age(person, birth, captured)
        if label is not None:
            labels.append(label)
    return tuple(labels)
