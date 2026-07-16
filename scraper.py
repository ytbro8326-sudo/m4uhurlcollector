"""
m4uhd.page — URL Collector
===========================
Collect every movie/series URL from /new-movies listing pages.
Saves to movies.json, movies2.json, etc. (max 1 MB each).

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
BASE_URL     = "https://ww1.m4uhd.page"
START_PAGE   = int(sys.argv[1]) if len(sys.argv) > 1 else 1
END_PAGE     = int(sys.argv[2]) if len(sys.argv) > 2 else 2
DELAY_MIN    = 1.5
DELAY_MAX    = 3.0
MAX_RETRIES  = 3
TIMEOUT      = 30
MAX_FILE_MB  = 1.0   # max size per JSON file in MB

# ── Proxies ───────────────────────────────────────────────────────────────────
PROXY_USER = "dxicdysy"
PROXY_PASS = "yndikr9coeto"

PROXY_LIST = [
    ("31.59.20.176",    6754),
    ("31.56.127.193",   7684),
    ("45.38.107.97",    6014),
    ("198.105.121.200", 6462),
    ("64.137.96.74",    6641),
    ("198.23.243.226",  6361),
    ("38.154.185.97",   6370),
    ("84.247.60.125",   6095),
    ("142.111.67.146",  5611),
    ("191.96.254.138",  6185),
]

def get_random_proxy() -> dict:
    host, port = random.choice(PROXY_LIST)
    url = f"http://{PROXY_USER}:{PROXY_PASS}@{host}:{port}"
    return {"http": url, "https": url}


# ── Data model ────────────────────────────────────────────────────────────────
@dataclass
class Entry:
    title:   str
    url:     str
    type:    str          # "movie" or "series"
    imdb_id: str = ""
    tmdb_id: str = ""
    server1: str = ""
    server2: str = ""
    server3: str = ""
    server4: str = ""

def entry_to_record(e: Entry) -> dict:
    """Convert to the flat output format."""
    return {
        "title":   e.title,
        "url":     e.url,
        "type":    e.type,
        "imdb_id": e.imdb_id,
        "tmdb_id": e.tmdb_id,
        "server1": e.server1,
        "server2": e.server2,
        "server3": e.server3,
        "server4": e.server4,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────
def http_get(url: str) -> str | None:
    for attempt in range(1, MAX_RETRIES + 1):
        proxy = get_random_proxy()
        host  = proxy["http"].split("@")[1]
        try:
            S = requests.Session(impersonate="chrome124")
            S.proxies.update(proxy)
            r = S.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            log.info(f"  ✓ via {host}")
            return r.text
        except Exception as e:
            log.warning(f"GET {url} attempt {attempt}/{MAX_RETRIES} via {host} failed: {e}")
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


# ── Save with 1 MB splitting ──────────────────────────────────────────────────
def get_json_filename(index: int) -> str:
    """movies.json, movies2.json, movies3.json ..."""
    return "movies.json" if index == 1 else f"movies{index}.json"


def load_existing(filename: str) -> list[dict]:
    """Load existing records from a JSON file if it exists."""
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_with_split(new_entries: list[Entry]) -> None:
    max_bytes    = MAX_FILE_MB * 1024 * 1024
    new_records  = [entry_to_record(e) for e in new_entries]

    # Find which file index to start appending into
    file_index   = 1
    while True:
        fname = get_json_filename(file_index)
        if not os.path.exists(fname):
            break
        size = os.path.getsize(fname)
        if size < max_bytes:
            break
        file_index += 1

    current_records = load_existing(get_json_filename(file_index))

    for record in new_records:
        current_records.append(record)
        serialized = json.dumps(current_records, indent=2, ensure_ascii=False)

        if len(serialized.encode("utf-8")) > max_bytes:
            # Remove last record, save current file, start a new one
            current_records.pop()
            fname = get_json_filename(file_index)
            with open(fname, "w", encoding="utf-8") as f:
                f.write(json.dumps(current_records, indent=2, ensure_ascii=False))
            log.info(f"File {fname} reached 1 MB limit — starting {get_json_filename(file_index + 1)}")
            file_index     += 1
            current_records = [record]

    # Write whatever remains
    fname = get_json_filename(file_index)
    with open(fname, "w", encoding="utf-8") as f:
        f.write(json.dumps(current_records, indent=2, ensure_ascii=False))
    log.info(f"Saved to {fname} ({len(current_records)} records in this file)")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info(f"=== Collecting URLs (pages {START_PAGE}–{END_PAGE}) ===")
    entries = collect_urls(START_PAGE, END_PAGE)

    if not entries:
        log.error("No URLs collected. Check BASE_URL and div.item selectors.")
        sys.exit(1)

    save_with_split(entries)

    movies = sum(1 for e in entries if e.type == "movie")
    series = sum(1 for e in entries if e.type == "series")
    print(f"\n{'='*65}")
    print(f"Done!  {len(entries)} total  |  {movies} movies  |  {series} series")
    print(f"{'='*65}")
    print(f"{'#':<4} {'Type':<8} {'Title':<38} URL")
    print("-" * 65)
    for i, e in enumerate(entries, 1):
        print(f"{i:<4} {e.type:<8} {e.title[:37]:<38} {e.url}")
