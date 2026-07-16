"""
m4uhd.page — URL Collector
===========================
Collect every movie/series URL from /new-movies listing pages.

Usage:
    python scraper.py                 # pages 1-2 (default)
    python scraper.py 1 10            # pages 1-10
"""

import sys, json, time, random, logging, os
from curl_cffi import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from dataclasses import dataclass, asdict

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL    = "https://ww1.m4uhd.page"
START_PAGE  = int(sys.argv[1]) if len(sys.argv) > 1 else 1
END_PAGE    = int(sys.argv[2]) if len(sys.argv) > 2 else 2
DELAY_MIN   = 1.5
DELAY_MAX   = 3.0
MAX_RETRIES = 3
TIMEOUT     = 30
OUTPUT_FILE = "movies.json"

# ── Session ───────────────────────────────────────────────────────────────────
S = requests.Session(impersonate="chrome124")

PROXY_URL = os.environ.get("PROXY_URL")
if PROXY_URL:
    S.proxies.update({"http": PROXY_URL, "https": PROXY_URL})
    log.info("Proxy enabled.")

# ── Data model ────────────────────────────────────────────────────────────────
@dataclass
class Entry:
    title: str
    url:   str
    type:  str   # "movie" or "series"


# ── Helpers ───────────────────────────────────────────────────────────────────
def http_get(url: str) -> str | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = S.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:
            log.warning(f"GET {url} attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
    return None


def parse_listing_page(html: str) -> list[Entry]:
    soup    = BeautifulSoup(html, "html.parser")
    entries = []
    for item in soup.select("div.item"):
        anchor = item.select_one("div.imagecover > a")
        if not anchor:
            continue
        href = anchor.get("href", "").strip()
        if not href:
            continue
        url   = urljoin(BASE_URL, href)
        title = anchor.get("title", "").strip() or anchor.get_text(strip=True)
        kind  = "series" if "/watch-tvseries-" in url else "movie"
        entries.append(Entry(title=title, url=url, type=kind))
    return entries


def collect_urls(start: int, end: int) -> list[Entry]:
    all_entries: list[Entry] = []
    for page in range(start, end + 1):
        url  = f"{BASE_URL}/new-movies?page={page}"
        log.info(f"Listing page {page}/{end} → {url}")
        html = http_get(url)
        if html is None:
            log.warning(f"Skipping listing page {page}.")
            continue
        found = parse_listing_page(html)
        log.info(f"Page {page}: {len(found)} entries collected.")
        all_entries.extend(found)
        if page < end:
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    log.info(f"Total URLs collected: {len(all_entries)}")
    return all_entries


def save_json(entries: list[Entry], path: str = OUTPUT_FILE) -> None:
    data = [asdict(e) for e in entries]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info(f"Saved {len(entries)} entries → {path}")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info(f"=== Collecting URLs (pages {START_PAGE}–{END_PAGE}) ===")
    entries = collect_urls(START_PAGE, END_PAGE)

    if not entries:
        log.error("No URLs collected. Check BASE_URL and div.item selectors.")
        sys.exit(1)

    save_json(entries)

    movies = sum(1 for e in entries if e.type == "movie")
    series = sum(1 for e in entries if e.type == "series")
    print(f"\n{'='*65}")
    print(f"Done!  {len(entries)} total  |  {movies} movies  |  {series} series")
    print(f"{'='*65}")
    print(f"{'#':<4} {'Type':<8} {'Title':<38} URL")
    print("-" * 65)
    for i, e in enumerate(entries, 1):
        print(f"{i:<4} {e.type:<8} {e.title[:37]:<38} {e.url}")
