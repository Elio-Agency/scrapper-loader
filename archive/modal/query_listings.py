"""Query listings in the DuckDB file pointed at by DUCKDB_PATH."""
import duckdb

from config import duckdb_path

con = duckdb.connect(str(duckdb_path()))
print(
    con.execute(
        """
        SELECT COUNT(*) AS rows, COUNT(DISTINCT property_url) AS unique_urls
        FROM search_listings
        """
    ).fetchdf()
)
print(
    con.execute(
        """
        SELECT check_in, check_out, title, stars, price_current, distance, room_type
        FROM search_listings
        LIMIT 10
        """
    ).fetchdf()
)
