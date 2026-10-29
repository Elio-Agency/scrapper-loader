"""Load existing scrape files into DuckDB and print a short summary."""
from warehouse import ingest_existing, summary, connect


def main():
    loaded = ingest_existing()
    print("Ingested:", loaded, flush=True)
    print("Totals:", summary(), flush=True)

    con = connect()
    try:
        print("\n--- quotes ---", flush=True)
        print(con.execute("SELECT * FROM quotes LIMIT 10").fetchdf().to_string(index=False), flush=True)
        print("\n--- search_listings ---", flush=True)
        print(
            con.execute("SELECT title, price, distance, review_block FROM search_listings LIMIT 10")
            .fetchdf()
            .to_string(index=False),
            flush=True,
        )
        print("\n--- property_rooms ---", flush=True)
        print(
            con.execute("SELECT property_name, room_name, price, sold_out FROM property_rooms LIMIT 10")
            .fetchdf()
            .to_string(index=False),
            flush=True,
        )
    finally:
        con.close()


if __name__ == "__main__":
    main()
