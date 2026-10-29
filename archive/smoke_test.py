"""One-date smoke test for the Booking scraper."""
import asyncio

import booking_property_chunked_any_vfix as m

m.HORIZON_DAYS = 0  # today only
m.CHUNK_SIZE = 1
m.MAX_CONCURRENCY = 1
m.VERBOSE = True
m.SAVE_DEBUG_SHOTS = True

if __name__ == "__main__":
    asyncio.run(m.run())
