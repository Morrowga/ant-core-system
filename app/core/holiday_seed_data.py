"""Starter holiday seed data — deliberately minimal and conservative.

Only includes dates that are fixed and unambiguous on the Gregorian
calendar (e.g. Jan 1, a country's legally-fixed National Day). Movable/lunar
holidays (Lunar New Year, Thingyan, Eid, Diwali, Easter-based holidays,
"Happy Monday"-style shifted weekday holidays, Thanksgiving, etc.) are NOT
included here -- their exact date shifts every year and often depends on
official government announcement, moon sighting, or a fixed weekday
calculation, so getting one wrong here would be worse than not having it at
all. Owners add those (and any other country-specific dates) themselves via
the "Add holiday" UI, using whatever authoritative source they trust for
their country/year.

This file is meant to be expanded over time as you verify real dates for
your actual company's countries -- treat it as a starting scaffold, not a
complete calendar. The 2026 dates below were generated from general
knowledge of each country's fixed-date public holidays, not independently
verified against an official government source for every country -- worth
spot-checking the less-common ones (Myanmar, Bangladesh, UAE, Russia)
before relying on this for real payroll/leave decisions.
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
        "myanmar": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-01-04", "name": "Independence Day"},
            {"date": "2026-02-12", "name": "Union Day"},
            {"date": "2026-03-02", "name": "Peasants' Day"},
            {"date": "2026-03-27", "name": "Armed Forces Day"},
            {"date": "2026-07-19", "name": "Martyrs' Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
        ],
        "thailand": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-04-06", "name": "Chakri Memorial Day"},
            {"date": "2026-04-13", "name": "Songkran"},
            {"date": "2026-04-14", "name": "Songkran"},
            {"date": "2026-04-15", "name": "Songkran"},
            {"date": "2026-05-04", "name": "Coronation Day"},
            {"date": "2026-07-28", "name": "King's Birthday"},
            {"date": "2026-08-12", "name": "Queen Mother's Birthday / Mother's Day"},
            {"date": "2026-10-13", "name": "King Bhumibol Memorial Day"},
            {"date": "2026-10-23", "name": "Chulalongkorn Day"},
            {"date": "2026-12-05", "name": "King Bhumibol's Birthday / Father's Day"},
            {"date": "2026-12-10", "name": "Constitution Day"},
            {"date": "2026-12-31", "name": "New Year's Eve"},
        ],
        "vietnam": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-04-30", "name": "Reunification Day"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-09-02", "name": "National Day"},
        ],
        "indonesia": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-08-17", "name": "Independence Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
        ],
        "singapore": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-08-09", "name": "National Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
        ],
        "malaysia": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-08-31", "name": "Merdeka Day (National Day)"},
            {"date": "2026-09-16", "name": "Malaysia Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
        ],
        "philippines": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-04-09", "name": "Day of Valor"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-06-12", "name": "Independence Day"},
            {"date": "2026-08-21", "name": "Ninoy Aquino Day"},
            {"date": "2026-11-30", "name": "Bonifacio Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
            {"date": "2026-12-30", "name": "Rizal Day"},
        ],
        "hong_kong": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-07-01", "name": "HKSAR Establishment Day"},
            {"date": "2026-10-01", "name": "National Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
            {"date": "2026-12-26", "name": "Boxing Day"},
        ],
        "china": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-10-01", "name": "National Day"},
            {"date": "2026-10-02", "name": "National Day (Golden Week)"},
            {"date": "2026-10-03", "name": "National Day (Golden Week)"},
        ],
        "taiwan": [
            {"date": "2026-01-01", "name": "Founding Day / New Year's Day"},
            {"date": "2026-02-28", "name": "Peace Memorial Day"},
            {"date": "2026-04-04", "name": "Children's Day"},
            {"date": "2026-10-10", "name": "National Day (Double Ten Day)"},
        ],
        "japan": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-02-11", "name": "National Foundation Day"},
            {"date": "2026-02-23", "name": "Emperor's Birthday"},
            {"date": "2026-04-29", "name": "Showa Day"},
            {"date": "2026-05-03", "name": "Constitution Memorial Day"},
            {"date": "2026-05-04", "name": "Greenery Day"},
            {"date": "2026-05-05", "name": "Children's Day"},
            {"date": "2026-08-11", "name": "Mountain Day"},
            {"date": "2026-11-03", "name": "Culture Day"},
            {"date": "2026-11-23", "name": "Labour Thanksgiving Day"},
        ],
        "south_korea": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-03-01", "name": "Independence Movement Day"},
            {"date": "2026-05-05", "name": "Children's Day"},
            {"date": "2026-06-06", "name": "Memorial Day"},
            {"date": "2026-08-15", "name": "Liberation Day"},
            {"date": "2026-10-03", "name": "National Foundation Day"},
            {"date": "2026-10-09", "name": "Hangeul Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
        ],
        "india": [
            {"date": "2026-01-26", "name": "Republic Day"},
            {"date": "2026-08-15", "name": "Independence Day"},
            {"date": "2026-10-02", "name": "Gandhi Jayanti"},
        ],
        "bangladesh": [
            {"date": "2026-02-21", "name": "International Mother Language Day"},
            {"date": "2026-03-26", "name": "Independence Day"},
            {"date": "2026-04-14", "name": "Pohela Boishakh (Bengali New Year)"},
            {"date": "2026-12-16", "name": "Victory Day"},
        ],
        "uae": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-12-02", "name": "UAE National Day"},
            {"date": "2026-12-03", "name": "UAE National Day"},
        ],
        "uk": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
            {"date": "2026-12-26", "name": "Boxing Day"},
        ],
        "france": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-05-08", "name": "Victory in Europe Day"},
            {"date": "2026-07-14", "name": "Bastille Day"},
            {"date": "2026-08-15", "name": "Assumption Day"},
            {"date": "2026-11-01", "name": "All Saints' Day"},
            {"date": "2026-11-11", "name": "Armistice Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
        ],
        "germany": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-10-03", "name": "German Unity Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
            {"date": "2026-12-26", "name": "Boxing Day"},
        ],
        "russia": [
            {"date": "2026-01-01", "name": "New Year's Holiday"},
            {"date": "2026-01-02", "name": "New Year's Holiday"},
            {"date": "2026-01-07", "name": "Orthodox Christmas"},
            {"date": "2026-02-23", "name": "Defender of the Fatherland Day"},
            {"date": "2026-03-08", "name": "International Women's Day"},
            {"date": "2026-05-01", "name": "Spring and Labour Day"},
            {"date": "2026-05-09", "name": "Victory Day"},
            {"date": "2026-06-12", "name": "Russia Day"},
            {"date": "2026-11-04", "name": "Unity Day"},
        ],
        "usa": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-06-19", "name": "Juneteenth"},
            {"date": "2026-07-04", "name": "Independence Day"},
            {"date": "2026-11-11", "name": "Veterans Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
        ],
        "brazil": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-04-21", "name": "Tiradentes Day"},
            {"date": "2026-05-01", "name": "Labour Day"},
            {"date": "2026-09-07", "name": "Independence Day"},
            {"date": "2026-10-12", "name": "Our Lady of Aparecida"},
            {"date": "2026-11-02", "name": "All Souls' Day"},
            {"date": "2026-11-15", "name": "Republic Day"},
            {"date": "2026-11-20", "name": "Black Awareness Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
        ],
        "australia": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-01-26", "name": "Australia Day"},
            {"date": "2026-04-25", "name": "Anzac Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
            {"date": "2026-12-26", "name": "Boxing Day"},
        ],
        "new_zealand": [
            {"date": "2026-01-01", "name": "New Year's Day"},
            {"date": "2026-01-02", "name": "Day after New Year's Day"},
            {"date": "2026-02-06", "name": "Waitangi Day"},
            {"date": "2026-04-25", "name": "Anzac Day"},
            {"date": "2026-12-25", "name": "Christmas Day"},
            {"date": "2026-12-26", "name": "Boxing Day"},
        ],
    },
}