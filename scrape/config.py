"""Shared runtime config. Proxy credentials stay in .env, not in code.

Works in both layouts:
- GitHub repo: this file lives in scrape/
- GCP VM pack: scripts are flattened into ~/scrapper/
"""
from __future__ import annotations

import os
from pathlib import Path

SCRAPE_DIR = Path(__file__).resolve().parent
ROOT = SCRAPE_DIR.parent if SCRAPE_DIR.name == "scrape" else SCRAPE_DIR
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv(SCRAPE_DIR / ".env")
except ImportError:
    pass


def playwright_proxy() -> dict | None:
    server = (os.getenv("PROXY_SERVER") or "").strip()
    if not server:
        return None
    cfg: dict = {"server": server}
    username = (os.getenv("PROXY_USERNAME") or "").strip()
    password = (os.getenv("PROXY_PASSWORD") or "").strip()
    if username:
        cfg["username"] = username
        cfg["password"] = password
    return cfg


def duckdb_path() -> Path:
    raw = (os.getenv("DUCKDB_PATH") or "booking.duckdb").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return path


def describe_proxy() -> str:
    proxy = playwright_proxy()
    if not proxy:
        return "direct (no proxy)"
    return proxy["server"]
