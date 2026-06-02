TYPE_REGULAR = "regular"
TYPE_SPECIAL_NON_WORKING = "special_non_working"
TYPE_SPECIAL_WORKING = "special_working"
TYPE_COMPANY = "company"
TYPE_LOCAL = "local"

HOLIDAY_TYPE_CHOICES = [
    (TYPE_REGULAR, "Regular Holiday"),
    (TYPE_SPECIAL_NON_WORKING, "Special (Non-Working)"),
    (TYPE_SPECIAL_WORKING, "Special (Working)"),
    (TYPE_COMPANY, "Company Holiday"),
    (TYPE_LOCAL, "Local Holiday"),
]
HOLIDAY_TYPE_VALUES = {c[0] for c in HOLIDAY_TYPE_CHOICES}

SOURCE_SYSTEM_DEFAULT = "system_default"
SOURCE_COMPANY = "company"
SOURCE_CHOICES = [
    (SOURCE_SYSTEM_DEFAULT, "System Default"),
    (SOURCE_COMPANY, "Company"),
]

# Resolution priority when multiple holidays share one date (lower = higher priority).
TYPE_PRIORITY = {
    TYPE_REGULAR: 0,
    TYPE_SPECIAL_NON_WORKING: 1,
    TYPE_LOCAL: 2,
    TYPE_COMPANY: 3,
    TYPE_SPECIAL_WORKING: 4,
}
