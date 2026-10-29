"""Query Milan listings in DuckDB without shell-quoting pain."""
import duckdb

from config import duckdb_path

con = duckdb.connect(str(duckdb_path()))
print("counts:", con.execute("SELECT COUNT(*) AS rows, COUNT(DISTINCT property_url) AS unique_urls FROM search_listings").fetchdf())
print(
    con.execute(
        """
        SELECT title, stars, price_current, distance, room_type, neighbourhood
        FROM search_listings
        LIMIT 10
        """
    ).fetchdf()
)
