"""Starter holiday seed data — deliberately minimal and conservative.

Only includes dates that are universally fixed and unambiguous (e.g. Jan 1).
Movable/lunar holidays (Lunar New Year, Thingyan, Eid, Diwali, etc.) are
NOT included here -- their exact Gregorian date shifts every year and often
depends on official government announcement or moon sighting, so getting
one wrong here would be worse than not having it at all. Owners add those
(and any other country-specific dates) themselves via the "Add holiday" UI,
using whatever authoritative source they trust for their country/year.

This file is meant to be expanded over time as you verify real dates for
your actual company's countries -- treat it as a starting scaffold, not a
complete calendar.
"""

# Supported country codes, shown in the Settings/employee-assignment
# dropdowns. Matches the countries already covered by the timezone list,
# for consistency.
SUPPORTED_COUNTRIES = [
    ("myanmar", "Myanmar"),
    ("thailand", "Thailand"),
    ("vietnam", "Vietnam"),
    ("indonesia", "Indonesia"),
    ("singapore", "Singapore"),
    ("malaysia", "Malaysia"),
    ("philippines", "Philippines"),
    ("hong_kong", "Hong Kong"),
    ("china", "China"),
    ("taiwan", "Taiwan"),
    ("japan", "Japan"),
    ("south_korea", "South Korea"),
    ("india", "India"),
    ("bangladesh", "Bangladesh"),
    ("uae", "UAE"),
    ("uk", "UK"),
    ("france", "France"),
    ("germany", "Germany"),
    ("russia", "Russia"),
    ("usa", "USA"),
    ("brazil", "Brazil"),
    ("australia", "Australia"),
    ("new_zealand", "New Zealand"),
]

# year -> country_code -> list of {date, name}. "all" is not a real country,
# it's reserved for company-wide custom holidays (added via the UI, not
# seeded here).
BUILTIN_HOLIDAYS: dict[int, dict[str, list[dict]]] = {
    2026: {
        code: [{"date": "2026-01-01", "name": "New Year's Day"}]
        for code, _ in SUPPORTED_COUNTRIES
    },
}