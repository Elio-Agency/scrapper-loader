"""
Local HTTP forward proxy (intermediate on this machine).

Traffic path: scraper -> 127.0.0.1:8888 -> internet

This does not change your public IP. For a real intermediate, put a VPS
or paid proxy URL in PROXY_SERVER instead, then skip this script.
"""
import subprocess
import sys

DEFAULT_LISTEN = "http://:8888"


def main():
    listen = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LISTEN
    print(f"Starting local proxy on {listen}", flush=True)
    print("Point PROXY_SERVER at http://127.0.0.1:8888 in .env", flush=True)
    raise SystemExit(subprocess.call([sys.executable, "-m", "pproxy", "-l", listen]))


if __name__ == "__main__":
    main()
