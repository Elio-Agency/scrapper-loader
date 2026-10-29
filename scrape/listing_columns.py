"""Shared output columns for search listings + property-page extras."""

# Search-card scrape (existing)
LISTING_COLS = [
    "check_in",
    "check_out",
    "title",
    "property_url",
    "room_type",
    "bed_info",
    "price_original",
    "price_current",
    "taxes_fees",
    "review_word",
    "review_score",
    "review_count",
    "distance",
    "neighbourhood",
    "availability_hint",
    "rooms_left_hint",
    "sponsored",
    "genius",
    "stars",
    "nights",
    "adults",
    "captured_at",
]

# Hotel page (address + amenities)
PROPERTY_COLS = [
    "address",
    "street",
    "postal_code",
    "city",
    "country",
    "popular_facilities",
    "amenities",
]

ALL_COLS = LISTING_COLS + PROPERTY_COLS
