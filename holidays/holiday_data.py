"""Pure-data default Philippine holiday catalog. No Django imports.

Fixed-date holidays can be re-seeded each year via `seed_holidays`.
Movable/proclaimed holidays (Maundy Thursday, Good Friday, Black Saturday,
Chinese New Year, Eid, etc.) are explicit per year and MUST be updated yearly.
"""
import datetime

from .constants import (
    TYPE_REGULAR, TYPE_SPECIAL_NON_WORKING,
)

# year -> list of (name, (month, day), type)
_RAW = {
    2026: [
        ("New Year's Day", (1, 1), TYPE_REGULAR),
        ("Araw ng Kagitingan", (4, 9), TYPE_REGULAR),
        ("Maundy Thursday", (4, 2), TYPE_REGULAR),
        ("Good Friday", (4, 3), TYPE_REGULAR),
        ("Labor Day", (5, 1), TYPE_REGULAR),
        ("Independence Day", (6, 12), TYPE_REGULAR),
        ("National Heroes Day", (8, 31), TYPE_REGULAR),
        ("Bonifacio Day", (11, 30), TYPE_REGULAR),
        ("Christmas Day", (12, 25), TYPE_REGULAR),
        ("Rizal Day", (12, 30), TYPE_REGULAR),
        ("Chinese New Year", (2, 17), TYPE_SPECIAL_NON_WORKING),
        ("EDSA People Power Anniversary", (2, 25), TYPE_SPECIAL_NON_WORKING),
        ("Black Saturday", (4, 4), TYPE_SPECIAL_NON_WORKING),
        ("Ninoy Aquino Day", (8, 21), TYPE_SPECIAL_NON_WORKING),
        ("All Saints' Day", (11, 1), TYPE_SPECIAL_NON_WORKING),
        ("Feast of the Immaculate Conception", (12, 8), TYPE_SPECIAL_NON_WORKING),
        ("Last Day of the Year", (12, 31), TYPE_SPECIAL_NON_WORKING),
    ],
}

DEFAULT_PH_HOLIDAYS = {
    year: [
        {"name": name, "date": datetime.date(year, m, d), "type": htype}
        for (name, (m, d), htype) in entries
    ]
    for year, entries in _RAW.items()
}


def holidays_for_year(year):
    """Return a list of {name, date, type} dicts for the given year (or [])."""
    return list(DEFAULT_PH_HOLIDAYS.get(year, []))
